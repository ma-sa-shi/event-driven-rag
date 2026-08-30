import { useState } from "react";
import type { UserQuota } from "../api/users";
import "./QuestionForm.css";

// バックエンドのChatStreamRequest(min_length=1, max_length=2000)に合わせる
const MAX_LENGTH = 2000;

interface QuestionFormProps {
  /** 成功したらtrueを返す。入力を残すか消すかの判断に使う */
  onSubmit: (question: string) => Promise<boolean>;
  isStreaming: boolean;
  /** 未取得の間はundefined。取得できない場合も送信は止めない(上限判定はサーバーが持つ) */
  quota?: UserQuota;
}

export function QuestionForm({
  onSubmit,
  isStreaming,
  quota,
}: QuestionFormProps) {
  const [question, setQuestion] = useState("");

  const isExhausted = quota !== undefined && quota.used >= quota.limit;
  const trimmed = question.trim();
  const canSubmit = trimmed.length > 0 && !isStreaming && !isExhausted;

  const handleSubmit = async (event: React.SyntheticEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    // 失敗時は書き直せるよう入力を残し、成功時だけクリアする
    if (await onSubmit(trimmed)) {
      setQuestion("");
    }
  };

  // textareaではEnterを改行に使う為、送信はCtrl/Cmd+Enterに割り当てる
  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      void handleSubmit(event);
    }
  };

  return (
    <form className="question-form" onSubmit={(e) => void handleSubmit(e)}>
      <label className="question-label" htmlFor="question">
        質問
      </label>
      <textarea
        id="question"
        className="question-input"
        rows={3}
        maxLength={MAX_LENGTH}
        placeholder="取り込んだドキュメントについて質問してください"
        value={question}
        disabled={isStreaming || isExhausted}
        onChange={(e) => setQuestion(e.target.value)}
        onKeyDown={handleKeyDown}
      />
      {quota && isExhausted && (
        <p className="question-exhausted" role="status">
          本日の利用上限（{quota.limit}
          回）に達しました。日付が変わると再び送信できます。
        </p>
      )}
      <div className="question-actions">
        <span className="question-hint">
          Ctrl(⌘) + Enter で送信 / {question.length} / {MAX_LENGTH}
        </span>
        <div className="question-submit">
          {quota && (
            <span
              className={
                isExhausted ? "question-quota is-exhausted" : "question-quota"
              }
            >
              残り {Math.max(quota.limit - quota.used, 0)} / {quota.limit} 回
            </span>
          )}
          <button type="submit" disabled={!canSubmit}>
            {isStreaming ? "生成中…" : "送信"}
          </button>
        </div>
      </div>
    </form>
  );
}
