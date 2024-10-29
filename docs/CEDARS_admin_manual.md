# CEDARS Administrator Manual

> **CEDARS is provided as-is with no guarantee whatsoever and users agree to be held responsible for compliance with their local government/institutional regulations.** All CEDARS installations should be reviewed with institutional information security authorities.

## Software Installation
1. Minimum CPU requirements: **32GB Memory and 8 cores** [t2.2xlarge on AWS]

2. In order to run, you will need two `.env` files
    - The first .env file will be placed under the ROOT DIR
    - The second the `.env` file under the `CEDARS/cedars` directory.

    .sample.env files are available - please modify them with your settings and rename it to .env

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

#### Local Installation Requirement

!!! warning "WARNING"

    Local installation is not recommended unless you want to modify the underlying codebase. It is recommended to use the Docker deployment method.


For example:
```
SECRET_KEY = \xcfR\xd9D\xaa\x06\x84S\x19\xc0\xdcA\t\xf7it
HOST=0.0.0.0 
DB_HOST=localhost  # change to DB_HOST=db if running docker container
DB_NAME=cedars
DB_PORT=27017
MINIO_HOST=localhost
MINIO_PORT=9000
MINIO_ACCESS_KEY=ROOTUSER
MINIO_SECRET_KEY=CHANGEME123
ENV=dev
PINES_API_URL=<>  # if using PINES
RQ_DASHBOARD_URL=/rq # URL for dashboard to interact with redis queues
```

CEDARS is a flask web application and depends on the following software:

