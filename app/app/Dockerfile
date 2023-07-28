FROM python:3.9

WORKDIR /app1

RUN apt-get -y update && apt-get -y install git gcc libldap2-dev libsasl2-dev libssl-dev libxml2-dev

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY . .
COPY .docker-env .env

CMD ["python", "wsgi.py"]
