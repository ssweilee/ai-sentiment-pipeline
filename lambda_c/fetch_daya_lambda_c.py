import os
import json
import boto3
import time
from datetime import datetime
from backend.fetch_data import generate_insight
from botocore.exceptions import ClientError

# AWS clients
s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
apigw_client = boto3.client("apigatewaymanagementapi", endpoint_url=os.environ.get("WS_ENDPOINT"))

# Environment variables
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")
CONNECTIONS_TABLE = os.environ.get("CONNECTIONS_TABLE")
BATCH_COUNT_TABLE = os.environ.get("BATCH_COUNT_TABLE")
LOCK_TABLE = os.environ.get("LOCK_TABLE") 

# DynamoDB tables
conn_table = dynamodb.Table(CONNECTIONS_TABLE)
batch_table = dynamodb.Table(BATCH_COUNT_TABLE)
lock_table = dynamodb.Table(LOCK_TABLE)

LOCK_KEY = "aggregate_lock" # global lock key for aggregation

def acquire_lock():
    try:
        # try to acquire a lock in DynamoDB, fail if it already exists
        lock_table.put_item(
            Item={"lockId": LOCK_KEY, "timestamp": int(time.time())},
            ConditionExpression="attribute_not_exists(lock_id)"
        )
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            return False # Lock already held
        raise

# release lock after aggregation to allow other Lambda invocations 
def release_lock():
    lock_table.delete_item(Key={"lockId": LOCK_KEY})

def lambda_handler(event, context):
    print("Lambda C triggered by S3 event")
    
    for record in event['Records']:
        s3_key = record['s3']['object']['key']
        batch_id = s3_key.split("/")[-1].replace(".json", "")
        print(f"Processing completed batch {batch_id}")

        # mark batch as done
        batch_table.put_item(Item={"batch_id": batch_id, "status": "done"})

    # try to acquire aggregation lock
    if not acquire_lock():
        print("Another Lambda is aggregating. Exiting...")
        return

    try:
        # scan all batch records
        all_batches = batch_table.scan()["Items"]
        if not all([b["status"] == "done" for b in all_batches]):
            print("Not all batches done yet. Releasing lock and exiting...")
            return

        connections = conn_table.scan().get("Items", [])
        if not connections:
            print("No WebSocket connections found, insight_completed will not be sent")

        # aggregate all batch data
        aggregated_data = []
        keywords = set() 
        for b in all_batches:
            obj = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=f"analyzed_data/{b['batch_id']}.json")
            batch_data = json.loads(obj["Body"].read())  
            aggregated_data.extend(batch_data)
            batch_table.delete_item(Key={"batch_id": b["batch_id"]})
            
            # collect keywords
            for item in batch_data:
                if "keyword" in item and item["keyword"]:
                    keywords.add(item["keyword"])

            batch_table.delete_item(Key={"batch_id": b["batch_id"]})

            # print sample items and sentiment types for debugging
            for item in batch_data[:3]:
                print("Sample item:", item, "sentiment type:", type(item.get("sentiment")))

        print(f"Aggregated {len(aggregated_data)} items from all batches")
        if keywords:
            keyword = list(keywords)[0]
        else:
            keyword = event.get("keyword", "Unknown")

        # compute statistics and trends for insight and chart
        def compute_stats(items):
            total = len(items)
            positive = sum(1 for x in items if str(x.get("sentiment")).lower() == "positive")
            negative = sum(1 for x in items if str(x.get("sentiment")).lower() == "negative")
            return {
                "positiveRatio": round(positive / total * 100, 2) if total else 0,
                "negativeRatio": round(negative / total * 100, 2) if total else 0,
                "topics": [x.get("title") for x in items if "title" in x][:5],
                "total": total
            }

        def compute_trend(posts):
            """
            Returns a list of daily sentiment counts for charting:
            [{"date": "YYYY-MM-DD", "Positive": x, "Negative": y, "Neutral": z}, ...]
            """
            from collections import defaultdict
            trend_map = defaultdict(lambda: {"Positive": 0, "Negative": 0, "Neutral": 0})

            for p in posts:
                date = p.get("date")
                if not date:
                    # fallback if no date field
                    timestamp = p.get("created_utc", 0)
                    date = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")
                sentiment = str(p.get("sentiment", "Neutral")).capitalize()
                if sentiment not in ["Positive", "Negative", "Neutral"]:
                    sentiment = "Neutral"
                trend_map[date][sentiment] += 1

            trend_list = []
            for date in sorted(trend_map.keys()):
                trend_list.append({"date": date, **trend_map[date]})
            return trend_list


        stats = compute_stats(aggregated_data)
        # compute overall trend summary
        trend_score = sum(
            1 if x["sentiment"].lower() == "positive" 
            else -1 if x["sentiment"].lower() == "negative" 
            else 0 
            for x in aggregated_data
        )
        trend_summary = trend_score / len(aggregated_data) if aggregated_data else 0
        insight_text = generate_insight(stats, trend_summary=trend_summary, keyword=keyword)

        # save final insight to S3
        insight_key = "final_insight.json"
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=f"insights/{insight_key}",
        Body=json.dumps({"insight": insight_text}),
            ContentType="application/json"
        )
        print(f"Insight saved to {insight_key}")

        # WebSocket notifications
        connections = conn_table.scan().get("Items", [])
        print(f"Connections: {connections}")
        print(conn_table.scan())
        for conn in connections:
            try:
                payload = {
                    "event": "insight_completed",
                    "payload": {
                        "insight": insight_text,           
                        "posts": aggregated_data,          
                        "stats": stats,                    
                        "trend": compute_trend(aggregated_data),  
                        "progress": {"completedBatches": len(all_batches), "totalBatches": len(all_batches)}
                    }
                }
                apigw_client.post_to_connection(
                    ConnectionId=conn["connectionId"],
                    Data=json.dumps(payload).encode("utf-8")
                )

                print(f"Sent insight_completed to {conn['connectionId']}")
            except apigw_client.exceptions.GoneException:
                conn_table.delete_item(Key={"connectionId": conn["connectionId"]})

    finally:
        release_lock() # always release lock at the end
        print("Released aggregation lock")