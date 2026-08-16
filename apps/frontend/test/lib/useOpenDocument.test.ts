import { act, renderHook } from "@testing-library/react";
import { AxiosError, AxiosHeaders } from "axios";
import type { AxiosResponse } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useOpenDocument } from "../../src/lib/useOpenDocument";

const fetchDownloadUrl = vi.fn();
vi.mock("../../src/api/documents", () => ({
  fetchDownloadUrl: (documentId: string) => fetchDownloadUrl(documentId),
}));

interface FakeTab {
  opener: unknown;
  location: { href: string };
  close: ReturnType<typeof vi.fn>;
}

function fakeTab(): FakeTab {
  return { opener: {}, location: { href: "" }, close: vi.fn() };
}

/** jsdomのwindow.openはnullを返し、location代入も未実装の為、差し替える。 */
function stubWindowOpen(tab: FakeTab | null) {
  const open = vi.fn(() => tab);
  vi.stubGlobal("open", open);
  return open;
}

beforeEach(() => {
  fetchDownloadUrl.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useOpenDocument", () => {
  it("空タブを先に開き、URL取得後に遷移させる", async () => {
    const tab = fakeTab();
    const open = stubWindowOpen(tab);
    let resolveUrl: (value: { downloadUrl: string }) => void = () => {};
    fetchDownloadUrl.mockReturnValue(
      new Promise((resolve) => {
        resolveUrl = resolve;
      }),
    );
    const { result } = renderHook(() => useOpenDocument(vi.fn()));

    let pending: Promise<void> = Promise.resolve();
    act(() => {
      pending = result.current.openDocument("doc-1");
    });

    // ポップアップブロックを避ける為、URL取得を待たずにタブを開く
    expect(open).toHaveBeenCalledWith("", "_blank");
    expect(tab.opener).toBeNull();
    expect(result.current.openingId).toBe("doc-1");

    await act(async () => {
      resolveUrl({ downloadUrl: "https://example.com/signed" });
      await pending;
    });

    expect(tab.location.href).toBe("https://example.com/signed");
    expect(result.current.openingId).toBeNull();
  });

  it("URL取得に失敗したらタブを閉じ、エラーメッセージを呼び出し側へ渡す", async () => {
    const tab = fakeTab();
    stubWindowOpen(tab);
    const config = { headers: new AxiosHeaders() };
    fetchDownloadUrl.mockRejectedValue(
      new AxiosError("not found", "ERR_BAD_REQUEST", config, {}, {
        status: 404,
        data: {},
        config,
      } as AxiosResponse),
    );
    const onError = vi.fn();
    const { result } = renderHook(() => useOpenDocument(onError));

    await act(async () => {
      await result.current.openDocument("doc-1");
    });

    expect(tab.close).toHaveBeenCalled();
    expect(onError).toHaveBeenCalledWith(
      "対象のドキュメントが見つかりません。一覧を再取得してください。",
    );
    expect(result.current.openingId).toBeNull();
  });

  it("window.openがnullを返した場合にポップアップ設定の案内を渡す", async () => {
    stubWindowOpen(null);
    fetchDownloadUrl.mockResolvedValue({
      downloadUrl: "https://example.com/signed",
    });
    const onError = vi.fn();
    const { result } = renderHook(() => useOpenDocument(onError));

    await act(async () => {
      await result.current.openDocument("doc-1");
    });

    expect(onError).toHaveBeenCalledWith(
      "別タブを開けませんでした。ブラウザのポップアップ設定を確認してください",
    );
  });
});
