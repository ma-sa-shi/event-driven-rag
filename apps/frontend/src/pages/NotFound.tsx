import { Link } from "react-router-dom";

export function NotFound() {
  return (
    <div>
      <h1 className="page-title">ページが見つかりません</h1>
      <p className="placeholder">
        URLが正しいか確認してください。 <Link to="/">チャットへ戻る</Link>
      </p>
    </div>
  );
}
