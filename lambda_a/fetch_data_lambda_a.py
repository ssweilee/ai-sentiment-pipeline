import os
import json
import boto3
import math
from datetime import datetime
from backend.fetch_data import fetch_all

S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")
sqs_client = boto3.client("sqs")
SQS_QUEUE_URL = os.environ.get("SQS_QUEUE_URL")

def run_a(keyword=None):
    raw_data = fetch_all(keyword=keyword)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    batch_size = 10

    for i in range(0, len(raw_data), batch_size):
        batch = raw_data[i:i+batch_size]
        batch_id = f"{timestamp}_{i//batch_size}"
        message = {
            "batch_id": batch_id,
            "items": batch
        }
        sqs_client.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=json.dumps(message)
        )

    print(f"Sent {math.ceil(len(raw_data) / batch_size)} batches to SQS")
    return {"message": f"Sent {math.ceil(len(raw_data) / batch_size)} batches to SQS"}


def lambda_handler(event, context):
    keyword = event.get("queryStringParameters", {}).get("keyword", None)
    return run_a(keyword)
