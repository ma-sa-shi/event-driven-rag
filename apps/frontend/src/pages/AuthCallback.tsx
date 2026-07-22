import { useAuth } from "react-oidc-context";
import { Navigate } from "react-router-dom";

// Hosted UIからのリダイレクト先。認可コードのトークン交換は
// AuthProviderが自動処理するため、完了を待って"/"へ戻すだけでよい
export function AuthCallback() {
  const auth = useAuth();

  if (auth.isAuthenticated) {
    return <Navigate to="/" replace />;
  }
  if (auth.error) {
    return <p>認証エラーが発生しました: {auth.error.message}</p>;
  }
  return <p>サインインしています…</p>;
}
