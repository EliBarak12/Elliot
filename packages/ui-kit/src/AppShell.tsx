import { useCallback, useEffect, useMemo, useState } from "react";
import {
  useApp,
  useHostStyles,
  type App,
  type McpUiHostContext,
} from "@modelcontextprotocol/ext-apps/react";
import type { ElliotBranding, ElliotUiConfig } from "./lib/config";
import { parseToolResult, resolveAutoPreset, type ToolData } from "./lib/data";
import { DetailPreset } from "./presets/detail";
import { MarkdownPreset } from "./presets/markdown";
import { MetricPreset } from "./presets/metric";
import { TablePreset } from "./presets/table";

export interface PresetProps {
  config: ElliotUiConfig;
  data: ToolData;
  app: App | null;
  /** Tell the model what the user picked/did inside the view. */
  onContext: (text: string, structured?: Record<string, unknown>) => void;
}

function applyTheme(ctx: McpUiHostContext | undefined, branding?: ElliotBranding | null) {
  const theme = ctx?.theme;
  if (theme === "dark" || theme === "light") {
    document.documentElement.setAttribute("data-theme", theme);
  }
  // The brand accent outranks the host's accent (it IS the product's
  // identity) while text/background stay host-themed for legibility. Inline
  // root style wins over both the stylesheet fallbacks and host variables.
  const accent =
    theme === "dark"
      ? (branding?.accent_dark ?? branding?.accent)
      : branding?.accent;
  if (accent) {
    document.documentElement.style.setProperty("--primary", accent);
  }
}

export function AppShell({ config }: { config: ElliotUiConfig }) {
  const [data, setData] = useState<ToolData | null>(null);
  const [toolInput, setToolInput] = useState<Record<string, unknown> | null>(null);
  const [cancelled, setCancelled] = useState<string | null>(null);

  const { app } = useApp({
    appInfo: { name: `elliot-ui:${config.tool_id}`, version: "1.0.0" },
    capabilities: {},
    autoResize: true,
    onAppCreated: (created) => {
      created.ontoolinput = (params) => {
        setToolInput((params.arguments as Record<string, unknown> | undefined) ?? {});
      };
      created.ontoolresult = (params) => {
        setCancelled(null);
        setData(parseToolResult(params));
      };
      created.ontoolcancelled = (params) => {
        setCancelled(typeof params?.reason === "string" ? params.reason : "cancelled");
      };
      created.onhostcontextchanged = (params) => {
        applyTheme(params as McpUiHostContext, config.branding);
      };
    },
  });

  useHostStyles(app);
  useEffect(() => {
    applyTheme(app?.getHostContext(), config.branding);
  }, [app, config.branding]);

  const onContext = useCallback(
    (text: string, structured?: Record<string, unknown>) => {
      if (!app) return;
      void app
        .updateModelContext({
          content: [{ type: "text", text }],
          ...(structured ? { structuredContent: structured } : {}),
        })
        .catch((err: unknown) => console.warn("[ui-kit] updateModelContext failed", err));
    },
    [app]
  );

  const preset = useMemo(() => {
    if (!data) return null;
    return config.preset === "auto" ? resolveAutoPreset(data) : config.preset;
  }, [config.preset, data]);

  if (cancelled) {
    return (
      <Frame title={config.title} logo={config.branding?.logo}>
        <p className="text-sm text-muted-foreground p-4">Tool call cancelled: {cancelled}</p>
      </Frame>
    );
  }

  if (!data) {
    return (
      <Frame title={config.title} logo={config.branding?.logo}>
        <div className="p-4 space-y-2" aria-label="Waiting for tool result">
          <div className="h-3.5 w-2/3 rounded bg-muted animate-pulse" />
          <div className="h-3.5 w-1/2 rounded bg-muted animate-pulse" />
          <div className="h-3.5 w-3/5 rounded bg-muted animate-pulse" />
        </div>
      </Frame>
    );
  }

  const shared: PresetProps = { config, data, app, onContext };
  let body: React.ReactNode;
  switch (preset) {
    case "detail":
      body = <DetailPreset {...shared} />;
      break;
    case "metric":
      body = <MetricPreset {...shared} />;
      break;
    case "markdown":
      body = <MarkdownPreset {...shared} />;
      break;
    case "table":
    default:
      body = <TablePreset {...shared} />;
      break;
  }

  return (
    <Frame title={config.title} toolInput={toolInput} logo={config.branding?.logo}>
      {body}
      {data.truncated && data.truncationNote && (
        <p className="px-4 pb-3 text-2xs text-warning">{data.truncationNote}</p>
      )}
    </Frame>
  );
}

function Frame({
  title,
  toolInput,
  logo,
  children,
}: {
  title: string;
  toolInput?: Record<string, unknown> | null;
  logo?: string | null;
  children: React.ReactNode;
}) {
  const inputSummary =
    toolInput && Object.keys(toolInput).length > 0
      ? Object.entries(toolInput)
          .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
          .join("  ")
      : null;
  return (
    <div className="min-h-full bg-background text-foreground">
      <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
        <span className="flex items-center gap-2 min-w-0">
          {logo && (
            <img
              src={logo}
              alt=""
              className="h-5 w-auto max-w-[7rem] shrink-0 rounded-sm object-contain"
            />
          )}
          <h1 className="text-sm font-semibold truncate">{title}</h1>
        </span>
        {inputSummary && (
          <span className="font-mono text-2xs text-muted-foreground truncate" title={inputSummary}>
            {inputSummary}
          </span>
        )}
      </header>
      {children}
    </div>
  );
}
