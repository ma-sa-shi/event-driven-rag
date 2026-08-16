import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { UploadForm } from "../../src/components/UploadForm";

function pdf(name = "manual.pdf") {
  return new File(["本文"], name, { type: "application/pdf" });
}

function fileInput(): HTMLInputElement {
  return screen.getByLabelText(/ファイルを選択/) as HTMLInputElement;
}

describe("UploadForm", () => {
  it("選択したファイルをそのままonUploadへ渡す", async () => {
    const onUpload = vi.fn().mockResolvedValue(true);
    render(<UploadForm onUpload={onUpload} isUploading={false} />);
    const file = pdf();

    await userEvent.upload(fileInput(), file);
    await userEvent.click(screen.getByRole("button", { name: "アップロード" }));

    expect(onUpload).toHaveBeenCalledWith(file);
  });

  it("アップロード成功で選択状態がクリアされる", async () => {
    const onUpload = vi.fn().mockResolvedValue(true);
    render(<UploadForm onUpload={onUpload} isUploading={false} />);

    await userEvent.upload(fileInput(), pdf());
    expect(screen.getByText("manual.pdf")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "アップロード" }));

    expect(
      screen.getByText("ファイルが選択されていません"),
    ).toBeInTheDocument();
    expect(fileInput().value).toBe("");
  });

  it("アップロード失敗では選択状態が残る", async () => {
    const onUpload = vi.fn().mockResolvedValue(false);
    render(<UploadForm onUpload={onUpload} isUploading={false} />);

    await userEvent.upload(fileInput(), pdf());
    await userEvent.click(screen.getByRole("button", { name: "アップロード" }));

    // やり直せるよう選択は残す
    expect(screen.getByText("manual.pdf")).toBeInTheDocument();
    expect(fileInput().files).toHaveLength(1);
  });
});
