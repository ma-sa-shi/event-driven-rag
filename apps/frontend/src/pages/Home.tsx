import { useAuth } from "react-oidc-context";
import { redirectToCognitoLogout } from "../auth/userManager";

export function Home() {
  const auth = useAuth();

  const handleSignOut = async () => {
    // localStorageのトークンを破棄してからHosted UIのセッションを破棄する
    await auth.removeUser();
    redirectToCognitoLogout();
  };

  return (
    <>
      <header>
        <span>{auth.user?.profile.name}</span>
        <button onClick={() => void handleSignOut()}>サインアウト</button>
      </header>
      <h1>Event Driven RAG</h1>
    </>
  );
}
