# CEDARS Quickstart Guide

> **CEDARS is provided as-is with no guarantee whatsoever and users agree to be held responsible for compliance with their local government/institutional regulations.** All CEDARS installations should be reviewed with institutional information security authorities.

## Software Installation
In order to run, you will need two `.env` files
    - The first .env file will be placed under the ROOT DIR
    - The second the `.env` file under the `CEDARS/cedars` directory.
    - There are `.env.sample` files available with best default configurations - just **RENAME** them .env to use defaults.

    ```bash
    CEDARS/
    │
    ├── .env
    ├── docker-compose.yml
    ├── cedars/
    │   ├── .env
    │   ├── Dockerfile
    │   └── ...
    ```

    - `CEDARS/.env`: This file contains environment variables used by Docker Compose.
    - `CEDARS/cedars/.env`: This file contains environment variables specific to cedars application.
    - `docker-compose.yml`: The Docker Compose configuration file.
    - `cedars/Dockerfile`: The Dockerfile for building cedars app.

### Detailed Requirements


#### Docker Requirement

!!! note "TIP"

    If using docker on windows, it is recommended to install docker via [WSL](https://learn.microsoft.com/en-us/windows/wsl/install).

Install [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/).

!!! note "TIP"

    Please install docker compose v2 as the spec using `deploy` which is not compatible with v1.



### Installing CEDARS

To install CEDARS, please start by cloning the repository and installing the required dependencies. You can then run the app locally or using Docker.

- Clone the Repo: `git clone git@github.com:CEDARS-NLP/CEDARS.git` 
- Change directory: `cd CEDARS`
- Initialize submodules: `git submodule init`
- Download submodules: `git submodule update`

!!! note "git submodule update time out"
    If you are accessing git over http - take following steps
    - update `.gitmodules` in the root dir with
      `url = https://github.com/CEDARS-NLP/PINES.git`
    - Run: `git submodule sync`
    - Run: `git submodule update`


#### Docker Deployment

The most straightforward way to complete a CEDARS project is via docker containers. This approach allows fast and reliable installation on any machine. Inclusion of required dependencies in the containers mitigate the problems associated with version incompatibilities inherent to *ad hoc* builds. Docker images can be easily installed in air-gapped environment, which is sometimes an institutional requirement. A CEDARS docker deployment will include:

- CEDARS Flask web server
- MongoDB database service
- MINIO object storage service
- PINES NLP annotation service (optional)

Each component runs as a service encapsulated in a docker container. Those three elements a coordinated within a deployment.

After cloning as described above, create required `.env` files by renaming the two `.env.sample` files as mentioned [here](#software-installation)

After creating `.env` files, run the following commands:
```shell
$ cd CEDARS
# This command will startup all of the services inside docker
$ docker compose --profile cpu --profile selfhosted up --build -d
```

Once all services are started - the app will be available here

```
http://<hostaddress>:80
```

## Project Execution

### Overview

Determining clinical event dates with CEDARS is a simple, sequential process:

![CEDARS Project Execution](pics/GitHub%20Schema%207%20B.png)

After generation of a CEDARS instance, EHR documents are uploaded, a keyword search query is generated and automatic NLP annotations are launched, following which manual data entry can begin. If known event dates exist, those can be imported before annotator work starts. Once all patient records have been annotated manually for clinical events, the dataset can be downloaded and used immediately in time-to-event analyses. Alternatively, estimated event dates can be obtained without the human review step if a PINES model of satisfactory accuracy was used to classify documents.

The package authors suggest that a random sample of patients be selected for manual review via independent means. If performance metrics are unsatisfactory, the search query can be modified and CEDARS annotations updated through the same process.

### Setting Up a CEDARS Project and Users

The first step after running CEDARS is to set up a new project. This is done by the administrator through the GUI. The following steps are required:

1\. At first login, the administrator will be prompted to register a new user. This user will be the administrator of the project.

2\. The administrator will then fill in Project Details such as Project Name.

3\. The administrator can also create new users who will only work on the Annotation Interface.

4\. Administrator will provide the credentials to the annotators.

### [Electronic Health Record Corpus Upload](upload_file_format.md)

### Keyword Search Query Design

The CEDARS search query incorporates the following wildcards:

"?": for one character, for example "r?d" would match "red" or "rod" but not "reed"

"\*": for zero to any number of characters, for example "r*" would match "red", "rod", "reed", "rd", etc.

CEDARS also applies the following Boolean operators:

"AND": both conditions present
"OR": either present present
"!": negation, for example "!red" would only match sentences without the word "red"

Lastly, the "(" and ")" operators can be used to further develop logic within a query.

#### Search Query Implementation
#### ::: cedars.app.nlpprocessor.query_to_patterns
---
### Natural Language Processing Annotations

The process of automatically parsing clinical documents before presentation to an annotator is performed in three steps:

1\. **NLP annotation via the SpaCy traditional NLP pipeline**: In this step, sentence boundaries, lemmas and negation status are characterized.

#### ::: cedars.app.nlpprocessor.is_negated
---

2\. **Keyword query matching**: only documents with at least one sentence matching the search query are retained. Sentences from documents without a matched will be marked as reviewed. Patients with no remaining sentences/documents will be considered not to have sustained the event of interest and will not be reviewed manually.

#### ::: cedars.app.nlpprocessor.NlpProcessor.process_notes
---
3\. **Transformer model labelling** (optional): individual documents are labelled for their probability (*p*) of occurring at or after a clinical event. This last step is facultative and offers the possibility of further narrowing the scope of material to be reviewed manually, further improving efficiency. Documents with a *p* inferior to the predetermined threshold and their associated sentences are marked as reviewed. Patients with no remaining sentences/documents will be considered not to have sustained the event of interest and will not be reviewed manually.

#### ::: cedars.app.db.get_prediction
---
#### ::: cedars.app.db.predict_and_save
---

### Event Pre-Loading

Sometimes a cohort of patients will already have been assessed with other methods and CEDARS is used as a redundant method to pick up any previously missed events. In this use case, a list of known clinical events with their dates will exist. This information can be loaded on CEDARS as a "starting point", so as to avoid re-discovering already documented events.

### Manual Assessment for Clinical Events

The process by which human abstractors annotate patient records for events is described in the [End User Manual](CEDARS_annotator_manual.md). This step can be skipped altogether if a PINES model was used to classify documents. An estimated event date will be generated by PINES. Transformer models often exhibit sufficient performance to be used without individual record review, but an audit step as detailed below is strongly advised to confirm satisfactory sensitivity, specifcity and event time estimation.

### Error Handling and Queues

All the jobs are processed at a patient level. For each patient, a job is submitted to a [rq](https://python-rq.org/docs/). If a job fails, it is retried 3 times before moving it a failed queue.

### Dataset Download

Once there are no patient records left to review, event data can be downloaded from the database via the GUI Detailed information is provided including clinical event dates, individual annotator contribution and review times. If a PINES model was used but no manual annotations were applied, estimated event dates can be used in a time-to-event analysis instead of manual entry.

#### ::: cedars.app.ops.download_file
---

### Audit

CEDARS is by definition semi-automated, and depending on the specific use case and search query some events might be missed. This problem should be quantified by means of a systematic, old-fashion review of randomly selected patients. Typically, at least 200 patients would be selected and their corpora reviewed manually for events. Alternatively, a different method (e.g. billing codes) could be used. This audit dataset should be overlapped with the CEDARS event table to estimate sensitivity of the search query in the cohort at large. If this parameter falls below the previously established minimum acceptable value, the search query scope should be broadened, followed by a database reset, uploading of previously identified events and a new human annotation pass, followed by a repeat audit.

### Project Termination

Once all events have been tallied and the audit results are satisfactory, if desired the CEDARS project database can be deleted from the MongoDB database. This is an irreversible operation.

In future, there will be way to archive CEDARS projects, but this feature is not yet available.