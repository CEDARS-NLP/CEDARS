# CEDARS


## Pre-requisites

In order to run the app you will need a `.env` file with at least the flask `SECRET_KEY`, MONGODB details and the host IP.
Place the `.env` file under the `cedars/cedars` directory.

For example:
```
SECRET_KEY = \xcfR\xd9D\xaa\x06\x84S\x19\xc0\xdcA\t\xf7it
HOST=0.0.0.0 
DB_HOST=localhost  # change to DB_HOST=db if running docker container
DB_NAME=cedars
DB_PORT=27017
```

## Run locally

From the root directory:
```shell
$ cd app
$ python3 -m venv venv
$ source venv/bin/activate
(venv) $ pip install -r requirements.txt
(venv) $ python -m app.wsgi
```

If you are using Poetry
```shell
$ poetry install  # do not cd into cedars/app
$ cd app
$ poetry run python -m app.wsgi
```

and navigate to http://localhost:5000

## Run on Docker

```shell
$ cd cedars
$ docker-compose build
$ docker-compose up
```

and navigate to http://localhost:5001

## MINIO 

1. User uploads small amout of data using UI
    - Store into MINIO
    - Use stored data to fill mongo

2. User uploads large file on MINIO
    - Load all available files to mongo

## Open Source softwares

1. Docker: (License Details)[https://www.linuxfoundation.org/resources/publications/docker-containers-what-are-the-open-source-licensing-considerations]
2. MINIO: GNU AFFERO GENERAL PUBLIC LICENSE
3. MongoDB: Server Side Public License (SSPL) v1
