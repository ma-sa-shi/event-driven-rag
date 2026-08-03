import axios from "axios";

/** APIエラーを画面表示用の日本語メッセージへ変換する。
 *
 * FastAPIのHTTPExceptionは{"detail": "..."}を返す為、あれば補足として添える。
 */
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
