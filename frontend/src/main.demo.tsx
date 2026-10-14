import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./fonts.css";
import "./styles.css";

// The demo build uses self-hosted fonts and data from ./demo/*.json.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
