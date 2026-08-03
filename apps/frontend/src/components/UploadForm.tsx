import { useRef, useState } from "react";
import { ACCEPTED_EXTENSIONS } from "../lib/fileTypes";
import "./UploadForm.css";

interface UploadFormProps {
  /** アップロードを実行し、成功したらtrueを返す(失敗時のエラー表示は呼び出し側が行う) */
  onUpload: (file: File) => Promise<boolean>;
  isUploading: boolean;
}

export function UploadForm({ onUpload, isUploading }: UploadFormProps) {
  const [file, setFile] = useState<File | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!file) return;
    // 失敗時はやり直せるよう選択状態を残し、成功時だけクリアする
    if (await onUpload(file)) {
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <form className="upload-form" onSubmit={(e) => void handleSubmit(e)}>
      {/* input[type=file]のボタン文言はブラウザのUIで変更できない為、
          inputは視覚的に隠し(キーボード操作の為フォーカスは残す)、labelを見た目上のボタンにする */}
      <label className="file-picker">
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS.join(",")}
          disabled={isUploading}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <span className="file-picker-button">ファイルを選択</span>
        <span className="file-name">
          {file ? file.name : "ファイルが選択されていません"}
        </span>
      </label>
      <button type="submit" disabled={!file || isUploading}>
        {isUploading ? "アップロード中…" : "アップロード"}
      </button>
      <span className="upload-hint">
        対応形式: {ACCEPTED_EXTENSIONS.join(" / ")}
      </span>
    </form>
  );
}
