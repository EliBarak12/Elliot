import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { callTool } from "@/lib/mcp-client";
import { useTools } from "@/hooks/useTools";
import type { ToolDefinition, SkillDefinition, ConnectorConfig } from "@/types/api";

interface LintIssue {
  code: string;
  severity: "ERROR" | "WARN" | "INFO";
  tool_id: string | null;
  message: string;
  suggestion: string;
}

function LintPanel({ issues }: { issues: LintIssue[] }) {
  if (issues.length === 0) {
    return (
      <p className="text-xs text-green-700 px-1">No issues — connector looks good.</p>
    );
  }
  return (
    <div className="space-y-1">
      {issues.map((issue, i) => (
        <div key={i} className="flex items-start gap-2 text-xs py-1 border-b last:border-0">
          <Badge
            variant={issue.severity === "ERROR" ? "destructive" : "outline"}
            className="text-xs shrink-0 mt-0.5"
          >
            {issue.severity}
          </Badge>
          {issue.tool_id && (
            <span className="font-mono text-muted-foreground shrink-0">{issue.tool_id}</span>
          )}
          <div>
            <p className="font-medium">{issue.message}</p>
            <p className="text-muted-foreground">{issue.suggestion}</p>
          </div>
        </div>
      ))}
    </div>
  );
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

export default function ConnectorPage() {
  const queryClient = useQueryClient();
  const { data: toolsRaw } = useTools();
  const tools = Array.isArray(toolsRaw) ? (toolsRaw as ToolDefinition[]) : [];

  const { data: skillsRaw } = useQuery({
    queryKey: ["skills"],
    queryFn: () => callTool("elliot_list_skills", {}),
  });
  const skills = (skillsRaw as { skills?: SkillDefinition[] } | undefined)?.skills ?? [];

  const [selectedToolIds, setSelectedToolIds] = useState<Set<string>>(new Set());
  const [selectedSkillIds, setSelectedSkillIds] = useState<Set<string>>(new Set());
  const [connectorName, setConnectorName] = useState("My Connector");
  const [connectorSlug, setConnectorSlug] = useState("my-connector");
  const [dirty, setDirty] = useState(false);
  const [builtConnector, setBuiltConnector] = useState<ConnectorConfig | null>(null);

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
        }
      } catch {
        // Plugin not yet connected — silently ignore
      }
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [lintIssues, setLintIssues] = useState<LintIssue[]>([]);
  const [lintLoading, setLintLoading] = useState(false);
  const [runtimeInfo, setRuntimeInfo] = useState<RuntimeInfo | null>(null);
  const [copied, setCopied] = useState(false);
  const [status, setStatus] = useState<{ type: "ok" | "error"; message: string } | null>(null);

  const handleNameChange = (v: string) => { setConnectorName(v); setDirty(true); };
  const handleSlugChange = (v: string) => { setConnectorSlug(v); setDirty(true); };

  const toggleTool = (id: string) =>
    setSelectedToolIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const toggleSkill = (id: string) =>
    setSelectedSkillIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
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
      setStatus({ type: "ok", message: `Connector built ✓ (${br.tool_count ?? 0} tools)` });
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
    } catch {
      setLintIssues([]);
    } finally {
      setLintLoading(false);
    }
  };

  const handleExport = async () => {
    try {
      await callTool("elliot_export_connector", { path: `${connectorSlug}.connector.json` });
      setStatus({ type: "ok", message: "Exported ✓" });
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
    await navigator.clipboard.writeText(JSON.stringify(runtimeInfo.connection_config, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">
          Connector
          {dirty && (
            <Badge variant="outline" className="ml-2 text-xs text-yellow-700 border-yellow-400">
              Unsaved
            </Badge>
          )}
        </h2>
        <Button size="sm" variant="outline" onClick={() => void handleLint()} disabled={lintLoading}>
          {lintLoading ? "Linting…" : "Lint"}
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-xs font-medium text-muted-foreground">Connector name</label>
          <Input
            value={connectorName}
            onChange={(e) => handleNameChange(e.target.value)}
            className="mt-1 h-8 text-sm"
          />
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground">Slug</label>
          <Input
            value={connectorSlug}
            onChange={(e) => handleSlugChange(e.target.value)}
            className="mt-1 h-8 text-sm"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Tools</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {tools.map((tool) => (
              <label key={tool.id} className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={selectedToolIds.has(tool.id)}
                  onChange={() => toggleTool(tool.id)}
                />
                <span className="truncate">{tool.name}</span>
                <Badge variant="outline" className="text-xs ml-auto">
                  {tool.category}
                </Badge>
              </label>
            ))}
            {tools.length === 0 && (
              <p className="text-xs text-muted-foreground">No tools available</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Skills</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {skills.map((skill) => (
              <label key={skill.id} className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={selectedSkillIds.has(skill.id)}
                  onChange={() => toggleSkill(skill.id)}
                />
                <span className="truncate">{skill.name}</span>
              </label>
            ))}
            {skills.length === 0 && (
              <p className="text-xs text-muted-foreground">No skills available</p>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="flex gap-2">
        <Button onClick={() => void handleBuild()}>Build Connector</Button>
        {builtConnector && (
          <>
            <Button variant="outline" onClick={() => void handleExport()}>
              Export
            </Button>
            <Button variant="outline" onClick={() => void handleStartRuntime()}>
              Start Runtime
            </Button>
            <Button variant="outline" onClick={() => void handleGetConnectionConfig()}>
              Connection Config
            </Button>
          </>
        )}
      </div>

      {status && (
        <div
          className={`text-xs px-3 py-2 rounded border ${
            status.type === "ok"
              ? "bg-green-50 border-green-200 text-green-800"
              : "bg-destructive/10 border-destructive/20 text-destructive"
          }`}
        >
          {status.message}
        </div>
      )}

      {builtConnector && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Built connector</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            <p>
              <span className="font-medium">Name:</span> {builtConnector.name}
            </p>
            <p>
              <span className="font-medium">Version:</span> {builtConnector.version}
            </p>
            <p>
              <span className="font-medium">Tools:</span> {builtConnector.tools?.length ?? 0}
            </p>
            <p>
              <span className="font-medium">Skills:</span> {builtConnector.skills?.length ?? 0}
            </p>
          </CardContent>
        </Card>
      )}

      {runtimeInfo?.connection_config && (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm">Connection config</CardTitle>
              <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => void handleCopy()}>
                {copied ? "Copied!" : "Copy"}
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <pre className="text-xs bg-muted rounded p-3 overflow-x-auto">
              {JSON.stringify(runtimeInfo.connection_config, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}

      {runtimeInfo?.url && (
        <p className="text-sm text-green-600">
          Runtime running at <span className="font-mono">{runtimeInfo.url}</span>
        </p>
      )}

      {lintIssues.length > 0 && (
        <Card data-testid="lint-panel">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              Lint
              <Badge variant={lintIssues.some(i => i.severity === "ERROR") ? "destructive" : "outline"} className="text-xs">
                {lintIssues.filter(i => i.severity === "ERROR").length} errors,{" "}
                {lintIssues.filter(i => i.severity === "WARN").length} warnings
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <LintPanel issues={lintIssues} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
