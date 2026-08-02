import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AppShell } from "./AppShell";
import { readConfig } from "./lib/config";
import "./styles.css";

const config = readConfig();
document.title = config.title;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppShell config={config} />
  </StrictMode>
);
