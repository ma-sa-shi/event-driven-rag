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

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthProvider userManager={userManager} onSigninCallback={onSigninCallback}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </AuthProvider>
  </StrictMode>,
);
