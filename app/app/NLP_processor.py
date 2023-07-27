import re
import logging
import spacy

class NLP_processor:
    """
    This class stores a sci-spacy model and functions needed to run it on medical notes.
    """
    def __new__(self, model_name = "en_core_sci_lg"):
        """
        Loads the model
        """
        if not hasattr(self, 'instance'):
            self.instance = super(NLP_processor, self).__new__(self)
            self.nlp_model = spacy.load(model_name)
        return self.instance

    def process_note(self, note, regex_query):
        """
        This function takes a medical note and a regex query as input and annotates the relevant sections of the text.
        ------
        ARGS
        note (str) :- This is a string representing the doctor's note.
        regex_query (str) :- This string is a regex pattern for information a doctor may want.
        ----
        Return type 
        This returs a list of dictionaries. Each dictionary contains the annotation and location of where this occurrence can be found.
        """
        doc = self.nlp_model(note)
        pattern = re.compile(regex_query)
        
        marked_flags = []
        
        for sent_no, sentence_annotation in enumerate(doc.sents):
            tokens = list(sentence_annotation.subtree)
            start_index = tokens[0].idx
        
            
            
            for token in tokens:
                has_negation = self.is_negated(token)
                if bool(pattern.match(token.lemma_)):                
                    start = token.idx - start_index
                    end = start + len(token.text)
                    marked_flags.append({"sentence" : sentence_annotation.text, "token" : token.text, 
                                        "lemma" : token.lemma_, "isNegated" : has_negation, 
                                        "start_index" : start, "end_index" : end, 
                                        "sentence_number" : sent_no})
                    
        return marked_flags
    

    def is_negated(self, token):
        """
        This function takes a spacy token and determines if it has been negated in this sentence.

        Ex. 
        This is not an apple.
        In the above sentence, the token apple is negated.
        ------
        ARGS
        token (spacy token) :- This is a token of a single word after spacy runs a model on some text.
        ----
        Return type 
        Boolean
        """
        neg_words = ['no','not',"n't","wouldn't",'never','nobody','nothing','neither','nowhere','noone',
                            'no-one','hardly','scarcely','barely']
        
        parents = [i for i in token.ancestors]
        
        children = list(token.children)
        
        for parent in token.ancestors:
            children.extend([i for i in parent.children])
        
        if ("neg" in [child.dep_ for child in children]) or ("neg" in [par.dep_ for par in parents]):
            return True
        
        parents_text = [par.text for par in parents]
        children_text = [child.text for child in children]
        
        for word in neg_words:
            if word in parents_text or word in children_text:
                return True
            
        return False
    

    def automatic_nlp_processor(self, database_connector, query, patient_id = None):
        """
        This function is used to perform and save NLP annotations
        on one or all patients saved in the database.
        If patient_id == None we will do this for all patients in the database.
        
        Args:
            query (str) : Regex query of all what terms the researcher is looking for.
            patient_id (int) : The ID of a patient we want to perform these annotations for.
            
        Returns:
            None

        Raises:
            None
        """
        if patient_id is not None:
            patient_ids = [patient_id]
        else:
            patients = database_connector.get_all_patients()

            patient_ids = [patient["patient_id"] for patient in patients]

        logging.info("Starting annotation of patients for query : %s.", query)
        for p_id in patient_ids:
            logging.info("Annotating patient #%s.", str(p_id))
            self.annotate_single(database_connector, query, p_id)

        logging.info("Completed annotation of patients for query : %s.", query)

    def annotate_single(self, database_connector, query, patient_id):
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

        Raises:
            None
        """
        database_connector.set_patient_lock_status(patient_id, True)
        foundAnyAnnotations = False


        for note in database_connector.get_patient_notes(patient_id):
            try:
                note_id = note["_id"]
                instances = self.process_note(note["text"], query)

                for inst in instances:
                    annotation = inst.copy()
                    annotation['note_id'] = note_id
                    annotation["patient_id"] = note["patient_id"]
                    annotation["event_date"] = None
                    annotation["comments"] = []
                    annotation["reviewed"] = False

                    database_connector.insert_one_annotation(annotation)
                    foundAnyAnnotations = True
            except Exception as exc:
                logging.error("""While computing annotations for patient #%s, 
                              on note with id %s,
                              threw error %s.""", 
                              str(patient_id), str(note_id), str(exc))
                break
        
        if foundAnyAnnotations:
            database_connector.mark_patient_reviewed(patient_id, False)
        else:
            database_connector.mark_patient_reviewed(patient_id, True)

        database_connector.set_patient_lock_status(patient_id, False)
