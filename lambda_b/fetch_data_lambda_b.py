import os
import json
import boto3
from backend.fetch_data import analyze_sentiments_batch

s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
apigw_client = boto3.client("apigatewaymanagementapi", endpoint_url=os.environ.get("WS_ENDPOINT"))

S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")
CONNECTIONS_TABLE = os.environ.get("CONNECTIONS_TABLE")
BATCH_COUNT_TABLE = os.environ.get("BATCH_COUNT_TABLE")

conn_table = dynamodb.Table(CONNECTIONS_TABLE)
batch_table = dynamodb.Table(BATCH_COUNT_TABLE)

def lambda_handler(event, context):
    print(f"Received {len(event.get('Records', []))} records from SQS")

    for record in event.get('Records', []):
        try:
            message = json.loads(record['body'])
            batch_id = message['batch_id']
            items = message['items']

            if isinstance(items, str):
                items = json.loads(items)

            cleaned_items = []
            for item in items:
                if isinstance(item, str):
                    try:
                        item = json.loads(item)
                    except json.JSONDecodeError:
                        print(f"Skipped malformed item: {item}")
                        continue
                cleaned_items.append(item)

            print(f"Processing batch {batch_id} with {len(cleaned_items)} items")

            analyzed = analyze_sentiments_batch(cleaned_items)

            s3_key = f"analyzed_data/{batch_id}.json"
            s3_client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=s3_key,
                Body=json.dumps(analyzed),
                ContentType="application/json"
            )

            print(f"Stored analyzed data for batch {batch_id}")
            batch_table.put_item(Item={"batch_id": batch_id, "status": "done"})

            connections = conn_table.scan()["Items"]
            for conn in connections:
                try:
                    apigw_client.post_to_connection(
                        ConnectionId=conn["connectionId"],
                        Data=json.dumps({
                            "event": "batch_completed",
                            "payload": {"batch_id": batch_id}
                        }).encode("utf-8")
                    )
                    print(f"Sent batch_completed to {conn['connectionId']}")
                except apigw_client.exceptions.GoneException:
                    print(f"Connection gone, deleting {conn['connectionId']}")
                    conn_table.delete_item(Key={"connectionId": conn["connectionId"]})
        except Exception as e:
            print(f"Failed to process record: {e}")

    return {"message": f"Processed {len(event.get('Records', []))} batches"}
