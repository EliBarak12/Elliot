import { useState, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  Copy,
  Download,
  Info,
  Package,
  Play,
  ShieldCheck,
  X,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { Separator } from "@/components/ui/separator";
import { isExpectedNoConnector, redactConnectionConfig } from "@/lib/connection";
import { callTool } from "@/lib/mcp-client";
import { useTools } from "@/hooks/useTools";
import { useSkills } from "@/hooks/useSkills";
import { cn } from "@/lib/utils";
import type { ToolDefinition, SkillDefinition, ConnectorConfig } from "@/types/api";

interface LintIssue {
  code: string;
  severity: "ERROR" | "WARN" | "INFO";
  tool_id: string | null;
  message: string;
  suggestion: string;
}

interface ConnectionConfig {
  host: string;
  port: number;
  path: string;
}

interface RuntimeInfo {
  url?: string;
  running?: boolean;
  connection_config?: ConnectionConfig;
}

const SEVERITY_VARIANT: Record<LintIssue["severity"], "destructive" | "warning" | "muted"> = {
  ERROR: "destructive",
  WARN: "warning",
  INFO: "muted",
};

function LintPanel({ issues }: { issues: LintIssue[] }) {
  if (issues.length === 0) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-success/10 text-success">
        <CheckCircle2 className="h-4 w-4 shrink-0" />
        <span className="text-sm">No issues — connector looks good.</span>
      </div>
    );
  }
  return (
    <div className="divide-y divide-border/60">
      {issues.map((issue, i) => (
        <div key={i} className="flex items-start gap-3 py-2.5 first:pt-0 last:pb-0">
          <Badge variant={SEVERITY_VARIANT[issue.severity]} className="shrink-0 mt-0.5">
            {issue.severity}
          </Badge>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <p className="text-sm font-medium text-foreground">{issue.message}</p>
              {issue.tool_id && (
                <span className="font-mono text-2xs text-muted-foreground">{issue.tool_id}</span>
              )}
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">{issue.suggestion}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function ConnectorPage() {
  const queryClient = useQueryClient();
  const { data: toolsRaw, isError: toolsError, error: toolsErr } = useTools();
  const tools = Array.isArray(toolsRaw) ? (toolsRaw as ToolDefinition[]) : [];

  const { data: skillsRaw, isError: skillsError, error: skillsErr } = useSkills();
  const skills = Array.isArray(skillsRaw) ? (skillsRaw as SkillDefinition[]) : [];

  const [selectedToolIds, setSelectedToolIds] = useState<Set<string>>(new Set());
  const [selectedSkillIds, setSelectedSkillIds] = useState<Set<string>>(new Set());
  const [connectorName, setConnectorName] = useState("My Connector");
  const [connectorSlug, setConnectorSlug] = useState("my-connector");
  const [dirty, setDirty] = useState(false);
  const [builtConnector, setBuiltConnector] = useState<ConnectorConfig | null>(null);
  const [infoError, setInfoError] = useState<string | null>(null);

  // Load existing connector state from the session on mount
  useEffect(() => {
    void (async () => {
      try {
        const info = await callTool("studio_get_connector_info", {});
        const data = info as { connector?: ConnectorConfig };
        if (data.connector) {
          setConnectorName(data.connector.name);
          setConnectorSlug(data.connector.slug);
          setBuiltConnector(data.connector);
          // Seed the tool/skill selection from what's already bundled so the
          // checkboxes (and the "n / total" counters) reflect the built
          // connector instead of showing 0 selected after a reload.
          if (data.connector.tools) {
            setSelectedToolIds(new Set(data.connector.tools.map((t) => t.id)));
          }
          if (data.connector.skills) {
            setSelectedSkillIds(new Set(data.connector.skills.map((s) => s.id)));
          }
        }
      } catch (err) {
        // The plugin not being connected yet (or there being no connector
        // built yet) is expected on a fresh session — stay silent for that.
        // Surface anything else so a real failure isn't swallowed.
        const message = err instanceof Error ? err.message : String(err);
        if (isExpectedNoConnector(message)) return;
        console.error("[ConnectorPage] failed to load connector info", err);
        setInfoError(message);
      }
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [lintIssues, setLintIssues] = useState<LintIssue[]>([]);
  const [lintLoading, setLintLoading] = useState(false);
  const [linted, setLinted] = useState(false);
  const [runtimeInfo, setRuntimeInfo] = useState<RuntimeInfo | null>(null);
  const [copied, setCopied] = useState(false);
  const [status, setStatus] = useState<{ type: "ok" | "error"; message: string } | null>(null);

  const handleNameChange = (v: string) => {
    setConnectorName(v);
    setDirty(true);
  };
  const handleSlugChange = (v: string) => {
    setConnectorSlug(v);
    setDirty(true);
  };

  const toggleTool = (id: string) =>
    setSelectedToolIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      setDirty(true);
      return next;
    });

  const toggleSkill = (id: string) =>
    setSelectedSkillIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      setDirty(true);
      return next;
    });

  const handleBuild = async () => {
    setStatus(null);
    try {
      const buildRes = await callTool("elliot_build_connector", {
        name: connectorName,
        slug: connectorSlug,
        tool_ids: Array.from(selectedToolIds),
        skill_ids: Array.from(selectedSkillIds),
      });
      const br = buildRes as { status?: string; error?: string; tool_count?: number };
      if (br.error) {
        setStatus({ type: "error", message: br.error });
        return;
      }
      // Fetch the full connector config now that it's been built in the session
      const infoRes = await callTool("studio_get_connector_info", {});
      const info = infoRes as { connector?: ConnectorConfig };
      setBuiltConnector(info.connector ?? null);
      setDirty(false);
      setStatus({
        type: "ok",
        message: `Connector built · ${br.tool_count ?? 0} tools`,
      });
      void queryClient.invalidateQueries({ queryKey: ["session"] });
    } catch (err) {
      setStatus({ type: "error", message: err instanceof Error ? err.message : String(err) });
    }
  };

  const handleLint = async () => {
    setLintLoading(true);
    try {
      const res = await callTool("elliot_lint_connector", {});
      const data = res as { issues?: LintIssue[]; error?: string };
      if (data.error) {
        setStatus({ type: "error", message: data.error });
        setLintIssues([]);
      } else {
        setLintIssues(data.issues ?? []);
      }
      setLinted(true);
    } catch {
      setLintIssues([]);
    } finally {
      setLintLoading(false);
    }
  };

  const handleExport = async () => {
    try {
      await callTool("elliot_export_connector", { path: `${connectorSlug}.connector.json` });
      setStatus({ type: "ok", message: "Exported" });
    } catch (err) {
      setStatus({ type: "error", message: err instanceof Error ? err.message : String(err) });
    }
  };

  const handleStartRuntime = async () => {
    try {
      const res = await callTool("elliot_start_runtime", {});
      setRuntimeInfo(res as RuntimeInfo);
    } catch (err) {
      setStatus({ type: "error", message: err instanceof Error ? err.message : String(err) });
    }
  };

  const handleGetConnectionConfig = async () => {
    try {
      const res = await callTool("elliot_get_connection_config", {});
      setRuntimeInfo((prev) => ({ ...prev, connection_config: res as ConnectionConfig }));
    } catch (err) {
      setStatus({ type: "error", message: err instanceof Error ? err.message : String(err) });
    }
  };

  const handleCopy = async () => {
    if (!runtimeInfo?.connection_config) return;
    await navigator.clipboard.writeText(
      JSON.stringify(redactConnectionConfig(runtimeInfo.connection_config), null, 2)
    );
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const errorCount = lintIssues.filter((i) => i.severity === "ERROR").length;
  const warnCount = lintIssues.filter((i) => i.severity === "WARN").length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Connector"
        description="Bundle tools and skills into a connector, lint for quality, then start the runtime."
        actions={
          <div className="flex items-center gap-2">
            {dirty && (
              <Badge variant="warning" className="gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-warning animate-pulse" />
                Unsaved
              </Badge>
            )}
            <Button
              size="sm"
              variant="outline"
              onClick={() => void handleLint()}
              disabled={lintLoading}
              className="gap-1.5"
            >
              <ShieldCheck className="h-3.5 w-3.5" />
              {lintLoading ? "Linting…" : "Lint"}
            </Button>
            <Button size="sm" onClick={() => void handleBuild()} className="gap-1.5">
              <Package className="h-3.5 w-3.5" />
              Build connector
            </Button>
          </div>
        }
      />

      {infoError && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span className="flex-1">Failed to load connector info — {infoError}</span>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => setInfoError(null)}
            className="shrink-0 rounded p-0.5 opacity-70 hover:opacity-100 hover:bg-foreground/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-current"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {(toolsError || skillsError) && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span className="flex-1">
            {toolsError && skillsError
              ? "Failed to load tools and skills."
              : toolsError
                ? `Failed to load tools${toolsErr instanceof Error ? ` — ${toolsErr.message}` : ""}.`
                : `Failed to load skills${skillsErr instanceof Error ? ` — ${skillsErr.message}` : ""}.`}
          </span>
          <Button
            size="sm"
            variant="outline"
            className="h-7 shrink-0 text-xs"
            onClick={() => {
              if (toolsError) void queryClient.invalidateQueries({ queryKey: ["tools"] });
              if (skillsError) void queryClient.invalidateQueries({ queryKey: ["skills"] });
            }}
          >
            Retry
          </Button>
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Identity</CardTitle>
          <CardDescription>Name and slug for the bundled connector.</CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="connector-name">Name</Label>
            <Input
              id="connector-name"
              value={connectorName}
              onChange={(e) => handleNameChange(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="connector-slug">Slug</Label>
            <Input
              id="connector-slug"
              value={connectorSlug}
              onChange={(e) => handleSlugChange(e.target.value)}
              className="font-mono"
            />
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-2">
              <CardTitle>Tools</CardTitle>
              <Badge variant="muted">{selectedToolIds.size} / {tools.length}</Badge>
            </div>
          </CardHeader>
          <CardContent className="px-2 pb-2">
            <div className="max-h-80 overflow-y-auto scrollbar-thin">
              {tools.length === 0 && (
                <p className="text-xs text-muted-foreground px-3 py-4 text-center">
                  No tools available
                </p>
              )}
              {tools.map((tool) => {
                const checked = selectedToolIds.has(tool.id);
                return (
                  <label
                    key={tool.id}
                    className={cn(
                      "flex items-center gap-3 px-3 py-2 rounded-md cursor-pointer transition-colors",
                      "hover:bg-muted/40"
                    )}
                  >
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => toggleTool(tool.id)}
                    />
                    <span className="flex-1 text-sm truncate">{tool.name}</span>
                    <Badge variant="muted" className="shrink-0">
                      {tool.category}
                    </Badge>
                  </label>
                );
              })}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-2">
              <CardTitle>Skills</CardTitle>
              <Badge variant="muted">{selectedSkillIds.size} / {skills.length}</Badge>
            </div>
          </CardHeader>
          <CardContent className="px-2 pb-2">
            <div className="max-h-80 overflow-y-auto scrollbar-thin">
              {skills.length === 0 && (
                <p className="text-xs text-muted-foreground px-3 py-4 text-center">
                  No skills available
                </p>
              )}
              {skills.map((skill) => {
                const checked = selectedSkillIds.has(skill.id);
                return (
                  <label
                    key={skill.id}
                    className="flex items-center gap-3 px-3 py-2 rounded-md cursor-pointer transition-colors hover:bg-muted/40"
                  >
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => toggleSkill(skill.id)}
                    />
                    <span className="flex-1 text-sm truncate">{skill.name}</span>
                    <Badge variant="muted" className="shrink-0">
                      {skill.steps?.length ? `${skill.steps.length} steps` : 'prose'}
                    </Badge>
                  </label>
                );
              })}
            </div>
          </CardContent>
        </Card>
      </div>

      {status && (
        <div
          role={status.type === "error" ? "alert" : "status"}
          className={cn(
            "flex items-center gap-2 rounded-md border px-3 py-2 text-sm",
            status.type === "ok"
              ? "border-success/30 bg-success/10 text-success"
              : "border-destructive/30 bg-destructive/10 text-destructive"
          )}
        >
          {status.type === "ok" ? (
            <CheckCircle2 className="h-4 w-4 shrink-0" />
          ) : (
            <AlertCircle className="h-4 w-4 shrink-0" />
          )}
          <span className="flex-1">{status.message}</span>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => setStatus(null)}
            className="shrink-0 rounded p-0.5 opacity-70 hover:opacity-100 hover:bg-foreground/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-current"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {builtConnector && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-success" />
                  {builtConnector.name}
                </CardTitle>
                <CardDescription>
                  v{builtConnector.version} · {builtConnector.tools?.length ?? 0} tools ·{" "}
                  {builtConnector.skills?.length ?? 0} skills
                </CardDescription>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void handleExport()}
                  className="gap-1.5"
                >
                  <Download className="h-3.5 w-3.5" />
                  Export
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void handleStartRuntime()}
                  className="gap-1.5"
                >
                  <Play className="h-3.5 w-3.5" />
                  Start runtime
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void handleGetConnectionConfig()}
                  className="gap-1.5"
                >
                  <Info className="h-3.5 w-3.5" />
                  Connection config
                </Button>
              </div>
            </div>
          </CardHeader>

          {runtimeInfo?.url && (
            <CardContent>
              <Separator className="mb-4" />
              <div className="flex items-center gap-2 text-sm">
                <span
                  className={cn(
                    "h-2 w-2 rounded-full",
                    runtimeInfo.running ? "bg-success animate-pulse" : "bg-muted-foreground/50"
                  )}
                />
                <span className="text-muted-foreground">Runtime running at</span>
                <span className="font-mono text-foreground">{runtimeInfo.url}</span>
              </div>
            </CardContent>
          )}

          {runtimeInfo?.connection_config && (
            <CardContent>
              <Separator className="mb-4" />
              <div className="flex items-center justify-between mb-2">
                <Label>Connection config</Label>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 text-xs gap-1.5"
                  onClick={() => void handleCopy()}
                >
                  <Copy className="h-3.5 w-3.5" />
                  {copied ? "Copied" : "Copy"}
                </Button>
              </div>
              <pre className="text-xs bg-muted/60 border border-border rounded-lg p-3 overflow-x-auto font-mono">
                {JSON.stringify(redactConnectionConfig(runtimeInfo.connection_config), null, 2)}
              </pre>
            </CardContent>
          )}
        </Card>
      )}

      {linted && (
        <Card data-testid="lint-panel">
          <CardHeader>
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div className="flex items-center gap-2">
                <CardTitle>Lint</CardTitle>
                {errorCount > 0 && <Badge variant="destructive">{errorCount} errors</Badge>}
                {warnCount > 0 && <Badge variant="warning">{warnCount} warnings</Badge>}
                {errorCount === 0 && warnCount === 0 && (
                  <Badge variant="success">All clear</Badge>
                )}
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <LintPanel issues={lintIssues} />
          </CardContent>
        </Card>
      )}

      {!builtConnector && tools.length === 0 && (
        <EmptyState
          icon={Package}
          title="Nothing to bundle yet"
          description="Add a source and define at least one tool, then come back to build your connector."
        />
      )}
    </div>
  );
}
