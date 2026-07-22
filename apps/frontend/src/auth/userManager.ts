import { UserManager, WebStorageStateStore } from "oidc-client-ts";

// AuthProviderとaxiosインターセプタで共有する唯一のUserManagerインスタンス。
// 設定の詳細はdocs/authorization.md参照
export const userManager = new UserManager({
  authority: import.meta.env.VITE_COGNITO_AUTHORITY,
  client_id: import.meta.env.VITE_COGNITO_CLIENT_ID,
  redirect_uri: `${window.location.origin}/auth/callback`,
  // profileは表示名(name)の取得に必要
  scope: "openid email profile",
  // リロードや複数タブでもセッションを維持するためlocalStorageに保存する
  userStore: new WebStorageStateStore({ store: window.localStorage }),
  // refresh tokenでaccess/id tokenを自動更新する
  automaticSilentRenew: true,
});

// localStorageのトークン破棄後に呼び、Hosted UIのセッションも破棄して"/"へ戻す
export function redirectToCognitoLogout(): void {
  const logoutUrl = new URL(`${import.meta.env.VITE_COGNITO_DOMAIN}/logout`);
  logoutUrl.searchParams.set(
    "client_id",
    import.meta.env.VITE_COGNITO_CLIENT_ID,
  );
  logoutUrl.searchParams.set("logout_uri", window.location.origin);
  window.location.assign(logoutUrl.toString());
}
