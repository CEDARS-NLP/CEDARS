FROM python:3.9-slim

ENV APP_HOME /app

RUN apt-get -y update && apt-get -y install git gcc libldap2-dev libsasl2-dev libssl-dev libxml2-dev

# Copy the codebase into the images
RUN pip install gunicorn==20.1.0
COPY ./requirements.txt $APP_HOME/requirements.txt
RUN pip install -r $APP_HOME/requirements.txt

ARG ENV
ENV ENV=${ENV}

COPY app $APP_HOME/app
COPY ./gunicorn.conf.py $APP_HOME/gunicorn.conf.py

ENV TZ=America/New_York
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR $APP_HOME

# Finally, run gunicorn.
CMD ["gunicorn", "app.wsgi:app"]