1. Python 3.9 - 3.11

    You can install Python from the [official website](https://www.python.org/downloads/).
    
    If you have multiple python versions installed, you can manage the environments using [pyenv](https://github.com/pyenv/pyenv?tab=readme-ov-file#installation)

    !!! note "Windows Setup Specification"

        On windows machines for development setups (not using docker) only python 3.9 is supported.
        If using windows, then installing python via [WSL](https://learn.microsoft.com/en-us/windows/wsl/install) is recommended.

2. Poetry

    To install poetry, run pipx install poetry or follow the [instructions](https://python-poetry.org/docs/).

3. Mongo 7.0 or later

    For using Mongo, you have multiple options:
    
     - You might use your own enterprise Mongo instance
     - You can use a cloud-based service like [MongoDB Atlas](https://www.mongodb.com/cloud/atlas)
     - You can run a local instance of Mongo using Docker
     - You can run a local instance of Mongo using the [official installation](https://docs.mongodb.com/manual/installation/)

4. Minio

    Similar to Mongo, you have multiple options to install MINIO

    - You might use your own enterprise MINIO instance
    - You can use a cloud-based service like [MINIO](https://min.io/)
    - You can run a local instance of MINIO using [Docker](https://min.io/docs/minio/container/index.html)
    - You can run a local instance of MINIO using the [official installation](https://docs.min.io/docs/minio-quickstart-guide.html)

 5. Redis

!!! note "Mac Fork Issue"
    On MacOS, if you see a issue with fork processes you will need to `export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`
    for running the `rq` workers

    To manage long running processes such as upload, download, spacy labelling, PINES jobs etc.

    - You can install [redis](https://redis.io/docs/install/install-redis/) locally on your computer 
    - Run redis docker [image](https://hub.docker.com/_/redis)

#### Docker Requirement

!!! note "TIP"

    This is the easiest way to run CEDARS and encapsulates all dependencies above.

!!! note "TIP"

    If using docker on windows, it is recommended to install docker via [WSL](https://learn.microsoft.com/en-us/windows/wsl/install).

Install [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/).

!!! note "TIP"

    Please install docker compose v2 as the spec using `deploy` which is not compatible with v1.


### System Architecture

![CEDARS Operational Schema](pics/GitHub%20Docker%20Schema%20C.png)

The CEDARS application runs on a web server and generates an online graphical user interface (GUI) using Flask. All data are stored in a MongoDB instance hosted separately. However, most CEDARS instances are dockerized in order to streamline the project setup process and ensure adequate compatibility of dependencies.

Once the instance is running, electronic health record (EHR) documents are imported and processed through the CEDARS natural language processing (NLP) pipeline. Additional document annotation with a PINES model is optional. A CEDARS annotation project can be set up entirely from the GUI, using the administrator panel. The existing annotations can be downloaded at any point from this interface.

Annotators can connect to the CEDARS app by accessing a web URL provided by the administrator. CEDARS performs the operations to pull selected documents from the database, process them and present them to the annotators. Data entered by users is processed by CEDARS and saved to the database. Multiple users can work on one CEDARS project at the same time. The application will automatically select individual patient records for each user. Record locking is implemented to prevent collisions and inconsistencies.

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

#### Standalone CEDARS Python Package Installation

Make sure all the local requirements [above](#detailed-requirements) are met. Then, you can install the package using Poetry:

```shell
$ cd cedars
$ poetry install  # do not cd into cedars/app
$ cd app
$ poetry run python -m app.wsgi
```

#### Setting Up VS Code Debugger for Flask Application (OPTIONAL)

If you are a developer and wish to use a code debugger while working with CEDARS, then you can follow the steps below to setup a VS Code debugger.

    1. Create a python virtual environment (preferably using [pyenv](https://github.com/pyenv/pyenv?tab=readme-ov-file#installation)).

    2. Create a profile in launch.json (VS Code) as defined in [this](https://code.visualstudio.com/docs/python/tutorial-flask#_run-the-app-in-the-debugger) article.

    3. Set FLASK_APP variable to “app/wsgi.py” in the new launch.json you created.

    4. Follow these [instructions](https://code.visualstudio.com/docs/python/environments) to load the python virtual environment you created in step 1. into VS Code.

    5. Select you new debugger profile in the debugger tab and run it.


#### Docker Deployment

The most straightforward way to complete a CEDARS project is via docker containers. This approach allows fast and reliable installation on prems or in the cloud with on-demand access to compute resources, including graphics processing unit \(GPU\). Inclusion of required dependencies in the containers mitigate the problems associated with version incompatibilities inherent to *ad hoc* builds. Docker images can be easily installed in air-gapped environment, which is sometimes an institutional requirement. A CEDARS docker deployment will include:

- CEDARS Flask web server
- MongoDB database service
- MINIO object storage service
- PINES NLP annotation service (optional)

Each component runs as a service encapsulated in a docker container. Those three elements a coordinated within a deployment.The PINES service requires a GPU for model training. This is optional for inference \(i.e. annotating documents\).

After cloning as described above, create required `.env` files as mentioned [here](#software-installation)

After creating `.env` files, run the following commands:
```shell
$ cd CEDARS
# if you do are not using GPU and want all the services to be hosted on docker
$ docker compose --profile cpu --profile selfhosted up --build -d
# if you are using a GPU
$ docker compose --profile gpu --profile selfhosted up --build -d
# if you want to use a native service such as AWS Document DB
$ docker compose --profile gpu  up --build -d  # gpu
$ docker compose --profile cpu  up --build -d  # cpu
```

Once all services are started - the app will be available here

```
http://<hostaddress>:80
```

#### AWS/Server Deployment

1. Install docker: [Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
2. Make sure you have docker compose v2
    if you are running docker as sudo - please follow this [stackoverflow link](https://stackoverflow.com/questions/48957195/how-to-fix-docker-got-permission-denied-issue) to run as a non-sudo  

3. Install compose v2  using this [link](https://www.digitalocean.com/community/tutorials/how-to-install-and-use-docker-compose-on-ubuntu-22-04)

For example to use AWS DocumentDB with tls you can create .env (under CEDARS/cedars) file like this
```bash
DB_HOST=<your-cluster-ip>.docdb.amazonaws.com
DB_NAME=cedars
DB_PORT=27017
DB_USER=<docdbuser>
DB_PWD=<docDBpassword>
DB_PARAMS="tls=true&tlsCAFile=global-bundle.pem&replicaSet=rs0&readPreference=secondaryPreferred&retryWrites=false"
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

### [Electronic Health Record Corpus Upload](upload_data.md)

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

#### Queue Operations
- `docker ps` - to see list of all docker contains
- `docker exec -it <any-worker-docker-container-id> bash`
- `export REDIS_HOST=redis` - the service name in nginx/nginx.conf
- `rq info` (status)
- `rq requeue --queue cedars -a` (requeue all failed jobs)

#### ::: cedars.app.db.add_task
---

### Dataset Download

Once there are no patient records left to review, event data can be downloaded from the database via the GUI Detailed information is provided including clinical event dates, individual annotator contribution and review times. If a PINES model was used but no manual annotations were applied, estimated event dates can be used in a time-to-event analysis instead of manual entry.

#### ::: cedars.app.ops.download_file
---

### Audit

CEDARS is by definition semi-automated, and depending on the specific use case and search query some events might be missed. This problem should be quantified by means of a systematic, old-fashion review of randomly selected patients. Typically, at least 200 patients would be selected and their corpora reviewed manually for events. Alternatively, a different method (e.g. billing codes) could be used. This audit dataset should be overlapped with the CEDARS event table to estimate sensitivity of the search query in the cohort at large. If this parameter falls below the previously established minimum acceptable value, the search query scope should be broadened, followed by a database reset, uploading of previously identified events and a new human annotation pass, followed by a repeat audit.

### Project Termination

Once all events have been tallied and the audit results are satisfactory, if desired the CEDARS project database can be deleted from the MongoDB database. This is an irreversible operation.

In future, there will be way to archive CEDARS projects, but this feature is not yet available.

### Issues

- Unable to install `thinc` - downgrade python version < 3.12

#### ::: cedars.app.db.terminate_project
---
