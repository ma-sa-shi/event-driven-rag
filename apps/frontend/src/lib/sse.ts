/** EventSourceはGET専用でヘッダーも付けられない為(ADR-0012)、fetchのbodyを自前で解析する。 */

export interface SseEvent {
  event: string;
  data: string;
}

function parseBlock(block: string): SseEvent | null {
  // event行が無い場合の既定値(SSEの仕様)
  let event = "message";
  const data: string[] = [];

  for (const line of block.split("\n")) {
    // ":"始まりはコメント行。KeepAliveの送信に使われる為、必ず読み飛ばす
    if (line === "" || line.startsWith(":")) continue;

    // ":"を含まない行はフィールド名だけの行として扱い、値は空文字にする(SSEの仕様)
    const separator = line.indexOf(":");
    let field = line;
    let value = "";

    if (separator !== -1) {
      field = line.slice(0, separator);
      value = line.slice(separator + 1).replace(/^ /, "");
    }

    if (field === "event") {
      event = value;
    } else if (field === "data") {
      data.push(value);
    }
    // id/retryは再接続用のフィールドで、このアプリでは再接続しない為使わない
  }

  // data行が1つも無いブロックはイベントとして成立しない
  if (data.length === 0) return null;
  return { event, data: data.join("\n") };
}

export async function* readSse(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      // マルチバイト文字がチャンク境界で分割されても壊れないようstreamモードで繋ぐ
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const event = parseBlock(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        if (event) yield event;
        boundary = buffer.indexOf("\n\n");
      }
    }
    // 空行で終わらないまま閉じた場合、末尾は不完全なイベントの為バッファごと捨てる
  } finally {
    // 既に閉じているstreamのcancelはrejectする為、握り潰す
    reader.cancel().catch(() => undefined);
  }
}
