import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useSessionState } from "@/hooks/useSessionState";
import { callTool } from "@/lib/mcp-client";

interface SessionState {
  source_count: number;
  tool_count: number;
  skill_count: number;
  connector_built: boolean;
}

interface AuditEntry {
  ts: number;
  tool_id: string;
  result_row_count: number;
  duration_ms: number;
  error?: string;
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-2xl font-bold">{value}</p>
      </CardContent>
    </Card>
  );
}

export default function Dashboard() {
  const { data: sessionRaw } = useSessionState();
  const session = sessionRaw as SessionState | undefined;

  const { data: auditRaw } = useQuery({
    queryKey: ["audit"],
    queryFn: () => callTool("studio_get_audit_log", { limit: 10 }),
    refetchInterval: 10_000,
  });
  const auditEntries = Array.isArray(auditRaw) ? (auditRaw as AuditEntry[]) : [];

  const sourceCount = session?.source_count ?? 0;
  const toolCount = session?.tool_count ?? 0;
  const skillCount = session?.skill_count ?? 0;
  const connectorBuilt = session?.connector_built ?? false;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Sources" value={sourceCount} />
        <StatCard label="Tools" value={toolCount} />
        <StatCard label="Skills" value={skillCount} />
        <StatCard
          label="Connector"
          value={connectorBuilt ? "Built" : "Not built"}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Getting started</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <ChecklistItem done={sourceCount > 0} label="Add a source" href="/sources" />
          <ChecklistItem done={toolCount > 0} label="Create a tool" href="/tools" />
          <ChecklistItem done={connectorBuilt} label="Build connector" href="/connector" />
        </CardContent>
      </Card>

      <div className="flex gap-3">
        <Link to="/sources">
          <Button variant="outline" size="sm">
            Add Source
          </Button>
        </Link>
        <Link to="/tools">
          <Button variant="outline" size="sm">
            Create Tool
          </Button>
        </Link>
        <Link to="/connector">
          <Button variant="outline" size="sm">
            Build Connector
          </Button>
        </Link>
      </div>

      {auditEntries.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Recent activity</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-1 text-sm">
              {auditEntries.map((entry, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="font-mono text-xs text-muted-foreground">
                    {new Date(entry.ts * 1000).toLocaleTimeString()}
                  </span>
                  <span>{entry.tool_id}</span>
                  <span className="text-muted-foreground">{entry.result_row_count} rows</span>
                  {entry.error && <Badge variant="destructive">error</Badge>}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function ChecklistItem({ done, label, href }: { done: boolean; label: string; href: string }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className={done ? "text-green-500" : "text-muted-foreground"}>{done ? "✓" : "○"}</span>
      {done ? (
        <span className="line-through text-muted-foreground">{label}</span>
      ) : (
        <Link to={href} className="hover:underline">
          {label}
        </Link>
      )}
    </div>
  );
}
