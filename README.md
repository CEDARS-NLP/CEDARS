# Flask App Template

Simple Flask application template that uses
1. Flask-Login for user authentication.
2. Flask-Caching + Redis LRU as the caching layer.
3. Jinja templates + Bootstrap for the UI.
4. Flask application factories to manage multiple configurations (dev, prod, etc.).
5. Blueprints to encapsulate pieces of functionality in different components.
6. Docker to simplify the deployment.

## Pre-requisites

In order to run the app you will need a `.env` file with at least the flask `SECRET_KEY`
and place it under the `app/app/` directory.

For example:
```
SECRET_KEY = \xcfR\xd9D\xaa\x06\x84S\x19\xc0\xdcA\t\xf7it
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
$ poetry install
$ cd app
$ poetry run python -m app.wsgi
```

and navigate to http://localhost:5000

## Run on Docker

```shell
$ docker-compose build
$ docker-compose up
```

and navigate to http://localhost:8051
