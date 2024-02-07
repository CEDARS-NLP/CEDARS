# CEDARS Administrator Manual

## Software Installation

### Detailed Requirements

**CEDARS is provided as-is with no guarantee whatsoever and users agree to be held responsible for compliance with their local government/institutional regulations.** All CEDARS installations should be reviewed with institutional information security authorities.

Rohan to populate

### System Architecture

![CEDARS Operational Schema](pics/GitHub%20Docker%20Schema%20C.png)

The CEDARS application runs on a web server and generates an online graphical user interface (GUI) using Flask. All data are stored in a MongoDB instance hosted separately. However, most CEDARS instances are dockerized in order to streamline the project setup process and ensure adequate compatibility of dependencies.

Once the instance is running, electronic health record (EHR) documents are imported and processed through the CEDARS natural language processing (NLP) pipeline. Additional document annotation with a PINES model is optional. A CEDARS annotation project can be set up entirely from the GUI, using the administrator panel. The existing annotations can be downloaded at any point from this interface.

Annotators can connect to the CEDARS app by accessing a web URL provided by the administrator. CEDARS performs the operations to pull selected documents from the database, process them and present them to the annotators. Data entered by users is processed by CEDARS and saved to the database. Multiple users can work on one CEDARS project at the same time. The application will automatically select individual patient records for each user. Record locking is implemented to prevent collisions and inconsistencies.

### Installing CEDARS

#### Standalone CEDARS Python Package Installation

Rohan to populate.

#### Docker Deployment

The most straightforward way to complete a CEDARS project is via docker virtual containers. This approach allows fast and reliable installation on prems or in the cloud with on-demand access to compute resources, including graphics processing unit \(GPU\). Inclusion of required dependencies in the containers mitigate the problems associated with version incompatibilities inherent to *ad hoc* builds. Docker images can be easily installed in air-gapped environment, which is sometimes an institutional requirement. A CEDARS docker deployment will include:

- CEDARS Flask web server
- MongoDB database service
- PINES NLP annotation service (optional)

Each component runs as a service encapsulated in a docker container. Those three elements a coordinated within a deployment.The PINES service requires a GPU for model training. This is optional for inference \(i.e. annotating documents\).

Rohan to explain dockerization and include code/shell commands.

## Project Execution

### Overview

Determining clinical event dates with CEDARS is a simple, sequential process:

![CEDARS Project Execution](pics/GitHub%20Schema%207%20B.png)

After generation of a CEDARS instance, EHR documents are uploaded, a keyword search query is generated and automatic NLP annotations are launched, following which manual data entry can begin. If known event dates exist, those can be imported before annotator work starts. Once all patient records have been annotated manually for clinical events, the dataset can be downloaded and used immediately in time-to-event analyses. Alternatively, estimated event dates can be obtained without the human review step if a PINES model of satisfactory accuracy was used to classify documents.

The package authors suggest that a random sample of patients be selected for manual review via independent means. If performance metrics are unsatisfactory, the search query can be modified and CEDARS annotations updated through the same process.

### Electronic Health Record Corpus Upload



### Keyword Search Query Design

The CEDARS search query incorporates the following wildcards:

"?": for one character, for example "r?d" would match "red" or "rod" but not "reed"

"\*": for zero to any number of characters, for example "r*" would match "red", "rod", "reed", "rd", etc.

CEDARS also applies the following Boolean operators:

"AND": both conditions present
"OR": either present present
"!": negation, for example "!red" would only match sentences without the word "red"

Lastly, the "(" and ")" operators can be used to further develop logic within a query.

### Natural Language Processing Annotations

The process of automatically parsing clinical documents before presentation to an annotator is performed in three steps:

1. NLP annotation via the SpaCy traditional NLP pipeline: in this step, sentence boundaries, lemmas and negation status are characterized.
2. Keyword query matching: only documents with at least one sentence matching the search query are retained. Sentences from documents without a matched will be marked as reviewed. Patients with no remaining sentences/documents will be considered not to have sustained the event of interest and will not be reviewed manually.
3. Transformer model labelling (optional): individual documents are labelled for their probability (*p*) of occurring at or after a clinical event. This last step is facultative and offers the possibility of further narrowing the scope of material to be reviewed manually, further improving efficiency. Documents with a *p* inferior to the predetermined threshold and their associated sentences are marked as reviewed. Patients with no remaining sentences/documents will be considered not to have sustained the event of interest and will not be reviewed manually.

### Event Pre-Loading

Sometimes a cohort of patients will already have been assessed with other methods and CEDARS is used as a redundant method to pick up any previously missed events. In this use case, a list of known clinical events with their dates will exist. This information can be loaded on CEDARS as a "starting point", so as to avoid re-discovering already documented events.

### Manual Assessment for Clinical Events

The process by which human abstractors annotate patient records for events is described in the [End User Manual](CEDARS_end_user_manual.md). This step can be skipped altogether if a PINES model was used to classify documents. An estimated event date will be generated by PINES. Transformer models often exhibit sufficient performance to be used without individual record review, but an audit step as detailed below is strongly advised to confirm satisfactory sensitivity, specifcity and event time estimation.

### Dataset Download

Once there are no patient records left to review, event data can be downloaded from the database via the GUI Detailed information is provided including clinical event dates, individual annotator contribution and review times. If a PINES model was used but no manual annotations were applied, estimated event dates can be used in a time-to-event analysis instead of manual entry.

### Audit

CEDARS is by definition semi-automated, and depending on the specific use case and search query some events might be missed. This problem should be quantified by means of a systematic, old-fashion review of randomly selected patients. Typically, at least 200 patients would be selected and their corpora reviewed manually for events. Alternatively, a different method (e.g. billing codes) could be used. This audit dataset should be overlapped with the CEDARS event table to estimate sensitivity of the search query in the cohort at large. If this parameter falls below the previously established minimum acceptable value, the search query scope should be broadened, followed by a database reset, uploading of previously identified events and a new human annotation pass, followed by a repeat audit.

### Project Termination

Once all events have been tallied and the audit results are satisfactory, if desired the CEDARS project database can be deleted from the MongoDB database. This is an irreversible operation:

A CEDARS project can be saved by downloading the docker installation. Rohan to expand.

## Function Reference

Rohan to populate

