import React from "react";
import ReactDOM from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import Landing from "./pages/Landing";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <MemoryRouter>
      <Landing demoHref={null} />
    </MemoryRouter>
  </React.StrictMode>,
);
