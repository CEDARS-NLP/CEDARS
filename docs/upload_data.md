# Uploading EMR Records

To make use of this software, we will first need to upload some medical records to the database. To do this, you can click on the dropdown menu on the top right of the page. From here you can select the "Upload Data" option. This will redirect you to a page where you can select a file with the data from your computer by clicking the "Choose File" button. The allowed file formats for this data are:

1. CSV (.csv)
2. Excel (.xlsx)
3. Json (.json)
4. Parquet (.parquet)
5. Pickle (.pickle or .pkl)
6. XML (.xml)

The file with the data should contain tabular data with at least the following columns:
1. patient_id (A unique ID for the patient)
2. text (The medical note written by a doctor)
3. text_date (The date at which this note was recorded)