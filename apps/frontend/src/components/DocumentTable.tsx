import type { DocumentSummary } from "../api/documents";
import { StatusBadge } from "./StatusBadge";
import "./DocumentTable.css";

interface DocumentTableProps {
  documents: DocumentSummary[];
  /** サインイン中のユーザーのsub。取込は本人のドキュメントにしか実行できない */
  currentUserId: string | undefined;
  onOpen: (documentId: string) => void;
  onIngest: (documentId: string) => void;
  openingId: string | null;
  ingestingId: string | null;
}

const dateFormatter = new Intl.DateTimeFormat("ja-JP", {
  dateStyle: "short",
  timeStyle: "short",
});

// バックエンドのステータス遷移(uploaded|failed → processing)に合わせる
const INGESTABLE = ["uploaded", "failed"];

export function DocumentTable({
  documents,
  currentUserId,
  onOpen,
  onIngest,
  openingId,
  ingestingId,
}: DocumentTableProps) {
  return (
    <table className="document-table">
      <thead>
        <tr>
          <th scope="col">ファイル名</th>
          <th scope="col">状態</th>
          <th scope="col">更新日時</th>
          <th scope="col">操作</th>
        </tr>
      </thead>
      <tbody>
        {documents.map((document) => {
          const canIngest =
            document.userId === currentUserId &&
            INGESTABLE.includes(document.status);
          return (
            <tr key={document.documentId}>
              <td className="filename">{document.filename}</td>
              <td>
                <StatusBadge status={document.status} />
              </td>
              <td className="updated-at">
                {dateFormatter.format(new Date(document.updatedAt))}
              </td>
              <td className="actions">
                <button
                  type="button"
                  onClick={() => onOpen(document.documentId)}
                  disabled={openingId === document.documentId}
                >
                  開く
                </button>
                {canIngest && (
                  <button
                    type="button"
                    className="primary"
                    onClick={() => onIngest(document.documentId)}
                    disabled={ingestingId === document.documentId}
                  >
                    取込開始
                  </button>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
