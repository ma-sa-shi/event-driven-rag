import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AuthProvider } from "react-oidc-context";
import { BrowserRouter } from "react-router-dom";
import "./index.css";
import App from "./App.tsx";
import { userManager } from "./auth/userManager.ts";

// トークン交換後にURLへ残った認可コード(code/state)を履歴から取り除く
const onSigninCallback = () => {
  window.history.replaceState({}, document.title, window.location.pathname);
};

// アプリ全体で共有するキャッシュ。再生成するとキャッシュが失われる為モジュールスコープに置く
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 4xxを何度も投げ直さない
      retry: 1,
      staleTime: 30_000,
      // 別タブ→元タブに戻った時に自動で再フェッチしない
      refetchOnWindowFocus: false,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  // Provideで囲み、Contextをアプリ全体で利用可能にする
  <StrictMode>
    <AuthProvider userManager={userManager} onSigninCallback={onSigninCallback}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </AuthProvider>
  </StrictMode>,
);
