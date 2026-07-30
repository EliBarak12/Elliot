import { useEffect, useRef, useState } from "react";
import { AppBridge, PostMessageTransport } from "@modelcontextprotocol/ext-apps/app-bridge";
import { callToolResult, type McpToolResult } from "@/lib/mcp-client";
import { Badge } from "@/components/ui/badge";

/** What the model would receive from a ui/update-model-context call. */
interface ContextUpdate {
  text: string;
  structured: Record<string, unknown> | null;
}

interface AppPreviewHostProps {
  /** The single-file HTML view (from elliot_preview_tool_ui). */
  html: string;
  toolId: string;
  /** The arguments the previewed call ran with (sent as tool-input). */
  args: Record<string, unknown>;
  /** The previewed tool result to play into the view. */
  result: McpToolResult | null;
}

/**
 * Studio's MCP Apps host: renders a tool's ui:// view in a sandboxed iframe
 * and speaks the ext-apps postMessage protocol to it — the same contract
 * Claude/ChatGPT implement, so what renders here is what agents' users see.
 * Nested tools/call from the view is proxied through elliot_preview_tool, and
 * ui/update-model-context is surfaced in a visible "context sent to the
 * model" strip instead of reaching a real model.
 */
export function AppPreviewHost({ html, toolId, args, result }: AppPreviewHostProps) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const bridgeRef = useRef<AppBridge | null>(null);
  const [height, setHeight] = useState(360);
  const [contextUpdates, setContextUpdates] = useState<ContextUpdate[]>([]);
  const [viewReady, setViewReady] = useState(false);

  // (Re)connect the bridge whenever the document or the played result changes.
  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    let cancelled = false;
    let bridge: AppBridge | null = null;

    const connect = () => {
      const target = iframe.contentWindow;
      if (!target || cancelled) return;
      const isDark = document.documentElement.classList.contains("dark");
      bridge = new AppBridge(
        null,
        { name: "elliot-studio", version: "0.1.0" },
        { openLinks: {} },
        {
          hostContext: {
            theme: isDark ? "dark" : "light",
            displayMode: "inline",
            platform: "web",
            containerDimensions: { maxHeight: 640 },
          },
        }
      );
      bridgeRef.current = bridge;

      bridge.oninitialized = () => {
        if (cancelled || !bridge) return;
        setViewReady(true);
        void bridge.sendToolInput({ arguments: args });
        if (result) {
          void bridge.sendToolResult({
            content: result.content as never,
            structuredContent: result.structuredContent ?? undefined,
          });
        }
      };
      bridge.addEventListener("sizechange", (event) => {
        const h = (event as unknown as { detail?: { height?: number } }).detail?.height;
        if (typeof h === "number" && h > 0) setHeight(Math.min(Math.max(h, 160), 640));
      });
      bridge.oncalltool = async (params) => {
        // The view refines by re-calling its own tool: route through the
        // builder's preview meta-tool so no runtime needs to be up.
        const previewed = await callToolResult("elliot_preview_tool", {
          tool_id: params.name,
          params: params.arguments ?? {},
        });
        const rows = (previewed.data as { rows?: unknown[] })?.rows ?? [];
        const structured = { rows, count: rows.length };
        return {
          content: [{ type: "text", text: JSON.stringify(structured) }],
          structuredContent: structured,
        } as never;
      };
      bridge.onupdatemodelcontext = async (params) => {
        const text =
          params.content
            ?.map((c) => ("text" in c && typeof c.text === "string" ? c.text : ""))
            .filter(Boolean)
            .join("\n") ?? "";
        setContextUpdates((prev) => [
          ...prev.slice(-4),
          { text, structured: (params.structuredContent as Record<string, unknown>) ?? null },
        ]);
        return {} as never;
      };
      bridge.onopenlink = async ({ url }) => {
        window.open(url, "_blank", "noopener,noreferrer");
        return {} as never;
      };
      bridge.onmessage = async (params) => {
        console.info("[app-preview] ui/message from view", params);
        return {} as never;
      };

      const transport = new PostMessageTransport(target, target);
      void bridge.connect(transport).catch((err: unknown) => {
        if (!cancelled) console.error("[app-preview] bridge connect failed", err);
      });
    };

    iframe.addEventListener("load", connect);
    return () => {
      cancelled = true;
      iframe.removeEventListener("load", connect);
      bridgeRef.current = null;
      void bridge?.close?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [html, result]);

  return (
    <div className="space-y-2" data-testid="app-preview-host">
      <div className="overflow-hidden rounded-lg border border-border bg-background">
        <iframe
          ref={iframeRef}
          title={`App view for ${toolId}`}
          sandbox="allow-scripts"
          srcDoc={html}
          style={{ width: "100%", height, border: "0", display: "block" }}
        />
      </div>
      <div className="flex items-center gap-2">
        <Badge variant={viewReady ? "success" : "outline"} className="text-2xs">
          {viewReady ? "view connected" : "loading view…"}
        </Badge>
        <span className="text-2xs text-muted-foreground">
          Sandboxed iframe · ext-apps postMessage bridge · what Claude renders for this tool
        </span>
      </div>
      {contextUpdates.length > 0 && (
        <div
          className="rounded-lg border border-border bg-muted/40 p-3 space-y-1"
          data-testid="model-context-panel"
        >
          <p className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground">
            Context the view sent to the model
          </p>
          {contextUpdates.map((update, i) => (
            <p key={i} className="text-xs font-mono break-words">
              {update.text}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Convenience wrapper: fetch the tool's built view via the
 * elliot_preview_tool_ui meta-tool (optionally with a DRAFT ui config) and
 * play a preview-run result into it. Used by the Playground's App view and
 * the Tool editor's UI tab.
 */
export function AppResultView({
  toolId,
  args,
  resultData,
  draftUi,
}: {
  toolId: string;
  args: Record<string, unknown>;
  /** The elliot_preview_tool payload ({rows, count, ...}) to render. */
  resultData: unknown;
  draftUi?: Record<string, unknown> | null;
}) {
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setHtml(null);
    setError(null);
    const fetchArgs: Record<string, unknown> = { tool_id: toolId };
    if (draftUi) fetchArgs.ui = draftUi;
    callToolResult("elliot_preview_tool_ui", fetchArgs)
      .then((res) => {
        if (cancelled) return;
        const body = res.data as { html?: string; error?: string };
        if (body.html) setHtml(body.html);
        else setError(body.error ?? "No view template returned.");
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [toolId, draftUi]);

  if (error) {
    return <p className="text-xs text-destructive p-2">Could not load the view: {error}</p>;
  }
  if (!html) {
    return <p className="text-xs text-muted-foreground p-2">Loading view…</p>;
  }
  const structured =
    typeof resultData === "object" && resultData !== null
      ? (resultData as Record<string, unknown>)
      : { rows: [], count: 0 };
  const played: McpToolResult = {
    data: resultData,
    content: [{ type: "text", text: JSON.stringify(structured) }],
    structuredContent: structured,
    meta: null,
    isError: false,
  };
  return <AppPreviewHost html={html} toolId={toolId} args={args} result={played} />;
}
