import { Route, Routes } from "react-router-dom";
import { RequireAuth } from "./auth/RequireAuth";
import { Layout } from "./components/Layout";
import { AuthCallback } from "./pages/AuthCallback";
import { Documents } from "./pages/Documents";
import { Home } from "./pages/Home";

function App() {
  return (
    <Routes>
      {/* 認証コールバック処理中は未認証状態のため、RequireAuth配下に置くとリダイレクトループが発生する */}
      <Route path="/auth/callback" element={<AuthCallback />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Home />} />
        <Route path="/documents" element={<Documents />} />
      </Route>
    </Routes>
  );
}

export default App;
