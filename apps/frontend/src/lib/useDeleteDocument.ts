import { useMutation, useQueryClient } from "@tanstack/react-query";
import { deleteDocument } from "../api/documents";
import { toErrorMessage } from "./errors";

const CONFIRM_MESSAGE =
  "このドキュメントを削除します。取り込んだ内容も消え、元に戻せません。";

/** ドキュメントを削除する。失敗の表示先はページごとに違う為、メッセージは呼び出し側へ渡す。 */
export function useDeleteDocument(onError: (message: string) => void) {
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: deleteDocument,
    // 失敗時も他の操作との競合を疑い、最新のステータスを取り直す
    onSettled: () =>
      // 削除したドキュメントは横断一覧とユーザー別一覧の双方に載る
      queryClient.invalidateQueries({
        predicate: (query) => query.queryKey.includes("documents"),
      }),
    onError: (e) =>
      onError(toErrorMessage(e, "ドキュメントの削除に失敗しました")),
  });

  const removeDocument = (documentId: string) => {
    if (!window.confirm(CONFIRM_MESSAGE)) {
      return;
    }
    mutation.mutate(documentId);
  };

  // mutationのvariablesは実行中のdocumentIdを指す。完了後も直前の値が残る為isPendingで絞る
  const deletingId = mutation.isPending ? (mutation.variables ?? null) : null;

  return { removeDocument, deletingId };
}
