import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Database,
  FileText,
  Globe,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useSources } from "@/hooks/useSources";
import { callTool } from "@/lib/mcp-client";
import { AddSourceDialog } from "@/components/sources/AddSourceDialog";

interface SourceSummary {
  id: string;
  source_id?: string;
  name: string;
  type: string;
  table_name?: string;
  table_count?: number;
  row_count?: number;
  last_fetched?: string;
  columns?: ColumnInfo[];
}

interface ColumnInfo {
  name: string;
  type: string;
}

function sourceIcon(type: string) {
  if (type === "rest") return Globe;
  if (type === "file") return FileText;
  return Database;
}

export default function SourcesPage() {
  const queryClient = useQueryClient();
  const { data: sourcesRaw, isLoading, isError, refetch } = useSources();
  const sources = Array.isArray(sourcesRaw) ? (sourcesRaw as SourceSummary[]) : [];

  const [dialogOpen, setDialogOpen] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const handleRefresh = async (sourceId: string) => {
    try {
      await callTool("elliot_refresh_source", { source_id: sourceId });
      await queryClient.invalidateQueries({ queryKey: ["sources"] });
      toast.success("Source refreshed");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Refresh failed");
    }
  };

  const handleRemove = async (sourceId: string) => {
    if (!confirm(`Remove source "${sourceId}"?`)) return;
    try {
      await callTool("studio_remove_source", { source_id: sourceId });
      await queryClient.invalidateQueries({ queryKey: ["sources"] });
      toast.success("Source removed");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Remove failed");
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Sources"
        description="Discover and manage the data sources your agents can query."
        actions={
          <Button onClick={() => setDialogOpen(true)} size="sm" className="gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            Add source
          </Button>
        }
      />

      {isLoading && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      )}

      {!isLoading && isError && (
        <EmptyState
          icon={AlertTriangle}
          title="Couldn't load sources"
          description="The Elliot MCP plugin didn't respond. Make sure the stack is running, then retry."
          action={
            <Button onClick={() => void refetch()} size="sm" variant="outline" className="gap-1.5">
              <RefreshCw className="h-3.5 w-3.5" />
              Retry
            </Button>
          }
        />
      )}

      {!isLoading && !isError && sources.length === 0 && (
        <EmptyState
          icon={Database}
          title="No sources yet"
          description="Connect a database, file, or API to start building tools that agents can call."
          action={
            <Button onClick={() => setDialogOpen(true)} size="sm" className="gap-1.5">
              <Plus className="h-3.5 w-3.5" />
              Add your first source
            </Button>
          }
        />
      )}

      <div className="space-y-3">
        {sources.map((source) => {
          const expanded = expandedId === source.id;
          const Icon = sourceIcon(source.type);
          return (
            <Card key={source.id} className="overflow-hidden">
              <button
                type="button"
                onClick={() => setExpandedId(expanded ? null : source.id)}
                className="flex w-full items-center gap-4 px-5 py-4 text-left hover:bg-muted/40 transition-colors"
              >
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary shrink-0">
                  <Icon className="h-4 w-4" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-semibold text-foreground truncate">
                      {source.name}
                    </span>
                    <Badge variant="muted" className="uppercase">
                      {source.type}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
                    {source.table_count !== undefined && (
                      <span className="tabular-nums">{source.table_count} tables</span>
                    )}
                    {source.row_count !== undefined && (
                      <span className="tabular-nums">
                        {source.row_count.toLocaleString()} rows
                      </span>
                    )}
                    {source.columns && (
                      <span className="tabular-nums">{source.columns.length} columns</span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <MoreHorizontal className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                      <DropdownMenuItem onClick={() => void handleRefresh(source.id)}>
                        <RefreshCw className="h-3.5 w-3.5" />
                        Refresh schema
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        onClick={() => void handleRemove(source.id)}
                        className="text-destructive focus:text-destructive [&_svg]:text-destructive"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Remove
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                  {expanded ? (
                    <ChevronDown className="h-4 w-4 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="h-4 w-4 text-muted-foreground" />
                  )}
                </div>
              </button>

              {expanded && source.columns && (
                <div className="border-t border-border/60 bg-muted/30 px-5 py-4 animate-fade-in-up">
                  <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-2">
                    Columns
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {source.columns.map((col) => (
                      <div
                        key={col.name}
                        className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2 py-1 text-2xs"
                      >
                        <span className="font-mono font-medium text-foreground">{col.name}</span>
                        <span className="text-muted-foreground">{col.type}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </Card>
          );
        })}
      </div>

      <AddSourceDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
    </div>
  );
}
