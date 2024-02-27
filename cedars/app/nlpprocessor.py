"""
This module contatins the class to perform NLP operations for the CEDARS project
"""
import re
import sys
from typing import Optional
from flask import current_app
from flask_login import current_user
from concurrent.futures import ProcessPoolExecutor, as_completed
import pandas as pd
import spacy
from spacy.matcher import Matcher
from loguru import logger
from tqdm import tqdm
from . import db

logger.enable(__name__)

# Filter keywords
def query_to_patterns(query: str) -> list:
    """
    Expected query will be a set of keywords separated
    by OR keyword.

    Each expression separated by OR can have expressions
    combined by AND or NOT and the keywords can also contain
    wildcards.

    ##### Spacy Requirements:
    - ! - negation
    - Each dictionary in a list matches one token only
    - A list matches all the dictionaries inside it (and condition)
    - A list of list contains OR conditions
      - [{"TEXT": {"REGEX": "abc*"}}] represents one token with regex match
      - [{"LOWER": "dvt"}] matches case-insenstitive  DVT
      - [{"LEMMA": "embolus"}] matches the lemmatized version of embolus as well in text

    ##### Implementation:
      1. Split the query by OR
      2. Split each expression by AND
      3. Split each expression by NOT
      4. Split each expression by wildcard
      5. Convert each expression to a spacy pattern
      6. Combine the patterns
      7. Return the combined pattern
    """
    def get_regex_dict(token):
        # Replace '*' with '.*' and '?' with '.'
        regex_pattern = '(?i)' + token.replace('*', '.*').replace('?', '\w?')
        return {"TEXT": {"REGEX": regex_pattern}}

    def get_lemma_dict(token):
        return {"LEMMA": token}
    
    def get_negated_dict(token):
        return {"LOWER": token, "OP": "!"}

    or_expressions = query.split(" OR ")
    res = [[] for _ in range(len(or_expressions))]
    for i, expression in enumerate(or_expressions):
        spacy_pattern = []
        expression = expression.strip().replace("(", "").replace(")", "")
        and_expressions = expression.split(" AND ")
        for tok in and_expressions:
            tok = tok.strip()
            if not tok:
                continue
            if "*" in tok or "?" in tok:
                spacy_pattern.append(get_regex_dict(tok))
            elif "!" in tok:
                spacy_pattern.append(get_negated_dict(tok.replace("!", "")))
            else:
                spacy_pattern.append(get_lemma_dict(tok))
        # logger.debug(f"{expression} -> {spacy_pattern}")
        res[i] = spacy_pattern
    return res


def is_negated(span):
    """
    ##### Negation Detection

    This function takes a spacy token and determines if it has been negated in the sentence.
    ```
    Ex.
    This is not an apple.
    In the above sentence, the token apple is negated.
    ```

    Args:
        spacy token : This is a token of a single word after spacy
        runs a model on some text.

    Returns:
        (bool) : True if the token is negated in the sentence.
    """
    neg_words = ['no','not',"n't","wouldn't",'never','nobody','nothing',
                 'neither','nowhere','noone',
                 'no-one','hardly','scarcely','barely']

    for token in span.subtree:
        parents = list(token.ancestors)
        children = list(token.children)

        for parent in token.ancestors:
            children.extend(list(parent.children))

        if ("neg"in [child.dep_ for child in children]) or ("neg" in [par.dep_ for par in parents]):
            return True

        parents_text = [par.text for par in parents]
        children_text = [child.text for child in children]

        for word in neg_words:
            if word in parents_text or word in children_text:
                return True

    return False

