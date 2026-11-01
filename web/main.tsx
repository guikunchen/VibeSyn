import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./app.tsx";
import "@xyflow/react/dist/style.css";
import "ketcher-react/dist/index.css";

createRoot(document.getElementById("root")!).render(
  <BrowserRouter>
    <App />
  </BrowserRouter>,
);
