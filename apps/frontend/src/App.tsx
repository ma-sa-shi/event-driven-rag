import { useEffect } from "react";
import { api } from "./api/client";

function App() {
  useEffect(() => {
    api.get("/health").then((res) => {
      console.log(res.data);
    });
  }, []);

  return <h1>Event Driven RAG</h1>;
}

export default App;
