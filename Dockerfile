FROM python:3.9

WORKDIR /app1

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY . .
COPY .docker-env .env

CMD [ "python", "-m", "cedars.app.wsgi" ]
