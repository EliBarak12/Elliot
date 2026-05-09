import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useSources } from "@/hooks/useSources";
import { callTool } from "@/lib/mcp-client";
import { AddSourceDialog } from "@/components/sources/AddSourceDialog";

interface SourceSummary {
  id: string;
  name: string;
  type: string;
  table_count?: number;
  row_count?: number;
  last_fetched?: string;
  columns?: ColumnInfo[];
}

interface ColumnInfo {
  name: string;
  type: string;
}

export default function SourcesPage() {
  const queryClient = useQueryClient();
  const { data: sourcesRaw, isLoading } = useSources();
  const sources = Array.isArray(sourcesRaw) ? (sourcesRaw as SourceSummary[]) : [];

  const [dialogOpen, setDialogOpen] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const handleRefresh = async (sourceId: string) => {
    await callTool("elliot_refresh_source", { source_id: sourceId });
    await queryClient.invalidateQueries({ queryKey: ["sources"] });
  };

  const handleRemove = async (sourceId: string) => {
    if (!confirm(`Remove source "${sourceId}"?`)) return;
    await callTool("elliot_remove_source", { source_id: sourceId });
    await queryClient.invalidateQueries({ queryKey: ["sources"] });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Sources</h2>
        <Button onClick={() => setDialogOpen(true)}>Add Source</Button>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}

      {sources.length === 0 && !isLoading && (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            No sources yet. Add a source to get started.
          </CardContent>
        </Card>
      )}

      {sources.map((source) => (
        <Card key={source.id}>
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <CardTitle className="text-base">{source.name}</CardTitle>
              <Badge variant="outline" className="text-xs">
                {source.type}
              </Badge>
              {source.table_count !== undefined && (
                <span className="text-xs text-muted-foreground">{source.table_count} tables</span>
              )}
              {source.row_count !== undefined && (
                <span className="text-xs text-muted-foreground">{source.row_count} rows</span>
              )}
              <div className="ml-auto flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setExpandedId(expandedId === source.id ? null : source.id)}
                >
                  {expandedId === source.id ? "Collapse" : "Expand"}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void handleRefresh(source.id)}
                >
                  Refresh
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => void handleRemove(source.id)}
                >
                  Remove
                </Button>
              </div>
            </div>
          </CardHeader>

          {expandedId === source.id && source.columns && (
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {source.columns.map((col) => (
                  <div key={col.name} className="flex items-center gap-1 text-xs">
                    <span>{col.name}</span>
                    <Badge variant="secondary">{col.type}</Badge>
                  </div>
                ))}
              </div>
            </CardContent>
          )}
        </Card>
      ))}

      <AddSourceDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
    </div>
  );
}
