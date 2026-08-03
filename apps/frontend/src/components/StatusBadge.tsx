import type { DocumentStatus } from "../api/documents";
import "./StatusBadge.css";

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
