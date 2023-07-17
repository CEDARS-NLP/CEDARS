"""
Abstract Class to interact with the spacy model for the CEDARS project.
"""
import logging
from nltk.tokenize import sent_tokenize
import spacy
from spacy.matcher import Matcher
from negspacy.termsets import termset



class NLPPipeline:
    """
    Class to store nlp models and functions to abstract the pipelines
    """
    def __init__(self, model_name):
        """
        Loads spacy model and expression matcher.

        Args:
            model_name (str) : Name of a downloaded spacy model.

        Returns:
            None

        Raises:
            Exception: Spacy model loading raised an error due to invalid model name.
        """
        try:
            self.spacy_model = spacy.load(model_name)
        except Exception as exc:
            logging.critical('Spacy model loading raised an error due to invalid model name.')

            raise exc

        term_set = termset("en")

        self.spacy_model.add_pipe("negex", config={
        "neg_termset":term_set.get_patterns()
    })


        self.expression_matcher = Matcher(self.spacy_model.vocab)

    def add_regex_pattern(self, reg_pattern, pattern_name, pattern_type = "TEXT"):
        """
        Stores a regex pattern with the type of event it is supposed to match to

        Args:
            reg_pattern (str) : Query in regex format.
            pattern_name (str) : Name of this query.
            pattern_type (str) : Type of pattern we are looking for.
                    For more info look at https://spacy.io/usage/rule-based-matching#phrasematcher

        Returns:
            None

        Raises:
            None
        """

        pattern = [{pattern_type: {"REGEX": reg_pattern}}]

        self.expression_matcher.add(pattern_name, [pattern])


    def annotate_text(self, text):
        """
        Runs the core NLP pipeline to convert plain-text to annotated format

        Args:
            text (str) : String of a doctor's note.

        Returns:
            annotations (list) : A list of all annotations found in the text.

        Raises:
            None
        """

        tokens = self.tokenize(text)
        annotations = []
        for sent in tokens:
            for annotation in self.spacy_model(sent):
                annotations.append(annotation)

        return annotations

    def run_matcher(self, text):
        """
        Runs and stores output of the token matcher

        Args:
            text (str) : String of a sentence from a doctor's note.

        Returns:
            annotations (list) : A list of all annotations found in the text.

        Raises:
            None
        """

        doc = self.spacy_model(text)
        matches = self.expression_matcher(doc)

        annotations = []

        for match_id, start, end in matches:
            string_id = self.spacy_model.vocab.strings[match_id]  # Get string representation
            span = doc[start:end]  # The matched span

            annotation = {"alert_type" : string_id, # "id" : match_id,
                          "start_index" : start,
                          "end_index" : end,
                          "flagged_word" : span.text}

            annotations.append(annotation)

        return annotations

    def tokenize(self, text):
        """
        Tokenizes the text into sentences

        Args:
            text (str) : String of a doctor's note.

        Returns:
           sentences (list) : A list of all sentences in the text.

        Raises:
            None
        """
        return sent_tokenize(text)
