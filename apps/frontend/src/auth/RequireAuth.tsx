import { useEffect, useRef, type ReactNode } from "react";
import { hasAuthParams, useAuth } from "react-oidc-context";
import { api } from "../api/client";

export function RequireAuth({ children }: { children: ReactNode }) {
  const auth = useAuth();
  // StrictModeの二重実行やstate更新による多重リダイレクト・多重送信を防ぐ
  const triedSignin = useRef(false);
  const syncedProfile = useRef(false);

  // 未認証ならHosted UIへリダイレクトする
  useEffect(() => {
    if (
      !hasAuthParams() &&
      !auth.isAuthenticated &&
      !auth.activeNavigator &&
      !auth.isLoading &&
      !triedSignin.current
    ) {
      triedSignin.current = true;
      void auth.signinRedirect();
    }
  }, [auth]);

  // サインイン時にIDトークンの表示名とメールをDynamoDBへ同期する(冪等)
  useEffect(() => {
    if (auth.isAuthenticated && auth.user && !syncedProfile.current) {
      syncedProfile.current = true;
      void api.post("/users/me", {
        displayName: auth.user.profile.name,
        email: auth.user.profile.email,
      });
    }
  }, [auth.isAuthenticated, auth.user]);

  if (auth.error) {
    return <p>認証エラーが発生しました: {auth.error.message}</p>;
  }
  if (!auth.isAuthenticated) {
    return <p>サインインしています…</p>;
  }
  return children;
}
