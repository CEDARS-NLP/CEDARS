# Downloading Results

Once you have reviewed the generated annotations and marked event dates, you can navigate to the dropdown on the top right. 

Then you can create a new download task (regular or full). A spinning animation will play while the data is being prepared. After it is done, the file will be added to the list of "Available Files" with a "Download" button. Clicking this download button will return a file with tabular data in [.csv](https://en.wikipedia.org/wiki/Comma-separated_values) format. 


The table for the regular download will have the following columns:

    1. patient_id (The ID of the patient for which that note was written)
    2. total_notes (The total number of notes for this patient)
    3. reviewed_notes (The number of notes that were reviewed for this patient)
    4. total_sentences (The total number of sentences found for this patient)
    5. reviewed_notes (The number of sentences that were reviewed for this patient)
    6. event_date (The date at which the event took place)
    7. event_information (The sentence where the event was found along with the note ID for the note that sentence belonged to)
    8. first_note_date (The earliest note date for that patient)
    9. last_note_date (The most recent note date for that patient)
    10. comments (Any comments for that patient written by annotators)
    11. reviewer (The investigator that reviewed this patient. Will be "PINES" if the patient has been adjudicated by a PINES model or "CEDARS" if that patient has no annotations.)
    12. max_score_note_id (The note ID in which PINES found the highest probability of an event. Will be empty if no PINES model was used.)
    13. max_score_note_id (The note date for which PINES found the highest probability of an event. Will be empty if no PINES model was used.)
    14. max_score (The highest score PINES assigned to any note for this patient. Will be empty if no PINES model was used.)
    15. predicted_notes (The note IDs with the predicted scores for this patient. Will be empty if no PINES model was used.)

If a full download task is created an additional column will be added to the output file :

    - sentences (A list of the annotation IDs with their corresponding sentences for that patient.)