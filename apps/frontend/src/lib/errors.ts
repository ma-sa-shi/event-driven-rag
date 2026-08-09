import axios from "axios";

/** SSEはaxiosを通らずfetchで呼ぶ為、ステータス単体で受け取れる形に切り出している。 */
export function toAuthErrorMessage(status: number | undefined): string | null {
  if (status === 401 || status === 403) {
    return "認証の有効期限が切れた可能性があります。ページを再読み込みしてください。";
  }
  return null;
}

/** toErrorMessageの404は一覧の再取得を促す文言で、詳細画面には合わない。
 * 画面ごとの案内へ差し替えられるよう判定だけ切り出す。
 */
export function isNotFound(error: unknown): boolean {
  return axios.isAxiosError(error) && error.response?.status === 404;
}

/** FastAPIのHTTPExceptionは{"detail": "..."}を返す為、あれば補足として添える。 */
export function toErrorMessage(error: unknown, fallback: string): string {
  if (!axios.isAxiosError(error)) {
    return fallback;
  }
  const status = error.response?.status;
  const authMessage = toAuthErrorMessage(status);
  if (authMessage) {
    return authMessage;
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
