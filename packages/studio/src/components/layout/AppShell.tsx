import { Outlet } from "@tanstack/react-router";
import { Toaster } from "sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Sidebar } from "./Sidebar";
import { Header } from "./Header";

export function AppShell() {
  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex h-screen overflow-hidden bg-background text-foreground antialiased">
        <Sidebar />
        <div className="flex flex-col flex-1 overflow-hidden bg-muted/40">
          <Header />
          <main className="flex-1 overflow-y-auto scrollbar-thin">
            <div className="mx-auto max-w-7xl px-8 py-8 animate-fade-in">
              <Outlet />
            </div>
          </main>
        </div>
        <Toaster
          position="bottom-right"
          richColors
          closeButton
          toastOptions={{
            classNames: {
              toast: "rounded-xl border border-border/70 shadow-lg",
            },
          }}
        />
      </div>
    </TooltipProvider>
  );
}
