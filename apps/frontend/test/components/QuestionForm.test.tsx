import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { QuestionForm } from "../../src/components/QuestionForm";

function textarea(): HTMLTextAreaElement {
  return screen.getByLabelText("質問") as HTMLTextAreaElement;
}

function submitButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: "送信" }) as HTMLButtonElement;
}

describe("QuestionForm", () => {
  it("残り回数を表示する", () => {
    render(
      <QuestionForm
        onSubmit={vi.fn()}
        isStreaming={false}
        quota={{ limit: 20, used: 3 }}
      />,
    );

    expect(screen.getByText("残り 17 / 20 回")).toBeInTheDocument();
  });

  it("上限に達すると入力と送信を止め、理由を表示する", async () => {
    const onSubmit = vi.fn().mockResolvedValue(true);
    render(
      <QuestionForm
        onSubmit={onSubmit}
        isStreaming={false}
        quota={{ limit: 20, used: 20 }}
      />,
    );

    expect(screen.getByText("残り 0 / 20 回")).toBeInTheDocument();
    expect(
      screen.getByText(/本日の利用上限（20回）に達しました/),
    ).toBeInTheDocument();
    expect(textarea()).toBeDisabled();
    expect(submitButton()).toBeDisabled();

    await userEvent.click(submitButton());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("利用回数を取得できていない間も送信できる", async () => {
    const onSubmit = vi.fn().mockResolvedValue(true);
    render(<QuestionForm onSubmit={onSubmit} isStreaming={false} />);

    await userEvent.type(textarea(), "設計方針は?");
    await userEvent.click(submitButton());

    expect(onSubmit).toHaveBeenCalledWith("設計方針は?");
    expect(screen.queryByText(/残り/)).not.toBeInTheDocument();
  });

  it("残りがある場合は通常どおり送信できる", async () => {
    const onSubmit = vi.fn().mockResolvedValue(true);
    render(
      <QuestionForm
        onSubmit={onSubmit}
        isStreaming={false}
        quota={{ limit: 20, used: 19 }}
      />,
    );

    await userEvent.type(textarea(), "設計方針は?");
    await userEvent.click(submitButton());

    expect(onSubmit).toHaveBeenCalledWith("設計方針は?");
  });
});
