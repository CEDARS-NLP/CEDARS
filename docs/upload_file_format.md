# Upload File Format

> To upload patient data to CEDARS an admin can upload a file on the Upload File page. Below are the details describing the file requirements and upload process.


## 1. File Upload Process

To make use of this software, we will first need to upload some medical records to the database. To do this, you can click on the dropdown menu on the top right of the page. From here you can select the "Upload Data" option. This will redirect you to a page where you can select a file with the data from your computer by clicking the "Choose File" button. 

## 2. File Type

CEDARS can accept tabular data stored in one of the the following file formats :

- .csv ([Comma Seperated Value](https://en.wikipedia.org/wiki/Comma-separated_values))
- .csv.gz ([GZIP Compressed CSV](https://www.gnu.org/software/gzip/))
- .xlsx ([Excel](https://en.wikipedia.org/wiki/Microsoft_Excel))
- .json ([Json](https://www.json.org/json-en.html))
- .parquet ([Parquet](https://coralogix.com/blog/parquet-file-format/))
- .pickle / .pkl ([Pickle](https://docs.python.org/3/library/pickle.html))

## 3. Mandatory Columns

These are columns that the uploaded file is required for a CEDARS project. Below is the format in which the columns are listed
    - column_name (data type) : Description of this column

Columns :

1. patient_id (string / int) : A unique identifier for the patient associated with a note. If you upload this as an integer, it will be converted to a string in the backend.

2. text_id (string) : A unique identifier for the note taken about this patient.

3. text (string) : The note taken about this patient.

4. text_date (string) : The date this note was taken in the format (YYYY-MM-DD).

Note that the values in the text_id column must be unique, but all other columns may contain duplicate values.

## 4. Optional Columns

These are optional columns that are not nessesary for CEDARS, but can be included to provide annotators with more context. Below is the format in which the columns are listed
    - column_name (data type) : Description of this column

Columns :

1. text_sequence (int) : A number stating the order in which note were taken. Example : 1 would indicate that the note for this row is the first note taken for this patient.

2. doc_id (string) : A unique identifier for document which containts this note.

3. text_tag_1 (string) : The first text tag for this note, will be shown on the annotations page while the note is being reviewed.

4. text_tag_2 (string) : The second text tag for this note, will be shown on the annotations page while the note is being reviewed.

5. text_tag_3 (string) : The third text tag for this note, will be shown on the annotations page while the note is being reviewed.

6. text_tag_4 (string) : The fourth text tag for this note, will be shown on the annotations page while the note is being reviewed.

## 5. Example Table

Below is a sample table to help illustrate what the file format should look like.

|   patient_id  |   text_id           |   text                                                                                                                                                                                                                                                                    |   text_date   |   doc_id         |   text_sequence  |   text_tag_1         |   text_tag_2  |   text_tag_3    |   text_tag_4      |
|---------------|---------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------|------------------|------------------|----------------------|---------------|-----------------|-------------------|
|   1111111111  |   UNIQUE0000000001  |   Mr First is a 60 YO M with a history of metastatic colon CA, diagnosed in 1-2008, initially with stage III disease and s/p hemicolectomy followed by adjuvant chemo, with recurrence in the liver 6 months ago, evaluated today for management of pulmonary embolism.   |   2010-01-01  |   DOC0000000001  |   1              |   consultation_note  |   HPI         |   Dr Blood      |   Hugo First      |
|   1111111111  |   UNIQUE0000000002  |   hypercholesterlemia   asthma   HTN                                                                                                                                                                                                                                      |   2010-01-01  |   DOC0000000001  |   2              |   consultation_note  |   PMHX        |   Dr Blood      |   Hugo First      |
|   2222222222  |   UNIQUE0000000019  |   Pt denies any fevers, NS or recent loss of weight. Review of other systems was otherwise negative.                                                                                                                                                                      |   2016-06-06  |   DOC0000000004  |   1              |   pre_op             |   ROS         |   Dr Internist  |   Cherry Blossom  |