"""
This module contatins the class to perform NLP operations for the CEDARS project
"""
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
import spacy
from spacy.matcher import Matcher
from loguru import logger
from tqdm import tqdm
from . import db

logger.enable(__name__)

def query_to_patterns(query: str) -> list:
    """
    Expected query will be a set of keywords separated
    by OR keyword.

    Each expression separated by OR can have expressions
    combined by AND or NOT and the keywords can also contain
    wildcards.

    Spacy Requirements:
    ! - negation
    Each dictionary in a list matches one token only
    A list matches all the dictionaries inside it (and condition)
    A list of list contains OR conditions
    [{"TEXT": {"REGEX": "abc*"}}] represents one token with regex match
    [{"LOWER": "dvt"}] matches case-insenstitive  DVT
    [{"LEMMA": "embolus"}] matches the lemmatized version of embolus as well in text

    Implementation:
    1. Split the query by OR
    2. Split each expression by AND
    3. Split each expression by NOT
    4. Split each expression by wildcard
    5. Convert each expression to a spacy pattern
    6. Combine the patterns
    7. Return the combined pattern
    """
    def get_regex_dict(token):
        return {"TEXT": {"REGEX": token}}

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
    This function takes a spacy token and determines if it has been negated in this sentence.

    Ex.
    This is not an apple.
    In the above sentence, the token apple is negated.

    Args:
        token (spacy token) : This is a token of a single word after spacy
        runs a model on some text.

    Returns:
        (bool) : True if the token is negated in the sentence.
    Raises:
        None
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

    def process_note(self, note: str):
        """
        This function takes a medical note and a regex query as input and annotates
        the relevant sections of the text.
        """
        doc = self.nlp_model(note)
        matcher = Matcher(self.nlp_model.vocab)
        assert len(matcher) == 0
        marked_flags = []
        query = db.get_search_query()
        spacy_patterns = query_to_patterns(query)
        for i, item in enumerate(spacy_patterns):
            matcher.add(f"DVT_{i}", [item])

        # TODO: check sentence boundaries 
        for sent_no, sentence_annotation in enumerate(doc.sents):
            sentence_text = sentence_annotation.text
            matches = matcher(sentence_annotation)
            for match in matches:
                token_id, start, end = match
                token = sentence_annotation[start:end]
                # print(start, end, token.text)
                # print(sentence_annotation)
                has_negation = is_negated(token)
                start_index = sentence_text.find(token.text, start)
                end_index = start_index + len(token.text)
                token_start = token.start_char
                token_end = token_start + len(token.text)
                marked_flags.append({"sentence" : sentence_text,
                                    "token" : token.text,
                                    "lemma" : "", # token.lemma_
                                    "isNegated" : has_negation,
                                    "start_index" : start_index,
                                    "end_index" : end_index,
                                    "note_start_index" : token_start,
                                    "note_end_index" : token_end,
                                    "sentence_number" : sent_no})

        return marked_flags


    def process_patient(self, p_id):
        """
        Processs  a single patient
        """
        logger.debug(f"Annotating patient #{p_id}")
        self.annotate_single(p_id)


    def automatic_nlp_processor(self, patient_id = None):
        """
        This function is used to perform and save NLP annotations
        on one or all patients saved in the database.
        If patient_id == None we will do this for all patients in the database.
        """

        if patient_id is not None:
            patient_ids = [patient_id]
        else:
            patients = db.get_all_patients()
            patient_ids = [patient["patient_id"] for patient in patients]

        logger.info("Starting annotation of patients")

        num_threads = min(7, len(patient_ids))
        
        with ProcessPoolExecutor(max_workers=num_threads) as executor:
            future_to_patient = {executor.submit(self.process_patient, p_id): p_id for p_id in patient_ids}

        with tqdm(total=len(patient_ids)) as pbar:
            for future in as_completed(future_to_patient):
                patient = future_to_patient[future]
                try:
                    future.result()
                    pbar.update(1)
                except Exception as exc:
                    logger.error('%r generated an exception: %s' % (patient, exc))

        logger.info("Completed annotation of patients for query")
        # for p_id in patient_ids:
        #     logger.info("Annotating patient #%s.", str(p_id))
        #     self.annotate_single(p_id)

        # logger.info("Completed annotation of patients for query")

    def annotate_single(self, patient_id):
        """
        This function is used to perform and save NLP annotations on a
        single patient saved in the database.
        The patient information in the PATIENTS collection is also
        appropriately updated during this process.
        """
        # TODO: make this parallel (fixme)

        try:
            db.set_patient_lock_status(patient_id, True)
            has_relevant_notes = False
            for note in db.get_patient_notes(patient_id):
                note_id = note["_id"]  # should be text_id
                note_date = note["text_date"]
                instances = self.process_note(note["text"])

                if len(instances) > 0:
                    for inst in instances:
                        annotation = inst.copy()
                        annotation['note_id'] = note_id
                        annotation["text_date"] = note_date
                        annotation["patient_id"] = note["patient_id"]
                        annotation["event_date"] = None
                        annotation["comments"] = []
                        annotation["reviewed"] = False

                        db.insert_one_annotation(annotation)
                        has_relevant_notes = True

            if has_relevant_notes:
                db.mark_patient_reviewed(patient_id, False)
            else:
                db.mark_patient_reviewed(patient_id, True)
        finally:
            db.set_patient_lock_status(patient_id, False)
