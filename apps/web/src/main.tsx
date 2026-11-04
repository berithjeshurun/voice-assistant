import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { establishSession } from "./api";
import "./styles.css";

const render = () =>
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );

// Never block the first paint on the network for more than a moment.
Promise.race([establishSession(), new Promise((r) => setTimeout(r, 1500))]).finally(render);
