import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useAuth } from "react-oidc-context";
import {
  completeUpload,
  createUploadUrl,
  fetchDownloadUrl,
  listDocuments,
  putToS3,
  startIngest,
} from "../api/documents";
import { DocumentTable } from "../components/DocumentTable";
import { UploadForm } from "../components/UploadForm";
import { toErrorMessage } from "../lib/errors";
import { ACCEPTED_EXTENSIONS, contentTypeFor } from "../lib/fileTypes";
import "./Documents.css";

const DOCUMENTS_QUERY_KEY = ["documents"];
// 取込はSQS経由の非同期処理の為、完了をポーリングで待つ
const POLL_INTERVAL_MS = 3000;

export function Documents() {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [openingId, setOpeningId] = useState<string | null>(null);

  const invalidateDocuments = () =>
    queryClient.invalidateQueries({ queryKey: DOCUMENTS_QUERY_KEY });

  const documentsQuery = useQuery({
    queryKey: DOCUMENTS_QUERY_KEY,
    queryFn: listDocuments,
    // 取込中の行があればキャッシュを定期的に更新する。
    refetchInterval: (query) =>
      query.state.data?.some((document) => document.status === "processing")
        ? POLL_INTERVAL_MS
        : false,
  });

  const uploadMutation = useMutation({
    mutationFn: async ({
      file,
      contentType,
    }: {
      file: File;
      contentType: string;
    }) => {
      const { documentId, uploadUrl } = await createUploadUrl(
        file.name,
        contentType,
      );
      await putToS3(uploadUrl, file, contentType);
      await completeUpload(documentId);
    },
    onSuccess: () => void invalidateDocuments(),
    onError: (e) => setError(toErrorMessage(e, "アップロードに失敗しました")),
  });

  const ingestMutation = useMutation({
    mutationFn: startIngest,
    onSuccess: () => void invalidateDocuments(),
    onError: (e) => {
      setError(toErrorMessage(e, "取込の開始に失敗しました"));
      // 他の操作と競合した場合に備え、最新のステータスを取り直す
      void invalidateDocuments();
    },
  });

  const handleUpload = async (file: File) => {
    setError(null);
    const contentType = contentTypeFor(file.name);
    if (!contentType) {
      // 非対応形式はS3へ送る前に弾き、uploadingのまま残るドキュメントを作らない
      setError(
        `対応していない形式です。${ACCEPTED_EXTENSIONS.join(" / ")}のいずれかを選択してください`,
      );
      return false;
    }
    try {
      await uploadMutation.mutateAsync({ file, contentType });
      return true;
    } catch {
      return false; // エラー表示はonErrorで行う
    }
  };

  const handleIngest = (documentId: string) => {
    setError(null);
    ingestMutation.mutate(documentId);
  };

  const handleOpen = async (documentId: string) => {
    setError(null);
    // await後のwindow.openはポップアップブロックの対象になる為、クリック直後に空タブを開く
    const tab = window.open("", "_blank");
    // 原本のContent-Type次第ではタブ内でスクリプトが動く為、開いた側への参照を切る
    if (tab) tab.opener = null;
    setOpeningId(documentId);
    try {
      const { downloadUrl } = await fetchDownloadUrl(documentId);
      if (tab) {
        tab.location.href = downloadUrl;
      } else {
        setError(
          "別タブを開けませんでした。ブラウザのポップアップ設定を確認してください",
        );
      }
    } catch (e) {
      tab?.close();
      setError(toErrorMessage(e, "原本の取得に失敗しました"));
    } finally {
      setOpeningId(null);
    }
  };

  return (
    <div className="documents">
      <h1 className="page-title">ドキュメント管理</h1>

      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}

      <UploadForm
        onUpload={handleUpload}
        isUploading={uploadMutation.isPending}
      />

      {documentsQuery.isPending && <p className="placeholder">読み込み中…</p>}

      {documentsQuery.isError && (
        <p className="placeholder">
          {toErrorMessage(documentsQuery.error, "一覧を取得できませんでした")}{" "}
          <button type="button" onClick={() => void documentsQuery.refetch()}>
            再試行
          </button>
        </p>
      )}

      {documentsQuery.data &&
        (documentsQuery.data.length === 0 ? (
          <p className="placeholder">ドキュメントはまだありません</p>
        ) : (
          <div className="table-scroll">
            <DocumentTable
              documents={documentsQuery.data}
              currentUserId={auth.user?.profile.sub}
              onOpen={(id) => void handleOpen(id)}
              onIngest={handleIngest}
              openingId={openingId}
              ingestingId={
                ingestMutation.isPending
                  ? (ingestMutation.variables ?? null)
                  : null
              }
            />
          </div>
        ))}
    </div>
  );
}
