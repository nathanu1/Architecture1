import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./fonts.css";
import "./styles.css";
import { Gate } from "./tab/Gate";

// The tab build: the whole town (engine and model) runs in this page; the Gate is its front door.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Gate>
      <App />
    </Gate>
  </StrictMode>,
);
