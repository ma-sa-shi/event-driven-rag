import { describe, expect, it } from "vitest";
import { readSse } from "../../src/lib/sse";
import type { SseEvent } from "../../src/lib/sse";
import { splitBytes, streamOf } from "../helpers/stream";

async function collect(body: ReadableStream<Uint8Array>): Promise<SseEvent[]> {
  const events: SseEvent[] = [];
  for await (const event of readSse(body)) {
    events.push(event);
  }
  return events;
}

describe("readSse", () => {
  it("イベントがチャンク境界で分割されても復元する", async () => {
    const events = await collect(
      streamOf("event: upd", "ate\ndata: {", '"node":"a"}\n\n'),
    );

    expect(events).toEqual([{ event: "update", data: '{"node":"a"}' }]);
  });

  it("1チャンクに複数のイベントが入っていても分割する", async () => {
    const events = await collect(
      streamOf("event: update\ndata: 1\n\nevent: done\ndata: 2\n\n"),
    );

    expect(events).toEqual([
      { event: "update", data: "1" },
      { event: "done", data: "2" },
    ]);
  });

  it("マルチバイト文字がチャンク境界で分割されても壊れない", async () => {
    // 「あ」はUTF-8で3バイト。その2バイト目で切る
    const [head, tail] = splitBytes("data: あいうえお\n\n", 7);

    const events = await collect(streamOf(head, tail));

    expect(events).toEqual([{ event: "message", data: "あいうえお" }]);
  });

  it("コメント行を読み飛ばす", async () => {
    // KeepAliveはコメント行で送られる
    const events = await collect(
      streamOf(": keep-alive\n\n", "event: done\ndata: 1\n\n"),
    );

    expect(events).toEqual([{ event: "done", data: "1" }]);
  });

  it("event行がないブロックはmessageとして扱う", async () => {
    const events = await collect(streamOf("data: 1\n\n"));

    expect(events).toEqual([{ event: "message", data: "1" }]);
  });

  it("複数のdata行を改行で連結する", async () => {
    const events = await collect(
      streamOf("event: update\ndata: 1\ndata: 2\n\n"),
    );

    expect(events).toEqual([{ event: "update", data: "1\n2" }]);
  });

  it("data行のないブロックはイベントとして返さない", async () => {
    const events = await collect(streamOf("event: update\n\n", "data: 1\n\n"));

    expect(events).toEqual([{ event: "message", data: "1" }]);
  });

  it("空行で終わらないまま閉じた末尾の不完全なブロックを捨てる", async () => {
    const events = await collect(
      streamOf("event: update\ndata: 1\n\n", "event: done\ndata: 2"),
    );

    expect(events).toEqual([{ event: "update", data: "1" }]);
  });

  it("値の先頭の空白を1つだけ取り除く", async () => {
    const events = await collect(streamOf("data:  leading\n\n"));

    expect(events).toEqual([{ event: "message", data: " leading" }]);
  });

  it("最初のコロン以降をすべて値として扱う", async () => {
    const events = await collect(streamOf('data: {"a": 1}\n\n'));

    expect(events).toEqual([{ event: "message", data: '{"a": 1}' }]);
  });

  it("途中で読むのをやめたらstreamをキャンセルする", async () => {
    const body = streamOf("data: 1\n\n", "data: 2\n\n");
    const events = readSse(body);

    await events.next();
    await events.return(undefined);

    // readerを握ったままなら再取得は失敗する
    expect(body.locked).toBe(true);
    await expect(collect(body)).rejects.toThrow();
  });
});
