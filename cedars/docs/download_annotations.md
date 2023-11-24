# Downloading Results

Once you have reviewed the generated annotations and marked event dates, you can navigate to the dropdown on the top right. Here you can click the "Download Annotations" option. This will return a file with tabular data in [.csv](https://en.wikipedia.org/wiki/Comma-separated_values) format. The table will have the following columns:

1. sentence (the sentence in which the lemma was found)
2. token (the word found in that sentence)
3. lemma (the lemma of the word found)
4. isNegated (will be TRUE if there is a negation on the word, otherwise it will be FALSE)
5. start_index (the character index at which the word begins in the sentence)
6. end_index (the character index at which the word ends in the sentence)
7. patient_id (the ID of the patient for which that note was written)
8. event_date (the date at which the event took place)
9. comments (a list of all comments made by the researcher while working on the project)
10. reviewed (will be TRUE if that record had been adjudicated by a researcher)
