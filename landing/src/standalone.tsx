import React from "react";
import ReactDOM from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import Landing from "./pages/Landing";
import "./index.css";

// Set VITE_CHAT_URL (e.g. https://<backend>/chat) to make the CTAs open the chat.
const chatUrl = import.meta.env.VITE_CHAT_URL || null;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <MemoryRouter>
      <Landing demoHref={chatUrl} chatHref={chatUrl} />
    </MemoryRouter>
  </React.StrictMode>,
);
