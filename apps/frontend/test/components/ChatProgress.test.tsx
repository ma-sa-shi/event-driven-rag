import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { RetrievedDocument } from "../../src/api/chats";
import { ChatProgress } from "../../src/components/ChatProgress";
import type { Attempt } from "../../src/lib/chatProgress";

function retrieved(
  overrides: Partial<RetrievedDocument> = {},
): RetrievedDocument {
  return {
    documentId: "doc-1",
    filename: "manual.pdf",
    text: "本文",
    score: 0.825,
    ...overrides,
  };
}

/** 実行中として描画されているステップのラベル。 */
function runningLabels(container: HTMLElement): string[] {
  return [...container.querySelectorAll(".step-running .step-label")].map(
    (label) => label.textContent ?? "",
  );
}

describe("ChatProgress", () => {
  it("ストリーミング中は最後の試行の未完了ステップの先頭だけを実行中にする", () => {
    // SSEはノードの完了時にしか届かない為、回答生成は「走っているはず」の状態
    const attempts: Attempt[] = [
      { queries: ["q1"], documents: [retrieved()], answer: "1回目" },
      { queries: ["q2"], documents: [retrieved()] },
    ];

    const { container } = render(
      <ChatProgress attempts={attempts} isStreaming />,
    );

    expect(runningLabels(container)).toEqual(["Generation"]);
  });

  it("ストリーミングが終われば実行中のステップはなくなる", () => {
    const attempts: Attempt[] = [{ queries: ["q1"], documents: [retrieved()] }];

    const { container } = render(
      <ChatProgress attempts={attempts} isStreaming={false} />,
    );

    expect(runningLabels(container)).toEqual([]);
  });

  it("showAnswerBodyで回答の文字数表示と本文表示が切り替わる", () => {
    const attempts: Attempt[] = [{ answer: "12345" }];

    const { rerender } = render(
      <ChatProgress attempts={attempts} isStreaming={false} />,
    );
    expect(screen.getByText("回答を生成しました（5文字）")).toBeInTheDocument();

    rerender(
      <ChatProgress attempts={attempts} isStreaming={false} showAnswerBody />,
    );
    expect(screen.getByText("12345")).toBeInTheDocument();
    expect(screen.queryByText(/文字）/)).not.toBeInTheDocument();
  });

  it("documentIdのない断片は原本を開くボタンにしない", () => {
    const attempts: Attempt[] = [
      {
        documents: [
          retrieved({ filename: "traceable.pdf" }),
          retrieved({ documentId: null, filename: "orphan.pdf" }),
        ],
      },
    ];

    render(
      <ChatProgress
        attempts={attempts}
        isStreaming={false}
        onOpenDocument={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: "traceable.pdf" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "orphan.pdf" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("orphan.pdf")).toBeInTheDocument();
  });

  it("チャンク本文は120文字を超えると省略記号を付けて切り詰める", () => {
    const short = "短い本文";
    const long = "あ".repeat(130);
    const attempts: Attempt[] = [
      {
        documents: [
          retrieved({ filename: "short.pdf", text: short }),
          retrieved({ filename: "long.pdf", text: long }),
        ],
      },
    ];

    render(<ChatProgress attempts={attempts} isStreaming={false} />);

    expect(screen.getByText(short)).toBeInTheDocument();
    expect(screen.getByText(`${"あ".repeat(120)}…`)).toBeInTheDocument();
  });
});
