# コード規約の具体例

CLAUDE.md の「TypeScript Code Style」「Python Code Style」「Comments」で定めた規約について、判断に迷いやすい箇所を実際のコードで示す。規約そのものは CLAUDE.md が正であり、この文書は解釈と適用例を補うものとする。

引用元を示していないコード片は、説明のために書いた仮の例である。

## 目次

- [1. TypeScript](#1-typescript)
  - [1.1 分岐に名前を付ける](#11-分岐に名前を付ける)
  - [1.2 早期リターンで平坦にする](#12-早期リターンで平坦にする)
  - [1.3 中間変数は業務ルールに名前を付けるために使う](#13-中間変数は業務ルールに名前を付けるために使う)
  - [1.4 イディオムとして許容するもの](#14-イディオムとして許容するもの)
  - [1.5 抽象化を先取りしない](#15-抽象化を先取りしない)
  - [1.6 判断が割れる例](#16-判断が割れる例)
- [2. コメントとdocstring](#2-コメントとdocstring)
  - [2.1 残す価値のあるコメント](#21-残す価値のあるコメント)
  - [2.2 消すべきコメント](#22-消すべきコメント)
  - [2.3 docstring](#23-docstring)
- [3. Python](#3-python)
  - [3.1 匿名の入れ子dictを型にする](#31-匿名の入れ子dictを型にする)
  - [3.2 外部データの形はTypedDictで宣言する](#32-外部データの形はtypeddictで宣言する)
  - [3.3 Anyを使ってよい境界](#33-anyを使ってよい境界)
  - [3.4 状態とループ](#34-状態とループ)
- [4. 規約整備時に直した箇所](#4-規約整備時に直した箇所)

## 1. TypeScript

### 1.1 分岐に名前を付ける

ステータスのような有限の文字列ユニオンを扱うときは、分岐そのものを値の対応表として書く。

悪い例:

```tsx
export function StatusBadge({ status }: { status: DocumentStatus }) {
  return (
    <span className={`status-badge status-${status}`}>
      {status === "uploading"
        ? "アップロード中"
        : status === "uploaded"
          ? "未取込"
          : status === "processing"
            ? "取込中"
            : status === "ingested"
              ? "取込済"
              : "失敗"}
    </span>
  );
}
```

良い例（`apps/frontend/src/components/StatusBadge.tsx`）:

```tsx
const LABELS: Record<DocumentStatus, string> = {
  uploading: "アップロード中",
  uploaded: "未取込",
  processing: "取込中",
  ingested: "取込済",
  failed: "失敗",
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  return (
    <span className={`status-badge status-${status}`}>
      <span className="status-dot" aria-hidden="true" />
      {LABELS[status] ?? status}
    </span>
  );
}
```

`Record<DocumentStatus, string>` は全キーの定義を要求するため、`DocumentStatus` にステータスが増えたときに漏れがコンパイルエラーになる。三項演算子の連鎖では最後の `else` に吸い込まれて気付けない。

### 1.2 早期リターンで平坦にする

条件ごとに返す値が決まっている関数は、条件を並べて順に返す。

悪い例:

```ts
export function toErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status;
    if (status === 401 || status === 403) {
      return "認証の有効期限が切れた可能性があります。ページを再読み込みしてください。";
    } else if (status === 404) {
      return "対象のドキュメントが見つかりません。一覧を再取得してください。";
    } else {
      if (!error.response) {
        return `${fallback}（サーバーに接続できませんでした）`;
      } else {
        const detail = (error.response.data as { detail?: unknown } | undefined)
          ?.detail;
        return typeof detail === "string" ? `${fallback}（${detail}）` : fallback;
      }
    }
  } else {
    return fallback;
  }
}
```

良い例（`apps/frontend/src/lib/errors.ts`）:

```ts
export function toErrorMessage(error: unknown, fallback: string): string {
  if (!axios.isAxiosError(error)) {
    return fallback;
  }
  const status = error.response?.status;
  if (status === 401 || status === 403) {
    return "認証の有効期限が切れた可能性があります。ページを再読み込みしてください。";
  }
  if (status === 404) {
    return "対象のドキュメントが見つかりません。一覧を再取得してください。";
  }
  if (status === 409) {
    return "ドキュメントの状態が変わっています。一覧を再取得しました。";
  }
  if (!error.response) {
    return `${fallback}（サーバーに接続できませんでした）`;
  }
  const detail = (error.response.data as { detail?: unknown } | undefined)
    ?.detail;
  return typeof detail === "string" ? `${fallback}（${detail}）` : fallback;
}
```

条件が1段に揃うため、ケースの追加が1ブロックの追加で済む。最後の三項演算子は入れ子になっておらず「detailが文字列なら添える」という1段の判断なので残してよい。

### 1.3 中間変数は業務ルールに名前を付けるために使う

悪い例:

```tsx
{document.userId === currentUserId &&
  ["uploaded", "failed"].includes(document.status) && (
    <button type="button" onClick={() => onIngest(document.documentId)}>
      取込開始
    </button>
  )}
```

良い例（`apps/frontend/src/components/DocumentTable.tsx`）:

```tsx
// バックエンドのステータス遷移(uploaded|failed → processing)に合わせる
const INGESTABLE = ["uploaded", "failed"];

const canIngest =
  document.userId === currentUserId && INGESTABLE.includes(document.status);
```

「本人のドキュメントで、かつ取込可能な状態」という業務ルールに `canIngest` という名前が付く。JSXの中で条件を組み立てると、表示の都合と業務ルールが混ざって読み分けられなくなる。

逆に、値を移し替えるだけの中間変数は入れない。次のような変数は `document.filename` をそのまま使えばよい。

```ts
const filename = document.filename; // 不要
```

ラッパー関数も同じ基準で判断する。`apps/frontend/src/pages/Documents.tsx` の `invalidateDocuments` は中身が1行だが3箇所から呼ばれ、「一覧のキャッシュを無効化する」という操作に名前を与えているので残す価値がある。呼び出しが1箇所しかない1行のラッパーは書かない。

### 1.4 イディオムとして許容するもの

```tsx
onSuccess: () => void invalidateDocuments(),
onOpen={(id) => void handleOpen(id)}
```

`void` は `no-misused-promises` に対して「戻り値のPromiseを意図的に捨てる」ことを示す定型表現で、エコシステムで広く共有されている。この例外は、意図が一目で伝わる定型表現にのみ適用する。`!!value` や `~list.indexOf(x)` のような、短さのために意味を圧縮した書き方はこの例外に含めない。

### 1.5 抽象化を先取りしない

悪い例:

```ts
function createResourceHooks<T>(queryKey: string[], fetcher: () => Promise<T[]>) {
  return {
    useList: () => useQuery({ queryKey, queryFn: fetcher }),
    useInvalidate: () => {
      const queryClient = useQueryClient();
      return () => queryClient.invalidateQueries({ queryKey });
    },
  };
}

const documentHooks = createResourceHooks(["documents"], listDocuments);
```

良い例（`apps/frontend/src/pages/Documents.tsx`）:

```ts
const documentsQuery = useQuery({
  queryKey: DOCUMENTS_QUERY_KEY,
  queryFn: listDocuments,
  // 取込中の行があればキャッシュを定期的に更新する。
  refetchInterval: (query) =>
    query.state.data?.some((document) => document.status === "processing")
      ? POLL_INTERVAL_MS
      : false,
});
```

現時点で一覧を持つリソースはドキュメントだけであり、共通化しても呼び出し側は短くならない。むしろ `refetchInterval` のようなリソース固有の設定を汎用フックへ通す口が必要になり、抽象が壊れる。2つ目のリソースが現れて共通部分が確定してから括る。

### 1.6 判断が割れる例

`apps/frontend/src/pages/Documents.tsx` にあった次の記述は、入れ子の三項ではないため規約違反ではないが、JSXの属性内で条件と `??` が重なって読み取りに一拍かかる。

```tsx
ingestingId={
  ingestMutation.isPending ? (ingestMutation.variables ?? null) : null
}
```

変数へ抽出すると、`isPending` で絞る理由をコメントで補える位置ができる。

```tsx
// mutationのvariablesは実行中のdocumentIdを指す。完了後も直前の値が残る為isPendingで絞る
const ingestingId = ingestMutation.isPending
  ? (ingestMutation.variables ?? null)
  : null;
```

この種の判断は「JSXを上から読んで各属性が何を渡しているか一読で分かるか」を基準にする。分からなければ props へ渡す前に名前を付ける。

## 2. コメントとdocstring

### 2.1 残す価値のあるコメント

いずれもコードからは読み取れない理由・制約・他モジュールとの取り決めを書いている。

```ts
// apps/frontend/src/lib/fileTypes.ts
// text/markdownはブラウザが表示せずダウンロードしてしまう為、原本閲覧のできるtext/plainで保存する。
// バックエンドはContent-Typeではなく拡張子で形式を判定するので取込結果は変わらない
".md": "text/plain; charset=utf-8",
```

```ts
// apps/frontend/src/pages/Documents.tsx
// await後のwindow.openはポップアップブロックの対象になる為、クリック直後に空タブを開く
const tab = window.open("", "_blank");
```

```python
# apps/backend/app/ingest/chunking.py
"""抽出テキストを検索単位のチャンクへ分割する。

langchain-text-splittersはlangchain-coreを引き込みworkerイメージを重くする為、自前実装する(ADR-0003)。
"""
```

```python
# apps/backend/app/ingest/pipeline.py
"""再取込でチャンク数が減ったときに、余った古いベクトルを削除する。

既存keyは上書きされるため、超過分だけを消せば良い
ListVectorsにprefix絞り込みがない為、前回のチャンク数から削除対象を決める
"""
```

判断基準は「このコメントを消したら、次に読む人が調べ直す羽目になるか」である。ADRで詳細を説明済みのものは、理由を1行に圧縮して参照先を書く。

### 2.2 消すべきコメント

コードがそのまま言っていることを繰り返すコメントは書かない。

```python
# apps/backend/app/rag/utils.py（修正前）
sorted_items = sorted(
    doc_score_map.items(),
    key=lambda x: x[1]["score"],
    reverse=True,  # 降順
)
```

`reverse=True` は降順であり、コメントは情報を足していない。

```ts
// ドキュメント一覧を取得する
export async function listDocuments(): Promise<DocumentSummary[]> {
```

関数名と戻り値の型が既に述べている。

### 2.3 docstring

悪い例（`apps/backend/app/rag/utils.py` の修正前）:

```python
def reciprocal_rank_fusion(
    retriever_outputs: list[list[Document]], k: int = 60, top_n: int = 20
) -> list[Document]:
    """複数クエリの検索結果を相互順位融合(RRF)で1本に統合する。

    Args:
        retriever_outputs: クエリごとの検索結果
        k: 順位の影響を緩めるRRFの定数
        top_n: 返すドキュメント数

    Returns:
        スコア降順のドキュメント。同一ドキュメントはdoc.idで名寄せされる
    """
```

`retriever_outputs` と `top_n` の説明は名前と型の言い換えでしかない。一方で「kが何の定数か」「同一ドキュメントをdoc.idで名寄せする」は署名から読み取れないため残す。

良い例:

```python
def reciprocal_rank_fusion(
    retriever_outputs: list[list[Document]], k: int = 60, top_n: int = 20
) -> list[Document]:
    """複数クエリの検索結果を相互順位融合(RRF)で1本に統合する。

    同一ドキュメントはdoc.idで名寄せする。kは順位差の影響を緩める定数。
    """
```

例外を契約として伝える場合は `Raises:` を書く。`DocumentRepository.update_status` の `DocumentStatusError` は呼び出し側が409へ変換する必要があるため、docstringで明示している。

## 3. Python

### 3.1 匿名の入れ子dictを型にする

悪い例（`apps/backend/app/rag/utils.py` の修正前）:

```python
# { doc_id: {score: スコア, document: Documentオブジェクト} }
doc_score_map: dict[str, dict] = {}

for docs in retriever_outputs:
    for rank, doc in enumerate(docs):
        if doc.id not in doc_score_map:
            doc_score_map[doc.id] = {"score": 0.0, "document": doc}
        doc_score_map[doc.id]["score"] += 1 / (rank + k)

sorted_items = sorted(doc_score_map.items(), key=lambda x: x[1]["score"], reverse=True)
return [item[1]["document"] for item in sorted_items[:top_n]]
```

問題は3点ある。内側の `dict` が未パラメータ化で中身が型で表現されていないこと、その構造をコメントで補っていること、`item[1]["document"]` のように意味のあるフィールドを位置と文字列キーで取り出していることである。

良い例:

```python
@dataclass
class _FusedDocument:
    document: Document
    score: float = 0.0


def reciprocal_rank_fusion(
    retriever_outputs: list[list[Document]], k: int = 60, top_n: int = 20
) -> list[Document]:
    """複数クエリの検索結果を相互順位融合(RRF)で1本に統合する。

    同一ドキュメントはdoc.idで名寄せする。kは順位差の影響を緩める定数。
    """
    fused: dict[str, _FusedDocument] = {}
    for docs in retriever_outputs:
        for rank, doc in enumerate(docs):
            entry = fused.setdefault(doc.id, _FusedDocument(document=doc))
            entry.score += 1 / (rank + k)

    ranked = sorted(fused.values(), key=lambda entry: entry.score, reverse=True)
    return [entry.document for entry in ranked[:top_n]]
```

構造を説明していたコメントが型定義に置き換わり、`entry.score` / `entry.document` で意味が読める。

### 3.2 外部データの形はTypedDictで宣言する

DynamoDBの項目のように、辞書の形が他モジュールとの契約になっているものは `TypedDict` で宣言する。

悪い例（`apps/backend/app/repositories/documents.py` の修正前）:

```python
def get_owned(self, user_id: str, document_id: str) -> dict | None: ...
def list_recent(self, limit: int) -> list[dict]: ...
```

呼び出し側は `document["s3Key"]` や `document.get("chunkCount", 0)` のようにキーを直接書くが、そのキーが存在するかどうかは型に現れない。

良い例:

```python
class DocumentItem(TypedDict):
    PK: str
    SK: str
    documentId: str
    userId: str
    filename: str
    s3Key: str
    status: str
    createdAt: str
    updatedAt: str


class IngestedDocumentItem(DocumentItem):
    # 取込完了後のみ付与される。再取込で余剰ベクトルを削除する際に参照する
    chunkCount: NotRequired[Decimal]


def get_owned(self, user_id: str, document_id: str) -> DocumentItem | None: ...
def list_recent(self, limit: int) -> list[DocumentItem]: ...
```

`chunkCount` が任意項目であることや、DynamoDBの数値が `Decimal` で返ることが型に現れる。`pipeline.py` の次のコメントは、型が同じ内容を語るようになったため2行から1行へ減らせた。

```python
# 修正前
# 初回取込ではchunkCountを持たないため0で代替する
# DynamoDBの数値はDecimalで返り、そのままではrange()に渡せない
previous_count=int(document.get("chunkCount", 0)),

# 修正後
# 初回取込ではchunkCountを持たない。Decimalのままではrange()へ渡せない
previous_count=int(document.get("chunkCount", 0)),
```

### 3.3 Anyを使ってよい境界

悪い例（`apps/backend/app/ingest/pipeline.py` の修正前）:

```python
@dataclass(frozen=True)
class IngestPipeline:
    bucket_name: str
    repository: DocumentRepository
    embedder: Any
    vector_index: VectorIndex
    s3_client: Any
```

`s3_client` は boto3 が動的にクライアントを生成し正確な型を付けられないため `Any` が妥当である。一方 `embedder` は自前の `CohereEmbedder` であり、テストで差し替えたいだけなら必要なメソッドを `Protocol` で宣言できる。

良い例:

```python
class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class IngestPipeline:
    bucket_name: str
    repository: DocumentRepository
    embedder: Embedder
    vector_index: VectorIndex
    # boto3のクライアントは動的に生成され、型を付けられない
    s3_client: Any
```

「型が付けられないから `Any`」と「差し替えたいから `Any`」を区別する。前者は理由をコメントに残し、後者は `Protocol` で必要なメソッドだけを宣言する。

### 3.4 状態とループ

同じ状態を表す変数を複数持たない。

```python
# 悪い例
kept: list[str] = []
kept_count = 0
for chunk in chunks:
    if chunk:
        kept.append(chunk)
        kept_count += 1

# 良い例
kept = [chunk for chunk in chunks if chunk]
kept_count = len(kept)
```

引数は再代入せず、新しいローカル変数を導入する。

```python
# 悪い例
def split_text(text: str, *, chunk_size: int = CHUNK_SIZE) -> list[str]:
    text = text.strip()
    ...

# 良い例
def split_text(text: str, *, chunk_size: int = CHUNK_SIZE) -> list[str]:
    normalized = text.strip()
    ...
```

複雑な状態管理が避けられない場合は、保つべき不変条件を書く。`apps/backend/app/ingest/chunking.py` の `_merge` が該当する。

```python
chunks: list[str] = []
current: list[str] = []
# currentをseparatorで連結したときの長さ
total = 0
```

`total` は `current` から計算できる派生値だが、ループのたびに再計算するとチャンク分割が O(n²) になるため保持している。この場合は「`total` が何と一致していなければならないか」を1行で書く。派生値のキャッシュは、このように性能上の理由があるときに限る。

## 4. 規約整備時に直した箇所

規約を後から整備したため、既存コードに未適用の箇所が残っていた。次の箇所は適用済みである。

| 箇所 | 内容 |
| --- | --- |
| `app/rag/utils.py` | `dict[str, dict]` を `_FusedDocument` へ。`Args:` / `Returns:` の羅列と `reverse=True,  # 降順` を削除し、位置指定アクセスを名前付きアクセスへ |
| `app/repositories/*.py` | 戻り値の `dict` / `list[dict]` を `DocumentItem` / `ChatItem` / `ChatAttemptItem` / `UserProfileItem` へ。ステータスは `DocumentStatus` のLiteral型にした |
| `app/rag/stream.py` | `to_document_payload` の戻り値を `RetrievedDocument` へ。`_attempts` の `list[tuple]` を `Attempt` NamedTupleにし、試行の各要素を名前で参照できるようにした |
| `app/ingest_queue.py` / `app/ingest_handler.py` | SQSメッセージ本文を `IngestMessage` として宣言。Powertoolsデコレータの説明コメントを1行へ |
| `app/ingest/pipeline.py` | `embedder: Any` を `Embedder` Protocolへ。`s3_client: Any` は理由をコメントに残して維持 |
| `app/rag/state.py` | `GraphState` の `Attributes:` ブロックを、署名から読み取れない内容だけへ圧縮 |
| `app/routers/*.py` | `model_validate(i) for i in ...` の `i` を `item` へ |
| `apps/frontend/src/pages/Documents.tsx` | JSX属性内で組み立てていた `ingestingId` を変数へ抽出 |

RAGまわり（`app/rag/`）は既存実装からの移植であり、規約整備前の書き方が入り込みやすい。移植を続けるときは、移植元の書き方をそのまま持ち込まないよう合わせて調整する。
