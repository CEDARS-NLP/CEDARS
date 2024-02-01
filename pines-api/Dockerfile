FROM python:3.9

WORKDIR /app

COPY requirements.txt .

RUN pip install -r requirements.txt

COPY . .

# RUN poetry install 

EXPOSE 8036

CMD ["uvicorn", "pines:app", "--host", "0.0.0.0", "--port", "8036"]