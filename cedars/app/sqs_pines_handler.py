import boto3
import json
import time
import uuid

class SQS_Task_Handler:
    """
    This class sends PINES inference jobs and retrives results over AWS SQS queues.
    """

    def __init__(self, inference_queue_url, response_queue_url, aws_region):
        self.sqs = boto3.client("sqs", region_name=aws_region)

        self.inference_queue_url = inference_queue_url
        self.response_queue_url = response_queue_url

    def send_warmup(self):

        request_id = str(uuid.uuid4())

        message = {
            "is_warmup" : True,
            "request_id": request_id,
            "notes": [],
            "response_queue" : None
        }

        self.sqs.send_message(
            QueueUrl=self.inference_queue_url,
            MessageBody=json.dumps(message)
        )

        return request_id

    def send_job(self, notes):

        request_id = str(uuid.uuid4())

        message = {
            "is_warmup" : False,
            "request_id": request_id,
            "notes": notes,
            "response_queue" : self.response_queue_url
        }

        self.sqs.send_message(
            QueueUrl=self.inference_queue_url,
            MessageBody=json.dumps(message)
        )

        return request_id


    def wait_for_result(self, request_id, timeout=1800):

        start_time = time.time()

        while time.time() - start_time < timeout:

            response = self.sqs.receive_message(
                QueueUrl=self.response_queue_url,
                MaxNumberOfMessages=5,
                WaitTimeSeconds=20,  # long polling
            )

            messages = response.get("Messages", [])

            for msg in messages:
                body = json.loads(msg["Body"])

                if body.get("request_id") == request_id:

                    # Delete message after processing
                    self.sqs.delete_message(
                        QueueUrl=self.response_queue_url,
                        ReceiptHandle=msg["ReceiptHandle"]
                    )

                    return body

                else:
                    # Not ours — make visible again
                    self.sqs.change_message_visibility(
                        QueueUrl=self.response_queue_url,
                        ReceiptHandle=msg["ReceiptHandle"],
                        VisibilityTimeout=0
                    )

        raise TimeoutError("BERT Inference result timed out")