"""
This module contatins the class to perform NLP operations for the CEDARS project
"""
import re
import logging
import spacy

from . import db

def is_negated(token):
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
                logging.critical("Spacy model %s failed to load.", model_name)
                raise FileNotFoundError(f"Spacy model {model_name} failed to load.") from exc
        return cls.instance

    def process_note(self, note, regex_query):
        """
        This function takes a medical note and a regex query as input and annotates
        the relevant sections of the text.

        Args:
            note (str) : This is a string representing the doctor's note.
            regex_query (str) : This string is a regex pattern for information a doctor may want.
        Returns:
            marked_flags (list) : A list of dictionaries.
            Each dictionary contains the annotation and location of where this occurrence
            can be found.
        """
        doc = self.nlp_model(note)
        pattern = re.compile(regex_query)

        marked_flags = []

        for sent_no, sentence_annotation in enumerate(doc.sents):
            tokens = list(sentence_annotation.subtree)
            start_index = tokens[0].idx


            for token in tokens:
                has_negation = is_negated(token)
                if bool(pattern.match(token.lemma_)):
                    start = token.idx - start_index
                    end = start + len(token.text)
                    marked_flags.append({"sentence" : sentence_annotation.text,
                                         "token" : token.text,
                                         "lemma" : token.lemma_,
                                         "isNegated" : has_negation,
                                         "start_index" : start,
                                         "end_index" : end,
                                         "sentence_number" : sent_no})

        return marked_flags


    def automatic_nlp_processor(self, patient_id = None):
        """
        This function is used to perform and save NLP annotations
        on one or all patients saved in the database.
        If patient_id == None we will do this for all patients in the database.

        Args:
            query (str) : Regex query of all what terms the researcher is looking for.
            patient_id (int) : The ID of a patient we want to perform these annotations for.
        Returns:
            None
        """
        query = db.get_search_query()
        if patient_id is not None:
            patient_ids = [patient_id]
        else:
            patients = db.get_all_patients()

            patient_ids = [patient["patient_id"] for patient in patients]

        logging.info("Starting annotation of patients for query : %s.", query)
        for p_id in patient_ids:
            logging.info("Annotating patient #%s.", str(p_id))
            self.annotate_single(query, p_id)

        logging.info("Completed annotation of patients for query : %s.", query)

    def annotate_single(self, query, patient_id):
        """
        This function is used to perform and save NLP annotations on a
        single patient saved in the database.
        The patient information in the PATIENTS collection is also
        appropriately updated during this process.

        Args:
            query (str) : Regex query of all what terms the researcher is looking for.
            patient_id (int) : The ID of a patient we want to perform these annotations for.
        Returns:
            None
        """
        # TODO: make this parallel (fixme)

        try:
            db.set_patient_lock_status(patient_id, True)
            has_relevant_notes = False
            for note in db.get_patient_notes(patient_id):
                note_id = note["_id"]  # should be text_id
                instances = self.process_note(note["text"], query)

                if len(instances) > 0:
                    for inst in instances:
                        annotation = inst.copy()
                        annotation['note_id'] = note_id
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
