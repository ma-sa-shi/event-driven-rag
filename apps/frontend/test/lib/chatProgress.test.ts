import { describe, expect, it } from "vitest";
import type { ChatAttempt, RetrievedDocument } from "../../src/api/chats";
import { applyUpdate, toAttempt } from "../../src/lib/chatProgress";
import type { Attempt } from "../../src/lib/chatProgress";

const DOCUMENT: RetrievedDocument = {
  documentId: "doc-1",
  filename: "manual.pdf",
  text: "本文",
  score: 0.8,
};

describe("applyUpdate", () => {
  it("generate_queries_nodeの到着で新しい試行が始まる", () => {
    const attempts = applyUpdate([], {
      node: "generate_queries_node",
      state: { retry_count: 0, queries: ["q1", "q2"] },
    });

    expect(attempts).toEqual([{ queries: ["q1", "q2"] }]);
  });

  it("リトライではretry_countより後ろの試行を破棄して作り直す", () => {
    // retry_countは試行の添字なので、それより後ろに積んだ分はすべて捨てる
    const attempts: Attempt[] = [
      { queries: ["q1"], answer: "1回目" },
      { queries: ["q2"], answer: "2回目" },
      { queries: ["q3"], answer: "3回目" },
    ];

    const next = applyUpdate(attempts, {
      node: "generate_queries_node",
      state: { retry_count: 1, queries: ["q2-new"] },
    });

    expect(next).toHaveLength(2);
    expect(next[0]).toEqual({ queries: ["q1"], answer: "1回目" });
    // 作り直した試行はqueriesだけを持ち、前回の回答は残らない
    expect(next[1]).toEqual({ queries: ["q2-new"] });
  });

  it("先頭ノードより先に他のノードが届いた場合は何も変えない", () => {
    const attempts: Attempt[] = [];

    const next = applyUpdate(attempts, {
      node: "generate_answer_node",
      state: { answer: "回答" },
    });

    expect(next).toBe(attempts);
  });

  it("各ノードの更新を最後の試行へマージする", () => {
    let attempts = applyUpdate([], {
      node: "generate_queries_node",
      state: { retry_count: 0, queries: ["q1"] },
    });
    attempts = applyUpdate(attempts, {
      node: "retrieve_contexts_node",
      state: { documents: [DOCUMENT] },
    });
    attempts = applyUpdate(attempts, {
      node: "generate_answer_node",
      state: { answer: "回答" },
    });
    attempts = applyUpdate(attempts, {
      node: "grade_answer_node",
      state: { grade: "useless", feedback: "根拠が不足しています" },
    });
    attempts = applyUpdate(attempts, {
      node: "analyze_failure_node",
      state: { failure_analysis: "検索クエリが広すぎます" },
    });

    expect(attempts).toEqual([
      {
        queries: ["q1"],
        documents: [DOCUMENT],
        answer: "回答",
        grade: "useless",
        feedback: "根拠が不足しています",
        failureAnalysis: "検索クエリが広すぎます",
      },
    ]);
  });

  it("検索結果が届かない場合は空配列を入れて完了扱いにする", () => {
    const attempts = applyUpdate([{ queries: ["q1"] }], {
      node: "retrieve_contexts_node",
      state: {},
    });

    expect(attempts[0].documents).toEqual([]);
  });

  it("元の配列を書き換えない", () => {
    const attempts: Attempt[] = [{ queries: ["q1"] }];

    applyUpdate(attempts, {
      node: "generate_answer_node",
      state: { answer: "回答" },
    });

    expect(attempts).toEqual([{ queries: ["q1"] }]);
  });
});

describe("toAttempt", () => {
  it("RESTのnullをundefinedへ落とす", () => {
    const stored: ChatAttempt = {
      attemptNo: 1,
      queries: ["q1"],
      documents: [DOCUMENT],
      answer: null,
      grade: null,
      feedback: null,
      failureAnalysis: null,
    };

    expect(toAttempt(stored)).toEqual({
      queries: ["q1"],
      documents: [DOCUMENT],
      answer: undefined,
      grade: undefined,
      feedback: undefined,
      failureAnalysis: undefined,
    });
  });

  it("空文字の回答はundefinedへ落とさない", () => {
    const stored: ChatAttempt = {
      attemptNo: 1,
      queries: [],
      documents: [],
      answer: "",
      grade: "useful",
      feedback: null,
      failureAnalysis: null,
    };

    expect(toAttempt(stored).answer).toBe("");
  });
});
