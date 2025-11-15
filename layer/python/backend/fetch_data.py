import os
import json
import random
import subprocess
import praw
from googleapiclient.discovery import build
import httplib2
import boto3
import time
import concurrent.futures
from botocore.exceptions import ClientError
from backend.aws_client import bedrock_client  

MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")
s3_client = boto3.client("s3")

# Twitter 
def fetch_tweets(query="", limit=10):
    try:
        cmd = f"snscrape --jsonl twitter-search '{query}' --max-results {limit}"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        tweets = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        for t in tweets:
            t["sentiment_score"] = random.uniform(-1, 1)
        return tweets
    except Exception as e:
        print("Error fetching tweets:", e)
        return []

# Reddit 
def fetch_reddit(query="", limit=10):
    try:
        reddit = praw.Reddit(
            client_id=os.environ.get("REDDIT_CLIENT_ID"),
            client_secret=os.environ.get("REDDIT_SECRET"),
            user_agent="audience-sentiment-agent"
        )
        posts = []
        # search across all subreddits
        for post in reddit.subreddit("all").search(query=query, sort="hot", limit=limit):
            posts.append({
                "title": post.title,
                "score": post.score,
                "url": post.url,
                "created_utc": post.created_utc,
                "sentiment_score": random.uniform(-1, 1)
            })
        return posts
    except Exception as e:
        print("Error fetching Reddit posts:", e)
        return []

# YouTube 
def fetch_youtube(query="", max_results=10):
    try:
        YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
        http = httplib2.Http(timeout=20)
        youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY, http=http)
        request = youtube.search().list(q=query, part="snippet", maxResults=max_results)
        response = request.execute()
        for item in response.get("items", []):
            item["sentiment_score"] = random.uniform(-1, 1)
            if "url" not in item or not item["url"]:
                video_id = item.get("id", {}).get("videoId")
                item["url"] = f"https://www.youtube.com/watch?v={video_id}" if video_id else None
        return response.get("items", [])
    except Exception as e:
        print("Error fetching YouTube videos:", e)
        return []

# analyze sentiments in batch
def analyze_sentiments_batch(items, max_retries=5):
    if not items:
        return []

    prompts = [
        f'Analyze the sentiment of this social media post about a TV show or movie titled "{item.get("title","")}". '
        'Respond with only one word: Positive, Negative, or Neutral.'
        for item in items
    ]

    combined_prompt = "\n\n".join(prompts)
    body = {
        "anthropic_version": "bedrock-2023-05-31", # need to specify version
        "system": (
            "You are an expert social media analyst. Each post refers to a TV show or movie. "
            "Respond with one word for sentiment: Positive, Negative, or Neutral. Maintain order."
        ),
        "messages": [{"role": "user", "content": combined_prompt}],
        "max_tokens": 100,
        "temperature": 0.0
    }

    delay = 1
    for attempt in range(max_retries):
        try:
            response = bedrock_client.invoke_model(
                modelId=MODEL_ID,
                body=json.dumps(body).encode("utf-8"),
                accept="application/json",
                contentType="application/json"
            )
            result_body = json.loads(response["body"].read())
            sentiments_text = result_body["content"][0]["text"].strip().split("\n")

            for item, sentiment in zip(items, sentiments_text):
                item["sentiment"] = sentiment.strip() or "Unknown"

            print("🔹 Bedrock raw response:", result_body)
            print("🔹 Parsed sentiments_text:", sentiments_text)
            return items  

        except ClientError as e:
            code = e.response['Error']['Code']
            if code == 'ThrottlingException':
                time.sleep(delay + random.random())
                delay *= 2
            else:
                print(f"AWS ClientError: {e}")
                break
        except Exception as e:
            print(f"Error invoking batch: {e}")
            break

    for item in items:
        item["sentiment"] = "Unknown"
    return items


# generate insight
def generate_insight(stats, trend_summary=None, keyword="", max_retries=5):

    # get ratios
    positive = stats.get("positiveRatio", 0)
    negative = stats.get("negativeRatio", 0)
    neutral = stats.get("neutralRatio", 0)
    topics = stats.get("topics", [])

    # construct prompt
    prompt = f"""
        You are a professional marketing analyst. Based on the following social media sentiment statistics for '{keyword}', 
        write a concise, readable, and professional insight in English, 3 lines max, do not exceed max_tokens 100 tokens.  

        Include:
        - Short overview of audience sentiment
        - Trend over time (if available)
        - One observation about key topics: {', '.join(topics) or 'None'}

        Stats:
        - Positive: {round(positive, 2)}%
        - Negative: {round(negative, 2)}%
        - Neutral: {round(neutral, 2)}%
        Trend: {round(trend_summary*100, 2) if trend_summary is not None else 'No trend data'}

        Instructions:
        - Keep paragraphs concise and human-readable.
        - Use line breaks between paragraphs.
        - Avoid unnecessary repetition.
        """

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "system": "You are a professional marketing analyst. Read the sentiment stats and trend, then produce actionable insights in clear English.",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 100,
        "temperature": 0.5
    }

    delay = 1
    for attempt in range(max_retries):
        try:
            response = bedrock_client.invoke_model(
                modelId=MODEL_ID,
                body=json.dumps(body).encode("utf-8"),
                accept="application/json",
                contentType="application/json"
            )
            result_body = json.loads(response["body"].read())
            return result_body["content"][0]["text"].strip() if result_body.get("content") else "No insight available."
        except Exception as e:
            print(f"Attempt {attempt+1} failed: {e}")
            time.sleep(delay + random.random())
            delay *= 2

    return "No insight available."


# normalize 
def normalize(item, source, keyword=None):
    url = item.get("url")
    if source == "youtube":
        video_id = item.get("id", {}).get("videoId")
        if not video_id:
            return None
        url = url or f"https://www.youtube.com/watch?v={video_id}"
        title = item.get("snippet", {}).get("title", "No Title")
        import datetime
        published_at = item.get("snippet", {}).get("publishedAt")
        created_utc = int(datetime.datetime.fromisoformat(published_at.replace("Z", "+00:00")).timestamp()) if published_at else 0
        sentiment = item.get("sentiment")
        if isinstance(sentiment, float):
            sentiment = "Positive" if sentiment > 0 else "Negative" if sentiment < 0 else "Neutral"
        item["sentiment"] = sentiment
    elif source == "reddit":
        title = item.get("title", "No Title")
        created_utc = int(item.get("created_utc") or 0)
        sentiment = float(item.get("sentiment_score") or 0)
    elif source == "twitter":
        title = item.get("content", "No Title")
        created_utc = int(item.get("date") or 0)
        sentiment = float(item.get("sentiment_score") or 0)
    else:
        return None
    if not url:
        return None
    return {"title": title, "url": url, "created_utc": created_utc, "sentiment": sentiment, "source": source, "keyword": keyword }

# fetch all 
def fetch_all(keyword=None):
    reddit = fetch_reddit(query=keyword)
    youtube = fetch_youtube(query=keyword)
    tweets = fetch_tweets(query=keyword)
    combined_raw = [(r, "reddit") for r in reddit] + [(y, "youtube") for y in youtube] + [(t, "twitter") for t in tweets]
    seen = set()
    deduped = []
    for item, source in combined_raw:
        norm = normalize(item, source, keyword=keyword)
        if norm:
            key = (norm["url"], norm["source"])
            if key not in seen:
                seen.add(key)
                deduped.append(norm)
    return deduped