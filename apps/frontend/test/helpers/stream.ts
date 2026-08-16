const encoder = new TextEncoder();

/** チャンクの区切りをそのまま再現するReadableStreamを作る。 */
export function streamOf(
  ...chunks: (string | Uint8Array)[]
): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(
          typeof chunk === "string" ? encoder.encode(chunk) : chunk,
        );
      }
      controller.close();
    },
  });
}

/** UTF-8のバイト列を指定位置で分割する。マルチバイト文字の途中で切る為に使う。 */
export function splitBytes(text: string, at: number): [Uint8Array, Uint8Array] {
  const bytes = encoder.encode(text);
  return [bytes.slice(0, at), bytes.slice(at)];
}
