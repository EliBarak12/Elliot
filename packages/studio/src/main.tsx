import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { router } from "./router";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 10_000, retry: 1 } },
});

// Surface otherwise-silent promise rejections (failed fetches, async throws)
// so they show up in DevTools rather than vanishing.
window.addEventListener("unhandledrejection", (event) => {
  console.error("[main] unhandled promise rejection", event.reason);
});

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error("[main] #root element not found in index.html");
}

createRoot(rootEl).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>
);
