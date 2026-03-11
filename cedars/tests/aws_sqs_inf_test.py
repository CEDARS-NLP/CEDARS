import os
import json
import time
import uuid
import boto3
from dotenv import dotenv_values

config = dotenv_values(".env")

sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION"))

INFERENCE_QUEUE_URL = os.getenv("INFERENCE_QUEUE_URL")
RESPONSE_QUEUE_URL = os.getenv("RESPONSE_QUEUE_URL")


def send_warmup():

    request_id = str(uuid.uuid4())

    message = {
        "is_warmup" : True,
        "request_id": request_id,
        "notes": [],
        "response_queue" : None
    }

    sqs.send_message(
        QueueUrl=INFERENCE_QUEUE_URL,
        MessageBody=json.dumps(message)
    )

    return request_id

def send_job(notes):

    request_id = str(uuid.uuid4())

    message = {
        "is_warmup" : False,
        "request_id": request_id,
        "notes": notes,
        "response_queue" : RESPONSE_QUEUE_URL
    }

    sqs.send_message(
        QueueUrl=INFERENCE_QUEUE_URL,
        MessageBody=json.dumps(message)
    )

    return request_id


def wait_for_result(request_id, timeout=3000):

    start_time = time.time()

    while time.time() - start_time < timeout:

        response = sqs.receive_message(
            QueueUrl=RESPONSE_QUEUE_URL,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=20,  # long polling
        )

        messages = response.get("Messages", [])

        for msg in messages:
            body = json.loads(msg["Body"])

            if body.get("request_id") == request_id:

                # Delete message after processing
                sqs.delete_message(
                    QueueUrl=RESPONSE_QUEUE_URL,
                    ReceiptHandle=msg["ReceiptHandle"]
                )

                return body

            else:
                # Not ours — make visible again
                sqs.change_message_visibility(
                    QueueUrl=RESPONSE_QUEUE_URL,
                    ReceiptHandle=msg["ReceiptHandle"],
                    VisibilityTimeout=0
                )

    raise TimeoutError("BERT Inference result timed out")


if __name__ == "__main__":
    send_warmup()

    request_id = send_job(["Hello world", "test 2"])
    result = wait_for_result(request_id)

    print("Result:", result)