import type { Attempt } from "../lib/chatProgress";
import { GradeBadge } from "./GradeBadge";
import "./ChatProgress.css";

/** Vector Search / RRF / Rerankはretrieve_contexts_nodeの内部処理で単一のイベントとしてしか届かない為、
 * 1ステップにまとめて併記する。
 */
const STEPS = [
  {
    key: "queries",
    label: "Multi Query",
    sub: "質問から複数の検索クエリを生成",
  },
  {
    key: "documents",
    label: "検索",
    sub: "Vector Search / RRF / Rerank",
  },
  {
    key: "answer",
    label: "Generation",
    sub: "検索結果のみを根拠に回答を生成",
  },
  {
    key: "grade",
    label: "Self Evaluation",
    sub: "回答が質問に答えられているかを自己評価",
  },
] as const;

const scoreFormatter = new Intl.NumberFormat("ja-JP", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

interface ChatProgressProps {
  attempts: Attempt[];
  isStreaming: boolean;
}

export function ChatProgress({ attempts, isStreaming }: ChatProgressProps) {
  return (
    <section
      className="chat-progress"
      aria-label="回答生成の進行状況"
      role="status"
      aria-live="polite"
    >
      {attempts.map((attempt, index) => {
        const isLast = index === attempts.length - 1;
        // 未完了の先頭ステップ。SSEはノードの完了時にしか届かない為、
        // 「次に走っているはず」のステップを実行中として見せる
        const runningKey = isStreaming && isLast ? nextStepKey(attempt) : null;

        return (
          <div className="attempt" key={index}>
            <h3 className="attempt-title">
              {index === 0 ? "試行1" : `再試行（試行${index + 1}）`}
            </h3>
            <ol className="step-list">
              {STEPS.map((step) => (
                <li
                  className={`step step-${stepStatus(attempt, step.key, runningKey)}`}
                  key={step.key}
                >
                  <span className="step-dot" aria-hidden="true" />
                  <div className="step-body">
                    <span className="step-label">{step.label}</span>
                    <span className="step-sub">{step.sub}</span>
                    {renderDetail(attempt, step.key)}
                  </div>
                </li>
              ))}
            </ol>
            {attempt.failureAnalysis && (
              <div className="failure-analysis">
                <span className="step-label">失敗分析</span>
                <p>{attempt.failureAnalysis}</p>
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}

type StepKey = (typeof STEPS)[number]["key"];

function nextStepKey(attempt: Attempt): StepKey | null {
  return STEPS.find((step) => attempt[step.key] === undefined)?.key ?? null;
}

function stepStatus(
  attempt: Attempt,
  key: StepKey,
  runningKey: StepKey | null,
): "done" | "running" | "pending" {
  if (attempt[key] !== undefined) return "done";
  return key === runningKey ? "running" : "pending";
}

function renderDetail(attempt: Attempt, key: StepKey) {
  if (key === "queries" && attempt.queries) {
    return (
      <ul className="step-detail">
        {attempt.queries.map((query, index) => (
          <li key={index}>{query}</li>
        ))}
      </ul>
    );
  }

  if (key === "documents" && attempt.documents) {
    if (attempt.documents.length === 0) {
      return <p className="step-detail">該当するドキュメントがありません</p>;
    }
    return (
      <ul className="step-detail">
        {attempt.documents.map((document, index) => (
          <li key={index}>
            {document.filename ?? "（ファイル名なし）"}
            {document.score !== null && (
              <span className="doc-score">
                {scoreFormatter.format(document.score)}
              </span>
            )}
          </li>
        ))}
      </ul>
    );
  }

  if (key === "answer" && attempt.answer !== undefined) {
    return (
      <p className="step-detail">
        回答を生成しました（{attempt.answer.length}文字）
      </p>
    );
  }

  if (key === "grade" && attempt.grade) {
    return (
      <div className="step-detail">
        <GradeBadge grade={attempt.grade} />
        {attempt.feedback && <p className="feedback">{attempt.feedback}</p>}
      </div>
    );
  }

  return null;
}
