"""
This module contatins the class to perform NLP operations for the CEDARS project
"""
import spacy
from spacy.matcher import Matcher
from loguru import logger
from . import db

logger.enable(__name__)


def get_regex_dict(token):
    if "*" in token:
        token = token.replace("*", ".*")
    if "?" in token:
        token = token.replace("?", ".")
    return {"TEXT": {"REGEX": rf"\b{token}\b"}}


def get_lemma_dict(token):
    return {"LEMMA": token}


def get_negated_dict(token):
    return {"LOWER": token, "OP": "!"}


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
        logger.debug(f"{expression} -> {spacy_pattern}")
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
    neg_words = ['no', 'not', "n't", "wouldn't", 'never', 'nobody', 'nothing',
                 'neither', 'nowhere', 'noone', 'no-one', 'hardly', 'scarcely', 'barely']

    for token in span.subtree:
        parents = list(token.ancestors)
        children = list(token.children)

        for parent in token.ancestors:
            children.extend(list(parent.children))

        if ("neg" in [child.dep_ for child in children]) or ("neg" in [par.dep_ for par in parents]):
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
    def __new__(cls, model_name="en_core_sci_lg"):
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
                # TODO make sure this is correct
                cls.matcher = Matcher(cls.nlp_model.vocab)
                cls.query = db.get_search_query()
            except Exception as exc:
                logger.critical("Spacy model %s failed to load.", model_name)
                raise FileNotFoundError(f"Spacy model {model_name} failed to load.") from exc
        return cls.instance

    def process_notes(self, patient_id, processes=1, batch_size=20):
        """
        ##### Process Query Matching

        This function takes a medical note and a regex query as input and annotates
        the relevant sections of the text.
        """
        # nlp_model = spacy.load(model_name)
        assert len(self.matcher) == 0
        query = db.get_search_query()

        # load previosly processed documents
        # document_processed = load_progress()
        spacy_patterns = query_to_patterns(query)
        for i, item in enumerate(spacy_patterns):
            self.matcher.add(f"DVT_{i}", [item])

        # check all documents already processed
        documents_to_process = []
        if patient_id is not None:
            # get all note for patient which are not reviewed
            documents_to_process = db.get_documents_to_annotate(patient_id)
        else:
            # get all notes which are not in annotation collection.
            documents_to_process = db.get_documents_to_annotate()

        document_list = [document for document in documents_to_process]
        if len(document_list) == 0:
            # no notes found to annotate
            logger.info(f"No documents to process for patient {patient_id}")
            if db.get_search_query("tag_query")["nlp_apply"] is True:
                self.process_patient_pines(patient_id)
            return

        document_text = [document["text"] for document in document_list]
        if patient_id is not None:
            logger.info(f"Found {len(document_list)}/{db.get_total_counts('NOTES', patient_id=patient_id)} to process")
        else:
            logger.info(f"Found {len(document_list)}/{db.get_total_counts('NOTES')} documents to process")

        # logger.info(f"sample document: {document_text[0][:100]}")
        annotations = self.nlp_model.pipe([document["text"].lower() for document in document_list],
                                          n_process=processes,
                                          batch_size=batch_size)
        logger.info(f"Starting to process document annotations: {len(document_text)}")
        count = 0
        docs_with_annotations = 0
        for document, doc in zip(document_list, annotations):
            match_count = 0
            for sent_no, sentence_annotation in enumerate(doc.sents):
                sentence_text = sentence_annotation.text
                matches = self.matcher(sentence_annotation)
                for match in matches:
                    _, start, end = match
                    token = sentence_annotation[start:end]
                    has_negation = is_negated(token)
                    start_index = sentence_text.find(token.text, start)
                    end_index = start_index + len(token.text)
                    token_start = token.start_char
                    token_end = token_start + len(token.text)
                    annotation = {
                                    "sentence": sentence_text,
                                    "token": token.text,
                                    "isNegated": has_negation,
                                    "start_index": start_index,
                                    "end_index": end_index,
                                    "note_start_index": token_start,
                                    "note_end_index": token_end,
                                    "sentence_number": sent_no
                                    }
                    annotation['note_id'] = document["text_id"]
                    annotation["text_date"] = document["text_date"]
                    annotation["patient_id"] = document["patient_id"]
                    annotation["event_date"] = None
                    annotation["reviewed"] = False
                    db.insert_one_annotation(annotation)
                    if not has_negation:
                        if match_count == 0:
                            docs_with_annotations += 1
                        match_count += 1

            if match_count == 0:
                db.mark_note_reviewed(document["text_id"], reviewed_by="CEDARS")
            count += 1
            if (count) % 10 == 0:
                logger.info(f"Processed {count} / {len(document_list)} documents")

        # check if nlp processing is enabled
        if docs_with_annotations > 0 and db.get_search_query("tag_query")["nlp_apply"] is True:
            logger.info(f"Processing {docs_with_annotations} documents with PINES")
            self.process_patient_pines(patient_id)

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

    def automatic_nlp_processor(self, patient_id=None, **kwargs):
        """
        This function is used to perform and save NLP annotations
        on one or all patients saved in the database.
        If patient_id == None we will do this for all patients in the database.
        """

        # Retrieve all patient ids where patient was not reviewed
        if not patient_id:
            patient_ids = db.get_patient_ids()
            logger.info(f"Found {len(patient_ids)} patients to process")
        else:
            patient_ids = [patient_id]
            logger.info(f"Processing patient {patient_id}")

        for patient_id in patient_ids:
            task = {
                "job_id": kwargs.get("job_id", None),
                "name": "nlp_processor",
                "description": kwargs.get("description", "NLP Processor"),
                "user": kwargs.get("user", None),
                "complete": False,
                "progress": 0
            }
            # check if the task is completed for the patient already
            # if not, add the task to the database
            existing_task = db.get_task(task["job_id"])

            if not existing_task or existing_task["complete"] is False:
                if not existing_task:
                    db.add_task(task)
                db.set_patient_lock_status(patient_id, True)
                self.process_notes(patient_id)
            else:
                logger.info(f"Task {task['job_id']} already completed")
