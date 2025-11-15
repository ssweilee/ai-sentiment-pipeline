import os
import boto3

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# S3 用來儲存 JSON 或分析結果
s3_client = boto3.client("s3", region_name=AWS_REGION)

# SageMaker 或 Bedrock LLM 客戶端
bedrock_client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
