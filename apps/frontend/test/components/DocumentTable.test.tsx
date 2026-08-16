import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { DocumentStatus, DocumentSummary } from "../../src/api/documents";
import { DocumentTable } from "../../src/components/DocumentTable";

const CURRENT_USER = "user-me";

function document(
  overrides: Partial<DocumentSummary> & { documentId: string },
): DocumentSummary {
  return {
    userId: CURRENT_USER,
    filename: `${overrides.documentId}.pdf`,
    status: "uploaded",
    createdAt: "2026-08-01T00:00:00Z",
    updatedAt: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

function renderTable(props: Partial<Parameters<typeof DocumentTable>[0]> = {}) {
  return render(
    <MemoryRouter>
      <DocumentTable
        documents={props.documents ?? []}
        currentUserId={CURRENT_USER}
        onOpen={vi.fn()}
        openingId={null}
        {...props}
      />
    </MemoryRouter>,
  );
}

function ingestButtonsByRow(): (HTMLElement | null)[] {
  return screen
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).queryByRole("button", { name: "取込開始" }));
}

describe("DocumentTable", () => {
  it("取込開始ボタンは自分のドキュメントかつuploaded / failedのときだけ表示する", () => {
    const statuses: DocumentStatus[] = [
      "uploading",
      "uploaded",
      "processing",
      "ingested",
      "failed",
    ];
    const documents = statuses.map((status) =>
      document({ documentId: status, status }),
    );
    documents.push(
      document({
        documentId: "others",
        userId: "user-other",
        status: "uploaded",
      }),
    );

    renderTable({ documents, onIngest: vi.fn() });

    expect(ingestButtonsByRow().map(Boolean)).toEqual([
      false, // uploading
      true, // uploaded
      false, // processing
      false, // ingested
      true, // failed
      false, // 他人のuploaded
    ]);
  });

  it("onIngestを渡さない場合は取込開始ボタンを表示しない", () => {
    renderTable({
      documents: [document({ documentId: "doc-1", status: "uploaded" })],
    });

    expect(
      screen.queryByRole("button", { name: "取込開始" }),
    ).not.toBeInTheDocument();
  });

  it("showOwnerのとき自分の行を「自分」、他人の行を「ユーザー」と表示する", () => {
    renderTable({
      documents: [
        document({ documentId: "mine" }),
        document({ documentId: "theirs", userId: "user-other" }),
      ],
      showOwner: true,
    });

    const [mine, theirs] = screen.getAllByRole("row").slice(1);
    expect(within(mine).getByRole("link")).toHaveTextContent("自分");
    expect(within(theirs).getByRole("link")).toHaveTextContent("ユーザー");
    expect(within(theirs).getByRole("link")).toHaveAttribute(
      "href",
      "/user/user-other",
    );
  });
});
