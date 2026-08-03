/** アップロード可能なファイル形式の判定とContent-Typeの決定。
 *
 * 対応形式はバックエンドのテキスト抽出(app/ingest/extract.py)に合わせる。
 */

// input[type=file]のaccept属性にもそのまま渡す
export const ACCEPTED_EXTENSIONS = [".pdf", ".md", ".markdown", ".txt"];

const CONTENT_TYPES: Record<string, string> = {
  ".pdf": "application/pdf",
  // text/markdownはブラウザが表示せずダウンロードしてしまう為、原本閲覧のできるtext/plainで保存する。
  // バックエンドはContent-Typeではなく拡張子で形式を判定するので取込結果は変わらない
  ".md": "text/plain; charset=utf-8",
  ".markdown": "text/plain; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
};

function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot === -1 ? "" : filename.slice(dot).toLowerCase();
}

/** 対応形式ならContent-Typeを、非対応ならnullを返す。
 *
 * FileオブジェクトのtypeはMarkdownで空文字になるなどブラウザ依存の為、拡張子から決める。
 * 署名付きURLの発行時とPUT時で同じ値を使わないと署名が一致しない。
 */
export function contentTypeFor(filename: string): string | null {
  return CONTENT_TYPES[extensionOf(filename)] ?? null;
}
