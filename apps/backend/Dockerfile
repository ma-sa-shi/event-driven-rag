# syntax=docker/dockerfile:1
# 単一のFastAPIコードベースから3つのLambda関数 (api-fn / chat-fn / ingest-fn) 用のイメージをビルドする。
# 共通のbuilderをベースに、CDKでターゲットを指定して最終イメージを選択する:
# - web:    api-fn用、Lambda Web Adapter + uvicorn CMD（軽量なベース依存関係のみ）
# - chat:   chat-fn用、webに加えてlanggraph, langchain-*を含める(ベース依存関係の約10倍のサイズ)
#           CDK側でSSE用にAWS_LWA_INVOKE_MODE=response_streamを設定する
#           app.mainはlanggraphが存在する時のみSSEルーターを読み込む為、webイメージは重いライブラリを含めずに同じコードを実行可能
# - worker: ingest-fn 用、Adapterを介さないawslambdaric経由の標準Lambdaハンドラー
#           LWA は起動しないWebサーバーを待って初期化ブロックするため除外
#           PDF抽出用のingestグループを追加で入れる(LangChainは含めない)
#
# ローカル環境では、web, chatターゲットは普通の HTTP サーバーとして動作する
# LWAは Lambda実行環境外では動作しない為、影響しない

# ---- ベースビルダー: 高速なuvのセットアップ ----
FROM public.ecr.aws/docker/library/python:3.12-slim AS builder

# uv CLIを公式イメージからコピー
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/

# uv のビルド最適化フラグ:
# - UV_COMPILE_BYTECODE=1: 起動時間を短縮する為.pycファイルへ事前コンパイル
# - UV_LINK_MODE=copy: コンテナ内でのキャッシュ共有用
# - UV_PYTHON_DOWNLOADS=never: システムにインストール済みのPython 3.12を使用
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# 依存関係定義ファイルのコピーとベースの仮想環境 (.venv) 作成
COPY pyproject.toml uv.lock ./
# dev及びchatはローカル開発時のデフォルトグループの為--no-default-groupsを指定して除外
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-default-groups --no-install-project

# ---- chat用ビルダー: 共通venvにLangGraph, LangChain依存関係を追加 ----
FROM builder AS chat-builder
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-default-groups --group chat --no-install-project

# ---- worker 用ビルダー: 共通venvにawslambdaricとドキュメント処理依存を追加 ----
FROM builder AS worker-builder
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-default-groups --group worker --group ingest --no-install-project

# ---- web-base: LWAを使用する2ターゲットの共通ベース ----
FROM public.ecr.aws/docker/library/python:3.12-slim AS web-base

# LWAを追加し、HTTPリクエストを Lambdaイベントに変換
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.0.1 /lambda-adapter /opt/extensions/lambda-adapter

WORKDIR /app
COPY app ./app

# ポート設定:
# - PORT, AWS_LWA_PORT: Adapter(デフォルト8080)とuvicorn(8000)のポートを同期
# - AWS_LWA_READINESS_CHECK_PATH: Lambda起動時のヘルスチェックパス
ENV PATH="/app/.venv/bin:$PATH" \
    PORT=8000 \
    AWS_LWA_PORT=8000 \
    AWS_LWA_READINESS_CHECK_PATH=/api/health

EXPOSE 8000

# 1つのLambda Sandboxは同時に1リクエストのみ処理する為、デフォルトのSingle Worker(--workers 1)で十分
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---- ターゲット 1: web (api-fn) ----
FROM web-base AS web
COPY --from=builder /app/.venv ./.venv

# ---- ターゲット 2: chat (chat-fn: RAG パイプライン用重厚依存関係を含む) ----
FROM web-base AS chat
COPY --from=chat-builder /app/.venv ./.venv

# ---- ターゲット 3: worker (ingest-fn: Web Adapter なしの直接ハンドラー実行環境) ----
FROM public.ecr.aws/docker/library/python:3.12-slim AS worker

WORKDIR /app
COPY --from=worker-builder /app/.venv ./.venv
COPY app ./app

ENV PATH="/app/.venv/bin:$PATH"

# awslambdaricを使い、Python関数を直接起動
ENTRYPOINT ["/app/.venv/bin/python", "-m", "awslambdaric"]
CMD ["app.ingest_handler.handler"]
