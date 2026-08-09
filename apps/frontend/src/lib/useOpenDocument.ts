import { useState } from "react";
import { fetchDownloadUrl } from "../api/documents";
import { toErrorMessage } from "./errors";

/** 原本を別タブで開く。失敗の表示先はページごとに違う為、メッセージは呼び出し側へ渡す。 */
export function useOpenDocument(onError: (message: string) => void) {
  const [openingId, setOpeningId] = useState<string | null>(null);

  const openDocument = async (documentId: string) => {
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
        onError(
          "別タブを開けませんでした。ブラウザのポップアップ設定を確認してください",
        );
      }
    } catch (e) {
      tab?.close();
      onError(toErrorMessage(e, "原本の取得に失敗しました"));
    } finally {
      setOpeningId(null);
    }
  };

  return { openDocument, openingId };
}
