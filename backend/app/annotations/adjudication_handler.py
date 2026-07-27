"""Faithful port of cedars/app/adjudication_handler.py to the v2 stack.

The core adjudication state machine (index navigation, review marking, event
date handling, skip logic, duplicate filtering) is preserved verbatim from v1.
Only two things are adapted for v2:

1. Annotation IDs are UUID strings (v2) instead of Mongo ``ObjectId`` (v1), so the
   ``ObjectId(...)`` conversion in :meth:`AdjudicationHandler.mark_event_date` is
   dropped and string IDs are compared directly.
2. In v1 each keyword match was its own annotation document, so highlighting
   iterated sibling annotations. In v2 an annotation is one matched *sentence*
   carrying its matched tokens in a ``tokens`` list (from ``annotation_tokens``),
   so :class:`SentenceHighlighter` reads token spans from that list.

Enums mirror ``cedars/app/cedars_enums.py`` exactly (int-valued) because
``patient_data['review_statuses']`` stores these values.
"""

import datetime
import html
import logging
from enum import Enum
from functools import wraps

logger = logging.getLogger(__name__)


def log_function_call(func):
    """No-op decorator preserved from v1 so ported method bodies stay verbatim."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


class ReviewStatus(Enum):
    """Review status of an annotation (mirrors cedars_enums.ReviewStatus)."""

    UNREVIEWED = 0
    REVIEWED = 1
    SKIPPED = 2


class PatientStatus(Enum):
    """Adjudication status for a patient (mirrors cedars_enums.PatientStatus)."""

    NO_ANNOTATIONS = 0
    REVIEWED_WITH_EVENT = 1
    REVIEWED_NO_EVENT = 2
    UNDER_REVIEW = 3


class AdjudicationHandler:
    '''
    This is a class meant to handle the logic of
    the adjudication workflow in CEDARS for a patient.
    '''

    def __init__(self, patient_id):
        self.patient_id = patient_id
        self.patient_data = {
            'event_date': None,
            'event_annotation_id': None,
            'annotation_ids': [],
            'review_statuses': [],
            'current_index': -1
        }

    @log_function_call
    def init_patient_data(self, raw_annotations, hide_duplicates,
                          stored_event_date=None, stored_annotation_id=None):
        '''
        This function will accept the annotations for that patient and
        select which annotation to show first using the current index.
        It will also initialize and return a JSON-like object that stores
        relevant data about that patient.
        '''

        logger.info("Starting filter strategy...")
        filter_strat = AnnotationFilterStrategy()
        filtered_results, annotations_with_duplicates = filter_strat.filter_annotations(
            raw_annotations, hide_duplicates)

        logger.info("Finished filter strategy.")
        annotation_ids = filtered_results['annotation_ids']
        review_statuses = filtered_results['review_statuses']
        annotations = filtered_results['annotations']
        index = 0
        try:
            # Find the index of the first unreviewed index
            index = review_statuses.index(ReviewStatus.UNREVIEWED)
        except ValueError:
            # A ValueError is thrown if the element being searched for
            # does not exist in the list.
            # In this case if there are no unreviewed indices, we default
            # to the index of the event date if one exists and if not we select index 0.

            if stored_event_date and stored_annotation_id:
                index = annotation_ids.index(stored_annotation_id)

        self.patient_data = {
            'event_date': stored_event_date,
            'event_annotation_id': stored_annotation_id,
            'annotation_ids': annotation_ids,
            'review_statuses': review_statuses,
            'current_index': index,
            'annotations': annotations
        }

        return self.patient_data, annotations_with_duplicates

    @log_function_call
    def load_from_patient_data(self, patient_id, patient_data):
        '''
        Loads the handler object form data for an ongoing patient's adjudication.
        '''
        self.patient_id = patient_id
        self.patient_data = patient_data

    @log_function_call
    def get_patient_data(self):
        return self.patient_data

    @log_function_call
    def get_curr_annotation(self):
        return self.patient_data['annotations'][self.patient_data['current_index']]

    @log_function_call
    def get_curr_annotation_id(self):
        return self.patient_data['annotation_ids'][self.patient_data['current_index']]

    @log_function_call
    def get_all_annotations_for_curr_note(self):
        """
        This function is used to get all the annotations from the note which
        the current annotation belongs to. Negated annotations are removed from the final
        output.
        Order of annotations -
            text_date (ascending)
            sentence_number (ascending)
        """
        note_id = self.get_curr_annotation()['note_id']

        note_annotations = []
        for annotation in self.patient_data['annotations']:
            if annotation['note_id'] == note_id and annotation['isNegated'] is False:
                note_annotations.append(annotation)

        # Sort by text_date, then by sentence_number
        sorting_function = lambda entry: (entry['text_date'],
                                          entry['sentence_number'])
        sorted_annotations = sorted(note_annotations, key=sorting_function)

        return sorted_annotations

    @log_function_call
    def get_all_annotations_for_curr_sentence(self):
        """
        This function is used to get all the annotations from the sentence which
        the current annotation belongs to. Negated annotations are removed from the final
        output.
        Order of annotations -
            text_date (ascending)
            note_start_index (ascending)
        """
        curr_anno = self.get_curr_annotation()
        note_id = curr_anno['note_id']
        sentence_number = curr_anno['sentence_number']

        note_annotations = []
        for annotation in self.patient_data['annotations']:
            correct_note = annotation['note_id'] == note_id
            correct_sentence = annotation['sentence_number'] == sentence_number
            is_not_negated = annotation['isNegated'] is False
            if correct_note and correct_sentence and is_not_negated:
                note_annotations.append(annotation)

        # Sort by text_date, then by sentence_number
        sorting_function = lambda entry: (entry['text_date'],
                                          entry['note_start_index'])
        sorted_annotations = sorted(note_annotations, key=sorting_function)

        return sorted_annotations

    @log_function_call
    def get_annotation_details(self, annotation, note, comments,
                               annotations_for_note, annotations_for_sentence):
        '''
        Get the details for the current annotation that is to be showed to the annotator.
        '''
        text_highlighter = SentenceHighlighter()
        annotation_data = {
            "pos_start": self.patient_data['current_index'] + 1,
            "total_pos": len(self.patient_data['annotation_ids']),
            "patient_id": self.patient_id,
            "note_date": self._format_date(annotation.get('text_date')),
            "event_date": self._format_date(self.patient_data['event_date']),
            "note_comment": comments,
            "highlighted_sentence": text_highlighter.get_highlighted_sentence(annotation,
                                                                              note,
                                                                              annotations_for_sentence),
            "note_id": annotation["note_id"],
            "full_note": text_highlighter.get_highlighted_text(note,
                                                               annotations_for_note),
            "tags": [note.get("text_tag_1", ""),
                     note.get("text_tag_2", ""),
                     note.get("text_tag_3", ""),
                     note.get("text_tag_4", ""),
                     note.get("text_tag_5", "")]
        }

        return annotation_data

    @log_function_call
    def get_patient_status(self):
        '''
        Returns the status for the current patient.
        '''

        is_reviewed = self.is_patient_reviewed()

        if len(self.patient_data['annotation_ids']) == 0:
            return PatientStatus.NO_ANNOTATIONS

        elif is_reviewed:
            if self.patient_data['event_date'] is None:
                return PatientStatus.REVIEWED_NO_EVENT
            return PatientStatus.REVIEWED_WITH_EVENT

        return PatientStatus.UNDER_REVIEW

    @log_function_call
    def is_patient_reviewed(self):
        '''
        Function that returns True if the current patient has been
        fully reviewed.
        '''

        # A patient is considered reviewed if there are
        # no unreviewed annotations left.
        # Note that this is not the same as having all the annotatings
        # being reviewed as annotations that are unreviewed but after the event date
        # can be marked None to indicate that they do not need to be annotated.
        return self.patient_data['review_statuses'].count(ReviewStatus.UNREVIEWED) == 0

    @log_function_call
    def perform_shift(self, action):
        '''
        Backend logic to allow an annotation to navigate back and forth
        between annotations without needing to review them.
        '''
        index = self.patient_data['current_index']
        last_index = len(self.patient_data['annotation_ids']) - 1

        if action == 'first_anno':
            self._shift_annotation_index(0)
        elif action == 'prev_10':
            new_index = max(0, index - 10)
            self._shift_annotation_index(new_index)
        elif action == 'prev_1':
            new_index = max(0, index - 1)
            self._shift_annotation_index(new_index)
        elif action == 'next_1':
            new_index = min(index + 1, last_index)
            self._shift_annotation_index(new_index)
        elif action == 'next_10':
            new_index = min(index + 10, last_index)
            self._shift_annotation_index(new_index)
        elif action == 'last_anno':
            self._shift_annotation_index(last_index)

    @log_function_call
    def _shift_annotation_index(self, new_index):
        self.patient_data['current_index'] = new_index

    @log_function_call
    def _adjudicate_annotation(self):
        '''
        Logic to mark the current annotation as reviewed and go to the
        next unreviewed annotation.
        '''
        index = self.patient_data['current_index']
        self.patient_data['review_statuses'][index] = ReviewStatus.REVIEWED
        review_statuses = self.patient_data['review_statuses']
        last_index = len(review_statuses) - 1

        # Find the next unreviewed index after the current one
        new_index = min(index + 1, last_index)
        if self.is_patient_reviewed():
            # If a patient is already reviewed
            # show the next annotation by default
            return new_index

        logger.debug("Fetching new index to show")
        # Check sentences from after the current annotation
        # for un-reviewed annotations
        for new_index in range(index + 1, len(review_statuses)):
            logger.debug(f"Checking index {new_index} / {len(review_statuses) - 1}")
            logger.debug(f"Index status : {review_statuses[new_index]}")
            if review_statuses[new_index] == ReviewStatus.UNREVIEWED:
                self.patient_data['current_index'] = new_index
                return

        # If no un-reviewed annotation is found, check the indices
        # before the current annotation
        for new_index in range(0, index):
            logger.debug(f"Checking index {new_index} / {len(review_statuses) - 1}")
            logger.debug(f"Index status : {review_statuses[new_index]}")
            if review_statuses[new_index] == ReviewStatus.UNREVIEWED:
                self.patient_data['current_index'] = new_index
                return

    @log_function_call
    def mark_event_date(self, event_date, event_annotation_id, annotations_after_event):
        '''
        Logic to enter an event date into the system and mark unreviewed annotations on or after
        that date as skipped.
        '''
        self.patient_data['event_date'] = self._format_date(event_date)
        self.patient_data['event_annotation_id'] = event_annotation_id
        annotations_after_event = set(annotations_after_event)

        for i, anno_id in enumerate(self.patient_data['annotation_ids']):
            review_status = self.patient_data['review_statuses'][i]
            # v2: annotation IDs are UUID strings; compare directly (no ObjectId).
            if (anno_id in annotations_after_event) and (review_status == ReviewStatus.UNREVIEWED):
                self.patient_data['review_statuses'][i] = ReviewStatus.SKIPPED

        self._adjudicate_annotation()

    @log_function_call
    def delete_event_date(self):
        '''
        Deletes the current event date and reverts the SKIPPED marks on any annotations
        for that patient.
        '''
        self.patient_data['event_date'] = None
        self.patient_data['event_annotation_id'] = None

        # Re-set all skipped events to UNREVIEWED
        self.reset_all_skipped()

        # Mark the annotation un-reviewed after the event_date is deleted
        index = self.patient_data['current_index']
        self.patient_data['review_statuses'][index] = ReviewStatus.UNREVIEWED

    @log_function_call
    def reset_all_skipped(self):
        '''
        Converts all annotations marked as SKIPPED to be marked as
        UNREVIEWED.
        '''
        for i, status in enumerate(self.patient_data['review_statuses']):
            if status == ReviewStatus.SKIPPED:
                self.patient_data['review_statuses'][i] = ReviewStatus.UNREVIEWED

    @log_function_call
    def _format_date(self, date_obj):
        '''
        Formats a datetime object into a date object.
        Will return None if no date exists.
        '''
        if isinstance(date_obj, datetime.date):
            return date_obj

        res = None
        if date_obj:
            res = date_obj.date()

        return res


class AnnotationFilterStrategy:
    @log_function_call
    def _filter_duplicates_by_patient(self, annotations):
        '''
        Finds and returns indices for duplicate sentences across any note
        for this patient. The first instance of a sentence is kept and all others
        are marked as duplicates.
        '''
        indices_with_duplicates = []
        seen_sentences = set()
        for i, annotation in enumerate(annotations):
            sentence = annotation['sentence'].lower().strip()
            if sentence in seen_sentences:
                indices_with_duplicates.append(i)
                continue

            seen_sentences.add(sentence)

        return indices_with_duplicates

    @log_function_call
    def _filter_duplicates_by_note(self, annotations):
        '''
        Finds and returns indices for duplicate sentences within a  paticular
        note. The first instance of a sentence is kept and all others
        are marked as duplicates.
        '''
        indices_with_duplicates = []
        prev_note_id = None
        seen_sentences = set()
        for i, annotation in enumerate(annotations):
            # If we are on a new note, then clear the hashset of sentences.
            # This is done so that we only check for the same sentence
            # in that note.
            if annotation['note_id'] != prev_note_id:
                seen_sentences.clear()

            prev_note_id = annotation['note_id']
            sentence = annotation['sentence'].lower().strip()
            if sentence in seen_sentences:
                indices_with_duplicates.append(i)
                continue

            seen_sentences.add(sentence)

        return indices_with_duplicates

    @log_function_call
    def _pop_and_mark_duplicates(self, annotations, indices_with_duplicates):
        '''
        Pops all annotations that have duplicates based on a list of
        indices dictating where the duplicates are found. The annotation
        IDs of these indices are also stored and returned in a seperate list.
        '''
        annotations_with_duplicates = []
        # Remove the indices in reverse order to avoid a later index changing
        # after a prior one is removed.
        indices_with_duplicates.sort(reverse=True)
        for index in indices_with_duplicates:
            annotations_with_duplicates.append(annotations[index]["_id"])
            annotations.pop(index)

        return annotations, annotations_with_duplicates

    @log_function_call
    def filter_annotations(self, annotations, hide_duplicates):
        """
        Filters annotations to keep only relevant occurrences as well
            as some additional data such as their review status.
        """

        logger.info("Finding duplicates...")
        if hide_duplicates:
            indices_with_duplicates = self._filter_duplicates_by_patient(annotations)
        else:
            indices_with_duplicates = self._filter_duplicates_by_note(annotations)

        logger.info("Removing duplicates...")
        annotations, annotations_with_duplicates = self._pop_and_mark_duplicates(
            annotations, indices_with_duplicates)

        filtered_results = {
            'annotation_ids': [str(annotation["_id"]) for annotation in annotations],
            'review_statuses': [ReviewStatus(int(x["reviewed"])) for x in annotations],
            'annotations': [dict(annotation) for annotation in annotations]
        }

        return filtered_results, annotations_with_duplicates


class SentenceHighlighter:
    @staticmethod
    def _collect_token_spans(annotations):
        """Flatten (start, end) token spans from a list of annotation dicts.

        In v2 each annotation carries its matched keyword tokens in a ``tokens``
        list (sourced from ``annotation_tokens``). This replaces v1's one
        annotation == one token model. Spans are sorted by start index so the
        overlap-avoidance loop below behaves exactly as v1's did on ordered
        per-token annotations.
        """
        spans = []
        for annotation in annotations:
            tokens = annotation.get("tokens")
            if tokens:
                for tok in tokens:
                    spans.append((tok["note_start_index"], tok["note_end_index"]))
            elif "note_start_index" in annotation:
                spans.append((annotation["note_start_index"], annotation["note_end_index"]))
        spans.sort(key=lambda s: s[0])
        return spans

    @log_function_call
    def get_highlighted_text(self, note, annotations_for_note):
        """
        Returns highlighted all of the text in a note.
        """
        highlighted_note = []
        prev_end_index = 0
        text = note["text"]

        spans = self._collect_token_spans(annotations_for_note)
        logger.debug(f"Getting highlighted text for spans: {spans}")

        for start_index, end_index in spans:
            # Make sure the annotations don't overlap
            if start_index < prev_end_index:
                continue

            # Escape note text so only the <b><mark> markup we add is live HTML
            # (prevents stored XSS from note content that v1 rendered raw).
            highlighted_note.append(html.escape(text[prev_end_index:start_index]))
            highlighted_note.append(f'<b><mark>{html.escape(text[start_index:end_index])}</mark></b>')
            prev_end_index = end_index

        highlighted_note.append(html.escape(text[prev_end_index:]))
        logger.debug(f"Final highlighted note : {highlighted_note}")
        return " ".join(highlighted_note).replace("\n", "<br>")

    @log_function_call
    def get_highlighted_sentence(self, current_annotation, note, annotations_for_sentence):
        """
        Returns highlighted text for a specific sentence in a note.
        """
        text = note["text"]

        sentence_start = text.lower().index(current_annotation['sentence'])
        sentence_end = sentence_start + len(current_annotation['sentence'])
        prev_end_index = sentence_start

        spans = self._collect_token_spans(annotations_for_sentence)

        highlighted_note = []
        for token_start_index, token_end_index in spans:
            # Make sure the annotations don't overlap unless it is the first index
            if (token_start_index < prev_end_index) and (token_start_index != 0):
                continue

            highlighted_note.append(html.escape(text[prev_end_index:token_start_index]))
            key_token = text[token_start_index:token_end_index]
            highlighted_note.append(f'<b><mark>{html.escape(key_token)}</mark></b>')
            prev_end_index = token_end_index

        highlighted_note.append(html.escape(text[prev_end_index:sentence_end]))
        sentence = "".join(highlighted_note).strip().replace("\n", "<br>")
        logger.debug(f'Showing sentence : {sentence}')
        return sentence
