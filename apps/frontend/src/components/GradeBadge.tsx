import type { ChatGrade } from "../api/chats";
import "./GradeBadge.css";

const LABELS: Record<ChatGrade, string> = {
  useful: "有用",
  useless: "不十分",
  hallucination: "根拠なし",
};

export function GradeBadge({ grade }: { grade: ChatGrade }) {
  return (
    <span className={`grade-badge grade-${grade}`}>
      {LABELS[grade] ?? grade}
    </span>
  );
}
