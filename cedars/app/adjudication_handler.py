from loguru import logger
from .cedars_enums import PatientStatus, ReviewStatus


class AdjudicationHandler:
    '''
    This is a class meant to handle the logic of
    the adjudication workflow in CEDARS for a patient.
    '''

    def __init__(self, patient_id):
        self.patient_id = patient_id
        self.patient_data = {
            'event_date' : None,
            'event_annotation_id' : None,
            'annotation_ids' : [],
            'review_statuses' : [],
            'current_index' : -1
        }

    def init_patient_data(self, raw_annotations, hide_duplicates,
                          stored_event_date = None, stored_annotation_id = None):
        '''
        This function will accept the annotations for that patient and
        select which annotation to show first using the current index.
        It will also initialize and return a JSON-like object that stores
        relevant data about that patient.

        Args :
            - patient_id (str) : ID for the patient currently being reviewed.
            - annotations (list[dict]) : List of all annotations for that patient.
            - hide_duplicates (bool) : True if we do not show duplicate sentences.
        '''

        filtered_results, annotations_with_duplicates = self._filter_annotations(raw_annotations,
                                                                                 hide_duplicates)

        annotation_ids = filtered_results['annotation_ids']
        review_statuses = filtered_results['review_statuses']
        index = 0
        try:
            # Find the index of the first unreviewed index
            index = review_statuses.index(ReviewStatus.UNREVIEWED)
        except ValueError as e:
            # A ValueError is thrown if the element being searched for
            # does not exist in the list.
            # In this case if there are no unreviewed indices, we default 
            # to the index of the event date if one exists and if not we select index 0.

            if stored_event_date and stored_annotation_id:
                index = annotation_ids.index(stored_annotation_id)

        self.patient_data = {
            'event_date' : stored_event_date,
            'event_annotation_id' : stored_annotation_id,
            'annotation_ids' : annotation_ids,
            'review_statuses' : review_statuses,
            'current_index' : index
        }

        return self.patient_data, annotations_with_duplicates

    def load_from_patient_data(self, patient_id, patient_data):
        '''
        Loads the handler object form data for an ongoing patient's adjudication.

        Args :
            - patient_id (str) : ID for the patient currently being reviewed.
            - patient_data (dict) : A JSON-like object of the relevant data for the current patient,
                                        follows the schema of the data created in the init_patient_data
                                        function of this class.
        '''
        self.patient_id = patient_id
        self.patient_data = patient_data
    
    def get_patient_data(self):
        return self.patient_data

    def get_curr_annotation_id(self):
        return self.patient_data['annotation_ids'][self.patient_data['current_index']]
    
    def get_annotation_details(self, annotation, note, comments,
                               annotations_for_note, annotations_for_sentence):
        annotation_data = {
            "pos_start": self.patient_data['current_index'] + 1,
            "total_pos": len(self.patient_data['annotation_ids']),
            "patient_id": self.patient_id,
            "note_date": self._format_date(annotation.get('text_date')),
            "event_date": self._format_date(self.patient_data['event_date']),
            "note_comment": comments,
            "highlighted_sentence" : self._get_highlighted_sentence(annotation, note, annotations_for_sentence),
            "note_id": annotation["note_id"],
            "full_note": self._highlighted_text(note, annotations_for_note),
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
            - status (PatientStatus) : An enum describing the current status for the patient.
        '''

        is_reviewed = self.is_patient_reviewed()

        if len(self.patient_data['annotation_ids']) == 0:
            return PatientStatus.NO_ANNOTATIONS

        elif is_reviewed:
            if self.patient_data['event_date'] is None:
                return PatientStatus.REVIEWED_NO_EVENT
            return PatientStatus.REVIEWED_WITH_EVENT

        return PatientStatus.UNDER_REVIEW

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
    
    def perform_shift(self, action):
        index = self.patient_data['current_index']
        last_index = len(self.patient_data['annotation_ids']) -1

        if action == 'first_anno':
            self._shift_annotation_index(0)
        elif action == 'prev_10':
            new_index = max(0, new_index - 10)
            self._shift_annotation_index(new_index)
        elif action == 'prev_1':
            new_index = max(0, new_index - 1)
            self._shift_annotation_index(new_index)
        elif action == 'next_1':
            new_index = min(index + 1, last_index)
            self._shift_annotation_index(new_index)
        elif action == 'next_10':
            new_index = min(index + 10, last_index)
            self._shift_annotation_index(new_index)
        elif action == 'last_anno':
            self._shift_annotation_index(last_index)

    def _shift_annotation_index(self, new_index):
        self.patient_data['current_index'] = new_index


    def _adjudicate_annotation(self):
        index = self.patient_data['current_index']
        last_index = len(self.patient_data['annotation_ids']) -1
        self.patient_data['review_statuses'][index] = ReviewStatus.REVIEWED
        review_statuses = self.patient_data['review_statuses']

        # Find the next unreviewed index after the current one
        new_index = min(index + 1, last_index)
        if self.is_patient_reviewed():
            # If a patient is already reviewed
            # show the next annotation by default
            return new_index

        while True:
            if review_statuses[new_index] == ReviewStatus.UNREVIEWED:
                self.patient_data['current_index'] = new_index
                break

            new_index += 1
            if new_index == last_index:
                new_index = 0


    def mark_event_date(self, event_date, event_annotation_id, annotations_after_event):
        self.patient_data['event_date'] = event_date
        self.patient_data['event_annotation_id'] = event_annotation_id
        annotations_after_event = set(annotations_after_event)

        for i, anno_id in self.patient_data['annotation_ids']:
            review_status = self.patient_data['review_statuses'][i]
            if (anno_id in annotations_after_event) and (review_status == ReviewStatus.UNREVIEWED):
                self.patient_data['review_statuses'][i] = ReviewStatus.SKIPPED

        self._adjudicate_annotation()

    def delete_event_date(self):
        self.patient_data['event_date'] = None
        self.patient_data['event_annotation_id'] = None

        # Re-set all skipped events to UNREVIEWED
        for i, status in enumerate(self.patient_data['review_statuses']):
            if status == ReviewStatus.SKIPPED:
                self.patient_data['review_statuses'][i] = ReviewStatus.UNREVIEWED

        self._adjudicate_annotation()


    def _highlighted_text(self, note, annotations_for_note):
        """
        Returns highlighted text for a note.
        """
        highlighted_note = []
        prev_end_index = 0
        text = note["text"]

        annotations = annotations_for_note
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
    
    def _get_highlighted_sentence(self, current_annotation, note, annotations_for_sentence):
        """
        Returns highlighted text for a sentence in a note.
        """
        highlighted_note = []
        text = note["text"]

        sentence_start = text.lower().index(current_annotation['sentence'])
        sentence_end = sentence_start + len(current_annotation['sentence'])
        prev_end_index = sentence_start

        annotations = annotations_for_sentence

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

        annotations_with_duplicates = []
        # Remove the indices in reverse order to avoid a later index changing
        # after a prior one is removed.
        indices_to_remove.sort(reverse=True)
        for index in indices_to_remove:
            # Mark the annotation as reviewed before poping it
            # This ensures that an unseen annotation cannot be unreviewed
            annotations_with_duplicates.append(annotations[index]["_id"])
            annotations.pop(index)

        filtered_results = {
            'annotation_ids' : [str(annotation["_id"]) for annotation in annotations],
            'review_statuses' : [ReviewStatus(int(x["reviewed"])) for x in annotations]
        }

        return filtered_results, annotations_with_duplicates