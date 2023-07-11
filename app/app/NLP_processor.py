import re
import spacy

class NLP_processor:
    """
    This class stores a sci-spacy model and functions needed to run it on medical notes.
    """
    def __init__(self, model_name = "en_core_sci_lg"):
        """
        Loads the model
        """
        self.nlp_model = spacy.load(model_name)

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