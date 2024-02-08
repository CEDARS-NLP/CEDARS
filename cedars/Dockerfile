FROM python:3.9

WORKDIR /cedars

COPY ./cedars/requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY ./cedars .
COPY ./cedars/.docker-env .env

CMD [ "python", "-m", "app.wsgi" ]
