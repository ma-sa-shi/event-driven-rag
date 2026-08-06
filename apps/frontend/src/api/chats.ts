import { userManager } from "../auth/userManager";
import { toHttpErrorMessage } from "../lib/errors";
import { readSse } from "../lib/sse";
import { api } from "./client";

/** 回答評価の結果。バックエンドのapp/rag/state.pyと対応する。 */
export type ChatGrade = "useful" | "useless" | "hallucination";

export interface ChatSummary {
  chatId: string;
  userId: string;
  question: string;
  finalAnswer: string | null;
  finalGrade: ChatGrade | null;
  retryCount: number;
  createdAt: string;
}

export interface RetrievedDocument {
  documentId: string | null;
  filename: string | null;
  text: string | null;
  /** Rerankを通っていない場合はnull */
  score: number | null;
}

/** バックエンドのapp/rag/nodes.pyの関数名がそのまま識別子になっており、片方だけ変えると進行表示が壊れる。 */
export type RagNode =
  | "generate_queries_node"
  | "retrieve_contexts_node"
  | "generate_answer_node"
  | "grade_answer_node"
  | "analyze_failure_node";

/** キーはバックエンドのGraphStateに合わせたsnake_caseで、documentsの中身だけがAPI共通shapeのcamelCase。
 * 更新したキーだけをノードが載せる為、全てoptional。
 */
export interface RagNodeState {
  queries?: string[];
  retry_count?: number;
  documents?: RetrievedDocument[];
  answer?: string;
  grade?: ChatGrade;
  feedback?: string;
  failure_analysis?: string;
}

/** 失敗の扱いを1箇所へまとめる為、SSEのerrorイベントはonEventへ渡さずthrowへ寄せる。 */
export type ChatStreamEvent =
  | { type: "update"; node: RagNode; state: RagNodeState }
  | {
      type: "done";
      chatId: string;
      finalGrade: ChatGrade | null;
      retryCount: number;
    };

export async function listChats(): Promise<ChatSummary[]> {
  const res = await api.get<ChatSummary[]>("/chats");
  return res.data;
}

/** API Gatewayの統合タイムアウト(29秒)や回線断では、doneもerrorも来ないままbodyが閉じる。
 * 無言で成功扱いにしない為に使う。
 */
const INTERRUPTED_MESSAGE =
  "回答の生成が中断されました。もう一度お試しください。";

/** POST + Authorizationヘッダーで購読する理由はADR-0012。
 * axiosは逐次読み出しに対応しない為ここだけfetchを使い、client.tsのインターセプタ相当を自前で書く。
 */
export async function streamChat(
  question: string,
  onEvent: (event: ChatStreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const user = await userManager.getUser();

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  // トークンが無い場合はヘッダーを付けず、サーバー側に401を返させる
  if (user?.access_token) {
    headers.Authorization = `Bearer ${user.access_token}`;
  }

  let res: Response;
  try {
    res = await fetch("/api/chats/stream", {
      method: "POST",
      headers,
      body: JSON.stringify({ question }),
      signal,
    });
  } catch (e) {
    // 中断は呼び出し側で区別する為そのまま投げ直す
    if (e instanceof Error && e.name === "AbortError") throw e;
    throw new Error(
      "回答の生成に失敗しました（サーバーに接続できませんでした）",
      {
        cause: e,
      },
    );
  }

  // fetchは4xx/5xxでrejectしない為、ステータスを自分で確認する
  if (!res.ok) {
    const authMessage = toHttpErrorMessage(res.status);
    if (authMessage) {
      throw new Error(authMessage);
    }
    throw new Error(await toResponseMessage(res));
  }
  if (!res.body) {
    throw new Error(INTERRUPTED_MESSAGE);
  }

  for await (const sse of readSse(res.body)) {
    if (sse.event === "update") {
      const { node, state } = JSON.parse(sse.data) as {
        node: RagNode;
        state: RagNodeState;
      };
      onEvent({ type: "update", node, state });
    } else if (sse.event === "done") {
      const { chatId, finalGrade, retryCount } = JSON.parse(sse.data) as {
        chatId: string;
        finalGrade: ChatGrade | null;
        retryCount: number;
      };
      onEvent({ type: "done", chatId, finalGrade, retryCount });
      return;
    } else if (sse.event === "error") {
      const { message, requestId } = JSON.parse(sse.data) as {
        message: string;
        requestId: string;
      };
      throw new Error(`${message}（リクエストID: ${requestId}）`);
    }
    // 上記以外のイベント名(KeepAlive等)は画面へ出さず読み飛ばす
  }

  throw new Error(INTERRUPTED_MESSAGE);
}

async function toResponseMessage(res: Response): Promise<string> {
  const fallback = `回答の生成に失敗しました（HTTP ${res.status}）`;
  try {
    const body: unknown = await res.json();
    const detail = (body as { detail?: unknown }).detail;
    return typeof detail === "string"
      ? `回答の生成に失敗しました（${detail}）`
      : fallback;
  } catch {
    return fallback;
  }
}