class NlpProcessor:
    """
    This class stores a sci-spacy model and functions needed to run it on medical notes.
    """
    def __new__(cls, model_name = "en_core_sci_lg"):
        """
        Loads the model

        Args:
            model_name (str) : Name of the sci-spacy model we wish to use.
        Returns:
            None
        """
        if not hasattr(cls, 'instance'):
            cls.instance = super(NlpProcessor, cls).__new__(cls)

            try:
                cls.nlp_model = spacy.load(model_name)
                                        
            except Exception as exc:
                logger.critical("Spacy model %s failed to load.", model_name)
                raise FileNotFoundError(f"Spacy model {model_name} failed to load.") from exc
        return cls.instance


    def process_notes(self, patient_id = None, processes=1, batch_size=20):
        """
        ##### Process Query Matching
        
        This function takes a medical note and a regex query as input and annotates
        the relevant sections of the text.
        """
        # nlp_model = spacy.load(model_name)
        matcher = Matcher(self.nlp_model.vocab)
        assert len(matcher) == 0
        query = db.get_search_query()

        # load previosly processed documents
        # document_processed = load_progress()
        spacy_patterns = query_to_patterns(query)
        for i, item in enumerate(spacy_patterns):
            matcher.add(f"DVT_{i}", [item])

        # check all documents already processed
        if patient_id is not None:
            documents_to_process = db.get_patient_notes(patient_id)
        else:
            documents_to_process = db.get_documents_to_annotate()
        document_list = [document for document in documents_to_process]
        document_text = [document["text"] for document in document_list]
        logger.info(f"Found {len(document_list)}/{db.get_total_counts('NOTES')} to process")
        logger.info(f"sample document: {document_text[0][:100]}")
        annotations = self.nlp_model.pipe([document["text"].lower() for document in document_list],
                                          n_process=processes,
                                          batch_size=batch_size)
        logger.info(f"Starting to process document annotations: {len(document_text)}")
        count = 0
        for document, doc in zip(document_list, annotations):
            match_count = 0
            for sent_no, sentence_annotation in enumerate(doc.sents):
                sentence_text = sentence_annotation.text
                matches = matcher(sentence_annotation)
                for match in matches:
                    match_count += 1
                    token_id, start, end = match
                    token = sentence_annotation[start:end]
                    has_negation = is_negated(token)
                    start_index = sentence_text.find(token.text, start)
                    end_index = start_index + len(token.text)
                    token_start = token.start_char
                    token_end = token_start + len(token.text)
                    annotation = {
                                    "sentence" : sentence_text,
                                    "token" : token.text,
                                    "isNegated" : has_negation,
                                    "start_index" : start_index,
                                    "end_index" : end_index,
                                    "note_start_index" : token_start,
                                    "note_end_index" : token_end,
                                    "sentence_number" : sent_no
                                    }
                    annotation['note_id'] = document["text_id"]
                    annotation["text_date"] = document["text_date"]
                    annotation["patient_id"] = document["patient_id"]
                    annotation["event_date"] = None
                    annotation["comments"] = []
                    annotation["reviewed"] = False
                    db.insert_one_annotation(annotation)
            if match_count == 0:
                db.mark_note_reviewed(document["text_id"], reviewed_by="CEDARS")
            count += 1
            if (count + 1) % 10 == 0:
                logger.info(f"Processed {count+1} / {len(document_list)} documents")


    def process_patient_pines(self, patient_id: int, threshold: float = 0.95) -> None:
        """
        For each patient who are unreviewed,

        1. Get all notes for which annotations are present
        2. Get the predictions for each note and save it in the pines collection
        3. If note prediction is 
            a. Below threshold
                i. Mark all annotation as reviewed
                ii. Update the patient reviewed status based on all notes reviewed status
            b. Above threshold: Update the pines database
        """

        notes = db.get_annotated_notes_for_patient(patient_id)
        logger.info(f"Found {len(notes)} annotated notes for patient {patient_id}")
        if len(notes) == 0:
            db.mark_patient_reviewed(patient_id, reviewed_by="CEDARS")
            logger.debug(f"Marked patient {patient_id} as reviewed")
            return
        
        db.predict_and_save(notes)
        scores = []
        for note_id in notes:
            score = db.get_note_prediction_from_db(note_id)
            scores.append(score)
            if score < threshold:
                updated_annots = db.update_annotation_reviewed(note_id)
                db.mark_note_reviewed(note_id, reviewed_by="PINES")
                logger.info(f"Marked {updated_annots} annotations as reviewed for note {note_id} with score {score}")
        
        if max(scores) < threshold:
            db.mark_patient_reviewed(patient_id, reviewed_by="PINES")
            logger.debug(f"Marked patient {patient_id} as reviewed")
        
    def automatic_nlp_processor(self, patient_id = None):
        """
        This function is used to perform and save NLP annotations
        on one or all patients saved in the database.
        If patient_id == None we will do this for all patients in the database.
        """
        for patient_id in db.get_patient_ids():
            try:
                db.add_task(self.process_notes,
                            job_id = f"spacy:{patient_id}",
                            patient_id=patient_id,
                            user=current_user.username,
                            description="cedars service",
                            on_success=db.report_success,
                            on_failure=db.report_failure
                            )
                
                db.add_task(self.process_patient_pines,
                            job_id = f"pines:{patient_id}",
                            patient_id=patient_id,
                            user=current_user.username,
                            description="pines service", 
                            depends_on=f"spacy:{patient_id}",
                            on_success=db.report_success,
                            on_failure=db.report_failure
                            )
            except:
                logger.debug(f"error while processing patient: {sys.exc_info()}")
            finally:
                logger.debug(f"error while processing patient: {sys.exc_info()}")
