import type {
  ChatGrade,
  ChatNodeUpdate,
  RetrievedDocument,
} from "../api/chats";

export interface Attempt {
  queries?: string[];
  documents?: RetrievedDocument[];
  answer?: string;
  grade?: ChatGrade;
  feedback?: string;
  failureAnalysis?: string;
}

/** generate_queries_nodeだけがretry_countを持つ為、それを試行の添字として使う。 */
export function applyUpdate(
  attempts: Attempt[],
  { node, state }: ChatNodeUpdate,
): Attempt[] {
  // 先頭ノードの到着は新しい試行の開始を意味する。
  // retry_count番目より後に積んだ内容は破棄し、この試行で作り直す
  if (node === "generate_queries_node") {
    // retry_countは常に含まれる。?? は型要件を満たす為のフォールバック
    const index = state.retry_count ?? attempts.length;
    const next = attempts.slice(0, index);
    next[index] = { queries: state.queries };
    return next;
  }

  // 先頭ノードより先に他のノードが届くことはないが、念の為ここで打ち切る
  if (attempts.length === 0) return attempts;

  const current = { ...attempts[attempts.length - 1] };

  if (node === "retrieve_contexts_node") {
    current.documents = state.documents ?? [];
  } else if (node === "generate_answer_node") {
    current.answer = state.answer;
  } else if (node === "grade_answer_node") {
    current.grade = state.grade;
    current.feedback = state.feedback;
  } else if (node === "analyze_failure_node") {
    current.failureAnalysis = state.failure_analysis;
  }

  return [...attempts.slice(0, -1), current];
}
