import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { streamChat } from "../../src/api/chats";
import type { ChatStreamEvent } from "../../src/api/chats";
import { streamOf } from "../helpers/stream";

// userManagerはimport時に実物のUserManagerを構築し、window.localStorageとVITE_COGNITO_*を触る
const getUser = vi.fn();
vi.mock("../../src/auth/userManager", () => ({
  userManager: { getUser: () => getUser() },
}));

const INTERRUPTED_MESSAGE =
  "回答の生成が中断されました。もう一度お試しください。";

function stubFetch(response: Response | Error) {
  const fetchMock = vi.fn<typeof fetch>(() => {
    if (response instanceof Error) return Promise.reject(response);
    return Promise.resolve(response);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function sseResponse(...chunks: string[]): Response {
  return new Response(streamOf(...chunks), { status: 200 });
}

function collector() {
  const events: ChatStreamEvent[] = [];
  return { events, onEvent: (event: ChatStreamEvent) => events.push(event) };
}

beforeEach(() => {
  getUser.mockResolvedValue({ access_token: "token-abc" });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("streamChat", () => {
  it("updateとdoneを届いた順にonEventへ渡し、doneで終了する", async () => {
    stubFetch(
      sseResponse(
        'event: update\ndata: {"node":"generate_queries_node","state":{"retry_count":0}}\n\n',
        'event: done\ndata: {"chatId":"chat-1","finalGrade":"useful","retryCount":0}\n\n',
      ),
    );
    const { events, onEvent } = collector();

    await streamChat("質問", onEvent, new AbortController().signal);

    expect(events).toEqual([
      {
        type: "update",
        node: "generate_queries_node",
        state: { retry_count: 0 },
      },
      {
        type: "done",
        chatId: "chat-1",
        finalGrade: "useful",
        retryCount: 0,
      },
    ]);
  });

  it("doneより後のイベントは読まない", async () => {
    stubFetch(
      sseResponse(
        'event: done\ndata: {"chatId":"chat-1","finalGrade":null,"retryCount":0}\n\n',
        'event: update\ndata: {"node":"generate_answer_node","state":{}}\n\n',
      ),
    );
    const { events, onEvent } = collector();

    await streamChat("質問", onEvent, new AbortController().signal);

    expect(events).toHaveLength(1);
  });

  it("アクセストークンがあればAuthorizationヘッダーを付ける", async () => {
    const fetchMock = stubFetch(
      sseResponse(
        'event: done\ndata: {"chatId":"c","finalGrade":null,"retryCount":0}\n\n',
      ),
    );
    const signal = new AbortController().signal;

    await streamChat("質問", collector().onEvent, signal);

    expect(fetchMock).toHaveBeenCalledWith("/api/chats/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        Authorization: "Bearer token-abc",
      },
      body: JSON.stringify({ question: "質問" }),
      signal,
    });
  });

  it("サインインしていなければAuthorizationヘッダーを付けない", async () => {
    getUser.mockResolvedValue(null);
    const fetchMock = stubFetch(
      sseResponse(
        'event: done\ndata: {"chatId":"c","finalGrade":null,"retryCount":0}\n\n',
      ),
    );

    await streamChat("質問", collector().onEvent, new AbortController().signal);

    const [, init] = fetchMock.mock.calls[0];
    expect(init?.headers).not.toHaveProperty("Authorization");
  });

  it("errorイベントでリクエストID付きのエラーをthrowする", async () => {
    stubFetch(
      sseResponse(
        'event: error\ndata: {"message":"生成に失敗しました","requestId":"req-1"}\n\n',
      ),
    );

    await expect(
      streamChat("質問", collector().onEvent, new AbortController().signal),
    ).rejects.toThrow("生成に失敗しました（リクエストID: req-1）");
  });

  it("401と403のレスポンスで認証切れの案内をthrowする", async () => {
    for (const status of [401, 403]) {
      stubFetch(new Response("", { status }));

      await expect(
        streamChat("質問", collector().onEvent, new AbortController().signal),
      ).rejects.toThrow(
        "認証の有効期限が切れた可能性があります。ページを再読み込みしてください。",
      );
    }
  });

  it("エラーレスポンスのdetailをメッセージへ含める", async () => {
    stubFetch(
      new Response(JSON.stringify({ detail: "質問が長すぎます" }), {
        status: 422,
      }),
    );

    await expect(
      streamChat("質問", collector().onEvent, new AbortController().signal),
    ).rejects.toThrow("回答の生成に失敗しました（質問が長すぎます）");
  });

  it("detailのないエラーレスポンスはステータスを添える", async () => {
    stubFetch(new Response("Internal Server Error", { status: 500 }));

    await expect(
      streamChat("質問", collector().onEvent, new AbortController().signal),
    ).rejects.toThrow("回答の生成に失敗しました（HTTP 500）");
  });

  it("doneが届かないままbodyが閉じたら中断のエラーをthrowする", async () => {
    stubFetch(
      sseResponse(
        'event: update\ndata: {"node":"generate_answer_node","state":{}}\n\n',
      ),
    );

    await expect(
      streamChat("質問", collector().onEvent, new AbortController().signal),
    ).rejects.toThrow(INTERRUPTED_MESSAGE);
  });

  it("bodyのないレスポンスも中断として扱う", async () => {
    stubFetch(new Response(null, { status: 200 }));

    await expect(
      streamChat("質問", collector().onEvent, new AbortController().signal),
    ).rejects.toThrow(INTERRUPTED_MESSAGE);
  });

  it("AbortErrorはそのまま投げ直す", async () => {
    const abortError = new Error("aborted");
    abortError.name = "AbortError";
    stubFetch(abortError);

    await expect(
      streamChat("質問", collector().onEvent, new AbortController().signal),
    ).rejects.toBe(abortError);
  });

  it("通信エラーは接続失敗の案内へ包み、原因を残す", async () => {
    const cause = new TypeError("Failed to fetch");
    stubFetch(cause);

    const promise = streamChat(
      "質問",
      collector().onEvent,
      new AbortController().signal,
    );

    await expect(promise).rejects.toThrow(
      "回答の生成に失敗しました（サーバーに接続できませんでした）",
    );
    await expect(promise).rejects.toHaveProperty("cause", cause);
  });

  it("未知のイベント名を読み飛ばす", async () => {
    stubFetch(
      sseResponse(
        "event: ping\ndata: {}\n\n",
        'event: done\ndata: {"chatId":"c","finalGrade":null,"retryCount":0}\n\n',
      ),
    );
    const { events, onEvent } = collector();

    await streamChat("質問", onEvent, new AbortController().signal);

    expect(events).toEqual([
      { type: "done", chatId: "c", finalGrade: null, retryCount: 0 },
    ]);
  });
});
