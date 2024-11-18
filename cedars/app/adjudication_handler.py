from loguru import logger
from . import db


class AdjudicationHandler:
    '''
    This is a class meant to handle the logic of
    the adjudication workflow in CEDARS for a patient.
    '''

    def __init__(self, patient_id, raw_annotations, hide_duplicates):
        '''
        Class constructor.
        This function will accept the annotations for that patient and
        select which annotation to show first using the current index.

        Args :
            - patient_id (str)
            - annotations (list[dict]) : List of all annotations for that patient.
            - hide_duplicates (bool) : True if we do not show duplicate sentences.
        '''

        stored_event_date = db.get_event_date(patient_id)
        stored_annotation_id = db.get_event_annotation_id(patient_id)

        self.patient_id = patient_id
        annotation_ids, review_statuses = self._filter_annotations(raw_annotations, hide_duplicates)
        self.annotation_ids = annotation_ids
        self.review_statuses = review_statuses
        self.event_date = stored_event_date

        try:
            # Find the index of the first unreviewed index
            self.index = self.review_statuses.index(False)
        except ValueError as e:
            # A ValueError is thrown if the element being searched for
            # does not exist in the list.
            # In this case if there are no unreviewed indices, we default 
            # to the index of the event date if one exists and if not we select index 0.

            if stored_event_date and stored_annotation_id:
                self.index = annotation_ids.index(stored_annotation_id)
            else:
                self.index = 0

        if len(self.annotation_ids) > 0:
            # Only lock the patient for annotation if
            # there are annotations that exist
            db.set_patient_lock_status(patient_id, True)
    
    def get_annotation_details(self):
        annotation_id = self.annotation_ids[self.index]
        annotation = db.get_annotation(annotation_id)
        note = db.get_annotation_note(annotation_id)

        annotation_data = {
            "pos_start": self.index + 1,
            "total_pos": len(self.annotation_ids),
            "patient_id": self.patient_id,
            "note_date": self._format_date(annotation.get('text_date')),
            "event_date": self._format_date(db.get_event_date(self.patient_id)),
            "note_comment": db.get_patient_by_id(self.patient_id)["comments"],
            "highlighted_sentence" : self._get_highlighted_sentence(annotation, note),
            "note_id": annotation["note_id"],
            "full_note": self._highlighted_text(note),
            "tags": [note.get("text_tag_1", ""),
                    note.get("text_tag_2", ""),
                    note.get("text_tag_3", ""),
                    note.get("text_tag_4", ""),
                    note.get("text_tag_5", "")]
            }

        return annotation_data


    def get_patient_status(self):
        '''
        Returns the status for the current patient.

        Args :
            - None
        
        Returns :
            - status (str) : A string describing the current status for the patient.
        '''

        is_reviewed = self.is_patient_reviewed()

        if len(self.annotation_ids) == 0:
            return "No Annotations"

        elif is_reviewed:
            if self.event_date is None:
                return "Reviewed, No Event"
            return "Reviewed, Event Found"

        return "Review Required"

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
        return self.review_statuses.count(False) == 0

    def _highlighted_text(note):
        """
        Returns highlighted text for a note.
        """
        highlighted_note = []
        prev_end_index = 0
        text = note["text"]

        annotations = db.get_all_annotations_for_note(note["text_id"])
        logger.info(annotations)

        for annotation in annotations:
            start_index = annotation['note_start_index']
            end_index = annotation['note_end_index']
            # Make sure the annotations don't overlap
            if start_index < prev_end_index:
                continue

            highlighted_note.append(text[prev_end_index:start_index])
            highlighted_note.append(f'<b><mark>{text[start_index:end_index]}</mark></b>')
            prev_end_index = end_index

        highlighted_note.append(text[prev_end_index:])
        logger.info(highlighted_note)
        return " ".join(highlighted_note).replace("\n", "<br>")
    
    def _get_highlighted_sentence(current_annotation, note):
        """
        Returns highlighted text for a sentence in a note.
        """
        highlighted_note = []
        text = note["text"]

        sentence_start = text.lower().index(current_annotation['sentence'])
        sentence_end = sentence_start + len(current_annotation['sentence'])
        prev_end_index = sentence_start

        annotations = db.get_all_annotations_for_sentence(note["text_id"],
                                                        current_annotation["sentence_number"])

        highlighted_note = []
        for annotation in annotations:
            token_start_index = annotation['note_start_index']
            token_end_index = annotation['note_end_index']

            # Make sure the annotations don't overlap unless it is the first index
            if (token_start_index < prev_end_index) and (token_start_index != 0):
                continue

            highlighted_note.append(text[prev_end_index:token_start_index])
            key_token = text[token_start_index:token_end_index]
            highlighted_note.append(f'<b><mark>{key_token}</mark></b>')
            prev_end_index = token_end_index

        highlighted_note.append(text[prev_end_index:sentence_end])
        sentence = "".join(highlighted_note).strip().replace("\n", "<br>")
        logger.info(f'Showing sentence : {sentence}')
        return sentence

        
    def _format_date(self, date_obj):
        res = None
        if date_obj:
            res = date_obj.date()

        return res
    
    def _filter_annotations(self, annotations, hide_duplicates):
        """
        Filters annotations to keep only relevant occurrences as well
            as some additional data such as their review status.

        Args:
            annotations (list) : A list of all annotations for a paticular patient.
            hide_duplicates (bool) : True if we want to discard duplicate sentences
                from the annotations of this patient.
        Returns:
            result (dictionary) : A dictionary of all relevant annotations with some metadata.
        """
        if hide_duplicates:
            # If hide_duplicates sentences that are exact matches for sentences in
            # the same note are removed.

            # We first note the indices where duplicate sentences occur
            indices_to_remove = []
            seen_sentences = set()
            for i, annotation in enumerate(annotations):
                sentence = annotation['sentence'].lower().strip()
                if sentence in seen_sentences:
                    indices_to_remove.append(i)
                    continue

                seen_sentences.add(sentence)
        else:
            # If hide_duplicates is false then each sentence will still only be shown once.

            # We first note the indices where duplicate sentences occur
            indices_to_remove = []
            prev_note_id = None
            seen_sentence_indices = set()
            for i, annotation in enumerate(annotations):
                # If we are on a new note, then clear the hashset of sentences.
                # This is done so that we only check for the same sentence
                # in that note.
                if annotation['note_id'] != prev_note_id:
                    seen_sentence_indices.clear()

                prev_note_id = annotation['note_id']
                sentence_index = annotation['sentence_start']
                if sentence_index in seen_sentence_indices:
                    indices_to_remove.append(i)
                    continue

                seen_sentence_indices.add(sentence_index)

        # Remove the indices in reverse order to avoid a later index changing
        # after a prior one is removed.
        indices_to_remove.sort(reverse=True)
        for index in indices_to_remove:
            # Mark the annotation as reviewed before poping it
            # This ensures that an unseen annotation cannot be unreviewed
            db.mark_annotation_reviewed(annotations[index]["_id"])
            annotations.pop(index)

        annotation_ids = [str(annotation["_id"]) for annotation in annotations]
        reviewed_statuses = [x["reviewed"] for x in annotations]

        return annotation_ids, reviewed_statuses
    
    def __del__(self):
        '''
        Destructor, used to ensure that the patient is
        unlocked before the object is removed from memory.
        '''

        db.set_patient_lock_status(self.patient_id, False)
