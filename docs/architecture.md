# ADR: Serverless Architecture

- Status: Proposed
- Date: 2026-07-18

## Overview

本システムは社内向けRAGチャットアプリケーションとして、AWSのサーバーレスサービスを中心に構成する。

設計方針は以下のとおり。

- フロントエンドはSPA
- バックエンドはFastAPI + AWS Lambda
- ベクトル検索はS3 Vectors
- データはDynamoDB
- 認証はAmazon Cognito
- VPCは利用しない
- 固定費を極力ゼロにする

---

# Architecture

```text
                        Browser
                  (Vite + React SPA)
                           │
                           ▼
                  CloudFront
        ┌──────────────────┴──────────────────┐
        │                                     │
        ▼                                     ▼
 S3 (Static SPA)                  Lambda Function URL
                                  (/api/*)
                                        │
                      ┌─────────────────┴─────────────────┐
                      ▼                                   ▼
                  api-fn                            chat-fn
               (REST API)                      (SSE Streaming)
                      │
                      ▼
                     SQS
                      │
                      ▼
                 ingest-fn
                      │
      ┌───────────────┼────────────────┐
      ▼               ▼                ▼
 DynamoDB            S3          S3 Vectors
```

---

# Frontend

## Technology

- Vite
- React
- TypeScript
- React Router
- TanStack Query

## Deployment

- S3
- CloudFront

SSRは採用しない。

OpenNextおよびNext.js Server Runtimeは利用しない。

---

# Authentication

Amazon Cognito User Poolを利用する。

認証フロー

```text
SPA

↓

Cognito Hosted UI

↓

Authorization Code + PKCE

↓

Access Token

↓

Authorization Header

↓

FastAPI
```

FastAPIではJWKSによるJWT検証のみを行う。

パスワード管理やJWT発行は実装しない。

MFAは有効化を推奨する。

---

# Backend

FastAPIを1つのDockerイメージとして管理し、3つのLambdaへデプロイする。

## api-fn

用途

- 認証API
- ドキュメント一覧
- チャット一覧
- presigned URL発行
- アップロード完了登録
- 取込開始

Lambda Web Adapterを利用する。

---

## chat-fn

用途

- SSE
- LangGraph
- Self-RAG

Lambda Web Adapterを利用する。

LangChain系ライブラリは本関数のみでロードする。

---

## ingest-fn

用途

- テキスト抽出
- チャンク生成
- Embedding生成
- S3 Vectors登録

SQSイベントから起動する。

Lambda Web Adapterは利用しない。

通常のLambda Handlerで実装する。

---

# Upload Flow

ファイルはLambdaを経由しない。

```text
① presigned URL取得

SPA
    │
    ▼
api-fn

② Upload

SPA
    │
 PUT
    ▼
S3

③ Upload完了登録

SPA
    │
    ▼
api-fn

status = uploaded
```

---

# Ingest Flow

アップロードと取込は分離する。

ユーザーが「取込」を実行したときのみEmbeddingを開始する。

```text
SPA

↓

api-fn

↓

SQS

↓

ingest-fn
```

ステータス

```
uploaded
    ↓
processing
    ↓
ingested

または

failed
```

DLQを設定する。

---

# RAG Pipeline

LangGraphによるSelf-RAGを採用する。

処理フロー

```text
Query
    ↓
Multi Query
    ↓
Vector Search
    ↓
RRF
    ↓
Cohere Rerank
    ↓
LLM Generation
    ↓
Self Evaluation
    ↓
Retry (Max 1)
    ↓
Answer
```

Vector DatabaseはS3 Vectorsを利用する。

---

# Data Store

## DynamoDB

シングルテーブル設計。

管理対象

- Documents
- Chat
- Chat Messages

例

```
PK = USER#123

SK = CHAT#20260718...
```

---

## Amazon S3

用途

- SPA
- 原本ファイル

---

## Amazon S3 Vectors

用途

- Embedding

Metadata

- userId
- documentId
- chunkId

---

# CloudFront

Origin

```
/

↓

S3
```

```
/api/*

↓

Lambda Function URL
```

SSE

- Origin Response Timeout: 60秒
- KeepAlive: 15〜20秒

---

# Logging

Lambda Powertoolsを利用する。

- Structured Logging
- Metrics
- Tracing

Request IDを全サービスで引き継ぐ。

---

# Infrastructure

AWS CDKを利用する。

Stack構成

- DataStack
- AppStack
- EdgeStack
- CiStack

---

# CI/CD

GitHub Actions

Frontend

```
Build

↓

S3 Sync

↓

CloudFront Invalidation
```

Backend

```
Docker Build

↓

ECR Push

↓

Lambda Update
```

---

# Cost Optimization

- VPCなし
- NATなし
- ECSなし
- EC2なし
- Auroraなし

Provisioned Concurrencyは利用しない。

必要になった場合のみchat-fnへ適用する。

---

# Expected Cost

少量利用（月数百チャット）

| Service | Cost |
|---------|------:|
| Lambda | <$1 |
| DynamoDB | ~$0.5 |
| S3 | ~$0.5 |
| S3 Vectors | ~$0.5 |
| CloudFront | Free Tier |
| Cognito | Free Tier |
| SQS | Free Tier |

合計

**約 $1〜2 / 月**

---

# Development Order

1. CDK
2. Vite + React
3. Cognito
4. api-fn
5. chat-fn（モック）
6. Upload
7. Ingest
8. S3 Vectors
9. LangGraph
10. CloudFront
11. CI/CD

---

# Design Principles

- SPA + REST APIを基本とする
- サーバーレンダリングは採用しない
- FastAPIへバックエンドを集約する
- Lambdaは責務ごとに分離する
- ファイルはS3へ直接アップロードする
- UploadとIngestを分離する
- Embeddingは明示的な取込時のみ生成する
- 固定費ゼロを優先する
- 運用をシンプルに保つ
