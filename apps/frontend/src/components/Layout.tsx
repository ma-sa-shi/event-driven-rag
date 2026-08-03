import { useAuth } from "react-oidc-context";
import { NavLink, Outlet } from "react-router-dom";
import { redirectToCognitoLogout } from "../auth/userManager";
import "./Layout.css";

export function Layout() {
  const auth = useAuth();

  const handleSignOut = async () => {
    // localStorageのトークンを破棄してからHosted UIのセッションを破棄する
    await auth.removeUser();
    redirectToCognitoLogout();
  };

  return (
    <div className="layout">
      <header className="layout-header">
        <span className="layout-brand">Event Driven RAG</span>
        <nav className="layout-nav">
          <NavLink to="/" end>
            チャット
          </NavLink>
          <NavLink to="/documents">ドキュメント</NavLink>
        </nav>
        <div className="layout-user">
          <span>{auth.user?.profile.name}</span>
          <button type="button" onClick={() => void handleSignOut()}>
            サインアウト
          </button>
        </div>
      </header>
      <main className="layout-main">
        <Outlet />
      </main>
    </div>
  );
}
