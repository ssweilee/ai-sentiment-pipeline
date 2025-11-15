# AI Sentiment Pipeline
## 🧩 Key Features
- **Asynchronous Processing:** Uses AWS SQS for scalable, non-blocking message handling.
- **Serverless Compute:** AWS Lambda functions for data fetching, analysis, and aggregation.
- **AI/NLP Integration:** Sentiment analysis and trend extraction using AWS Bedrock.
- **Reliable Storage:** Results stored in S3 and DynamoDB for easy retrieval.
- **Automated Deployment:** CI/CD with AWS Amplify (or CloudFormation/Terraform if used).

---


## 🏗️ Tech Stack

| Category | Technologies |
|-----------|---------------|
| **Frontend** | Next.js, TypeScript, TailwindCSS, Recharts |
| **Backend** | AWS Lambda (Python), API Gateway, SQS, S3, DynamoDB |
| **AI/NLP** | AWS Bedrock (Claude 3 Sonnet), LLM Integration, Sentiment Analysis |
| **Infrastructure** | Serverless Architecture, Event-Driven Processing, Amplify Deployment |
| **Version Control / DevOps** | Git, AWS Amplify (CI/CD) |

---

## 🧠 System Architecture
<pre>
Frontend (Next.js)
       ↓
API Routes (Next.js)
       ↓
AWS API Gateway
       ↓
Lambda fetch
    ↓
SQS (async queue)
    ↓
Lambda analyze → AWS Bedrock → S3
    ↓ (S3 trigger)
Lambda aggregate → generate insights → S3
       ↓
Frontend renders insights
</pre>

---

## Getting Started
The live demo is private due to usage limits, feel free to contact me for access.

---

## 🤖 Future Improvements
- Complete NLP preprocessing pipeline
- Implement microservice architecture for scalable sentiment analysis
- Add monitoring & logging dashboards
- Support multi-language datasets

---

🧑‍💻 Author
Developed independently by **Sandy Lee**, demonstrating applied AI, cloud computing, and serverless backend engineering.
