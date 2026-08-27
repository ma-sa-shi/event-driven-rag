import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDeleteDocument } from "../../src/lib/useDeleteDocument";

const deleteDocument = vi.fn();
vi.mock("../../src/api/documents", () => ({
  deleteDocument: (documentId: string) => deleteDocument(documentId),
}));

function withQueryClient(queryClient: QueryClient) {
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
}

function renderDeleteHook(onError = vi.fn()) {
  const queryClient = new QueryClient();
  const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries");
  const { result } = renderHook(() => useDeleteDocument(onError), {
    wrapper: withQueryClient(queryClient),
  });
  return { result, invalidateQueries, onError };
}

beforeEach(() => {
  deleteDocument.mockReset();
  // jsdomのwindow.confirmは未実装で呼ぶと例外になる
  vi.stubGlobal(
    "confirm",
    vi.fn(() => true),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useDeleteDocument", () => {
  it("確認を取ってから削除し、ドキュメント一覧を再取得させる", async () => {
    deleteDocument.mockResolvedValue(undefined);
    const { result, invalidateQueries } = renderDeleteHook();

    act(() => result.current.removeDocument("doc-1"));

    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() => expect(invalidateQueries).toHaveBeenCalled());
    expect(deleteDocument).toHaveBeenCalledWith("doc-1");
    // 横断一覧とユーザー別一覧の双方が対象になる
    const { predicate } = invalidateQueries.mock.calls[0][0]!;
    expect(predicate!({ queryKey: ["documents"] } as never)).toBe(true);
    expect(
      predicate!({ queryKey: ["user", "u-1", "documents"] } as never),
    ).toBe(true);
    expect(predicate!({ queryKey: ["user", "u-1", "chats"] } as never)).toBe(
      false,
    );
  });

  it("確認をキャンセルした場合は削除しない", () => {
    vi.stubGlobal(
      "confirm",
      vi.fn(() => false),
    );
    const { result } = renderDeleteHook();

    act(() => result.current.removeDocument("doc-1"));

    expect(deleteDocument).not.toHaveBeenCalled();
  });

  it("削除中のIDを返し、失敗時はメッセージを呼び出し側へ渡す", async () => {
    let rejectDelete: (reason: unknown) => void = () => {};
    deleteDocument.mockReturnValue(
      new Promise((_, reject) => {
        rejectDelete = reject;
      }),
    );
    const { result, onError } = renderDeleteHook();

    act(() => result.current.removeDocument("doc-1"));

    await waitFor(() => expect(result.current.deletingId).toBe("doc-1"));

    await act(async () => {
      rejectDelete(new Error("failed"));
    });

    await waitFor(() => expect(result.current.deletingId).toBeNull());
    expect(onError).toHaveBeenCalledWith("ドキュメントの削除に失敗しました");
  });
});
