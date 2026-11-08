import { useCallback, useEffect, useMemo, useState } from "react";
import {
  useApp,
  useHostStyles,
  type App,
  type McpUiHostContext,
} from "@modelcontextprotocol/ext-apps/react";
import { applyBrand } from "./lib/brand";
import type { ElliotBranding, ElliotUiConfig } from "./lib/config";
import { parseToolResult, resolveAutoPreset, type ToolData } from "./lib/data";
import { CardsPreset, looksLikeCards } from "./presets/cards";
import { ChartPreset } from "./presets/chart";
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
  const theme = ctx?.theme === "dark" || ctx?.theme === "light" ? ctx.theme : undefined;
  if (theme) document.documentElement.setAttribute("data-theme", theme);
  // The connector's design system: brand tokens outrank the host's (they ARE
  // the product's identity); anything the brand leaves unset keeps following
  // the host so the view stays legible in any client and theme.
  applyBrand(theme, branding);
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
    if (config.preset !== "auto") return config.preset;
    // A catalog (rows with an image and a title) reads best as cards.
    if (data.rows.length > 1 && looksLikeCards(data.rows)) return "cards";
    return resolveAutoPreset(data);
  }, [config.preset, data]);

  if (cancelled) {
    return (
      <Frame title={config.title} brand={config.branding}>
        <p className="text-sm text-muted-foreground p-4">Tool call cancelled: {cancelled}</p>
      </Frame>
    );
  }

  if (!data) {
    return (
      <Frame title={config.title} brand={config.branding}>
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
    case "cards":
      body = <CardsPreset {...shared} />;
      break;
    case "detail":
      body = <DetailPreset {...shared} />;
      break;
    case "metric":
      body = <MetricPreset {...shared} />;
      break;
    case "chart":
      body = <ChartPreset {...shared} />;
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
    <Frame title={config.title} toolInput={toolInput} brand={config.branding}>
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
  brand,
  children,
}: {
  title: string;
  toolInput?: Record<string, unknown> | null;
  brand?: ElliotBranding | null;
  children: React.ReactNode;
}) {
  const logo = brand?.logo;
  const name = brand?.name;
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
              alt={name ? "" : "Logo"}
              className="h-5 w-auto max-w-[7rem] shrink-0 rounded-sm object-contain"
            />
          )}
          {name && <span className="shrink-0 text-sm font-semibold">{name}</span>}
          {name && (
            <span aria-hidden className="h-3.5 w-px shrink-0 bg-border" />
          )}
          <h1 className={name ? "text-sm text-muted-foreground truncate" : "text-sm font-semibold truncate"}>
            {title}
          </h1>
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
