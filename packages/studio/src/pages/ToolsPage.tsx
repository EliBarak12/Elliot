import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Wrench } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { useTools } from "@/hooks/useTools";
import { ToolCard } from "@/components/tools/ToolCard";
import { ToolEditor } from "@/components/tools/ToolEditor";
import type { ToolDefinition } from "@/types/api";

export default function ToolsPage() {
  const queryClient = useQueryClient();
  const { data: toolsRaw, isLoading, isError, refetch } = useTools();
  const tools = Array.isArray(toolsRaw) ? (toolsRaw as ToolDefinition[]) : [];

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creatingNew, setCreatingNew] = useState(false);

  const selectedTool = tools.find((t) => t.id === selectedId) ?? null;

  const handleSaved = () => {
    void queryClient.invalidateQueries({ queryKey: ["tools"] });
    setCreatingNew(false);
    toast.success("Tool saved");
  };

  const startNew = () => {
    setSelectedId(null);
    setCreatingNew(true);
  };

  return (
    <div className="flex flex-col gap-6 h-full">
      <PageHeader
        title="Tools"
        description="Verb-first, typed contracts your agents can call. Design, validate, and test."
        actions={
          <Button size="sm" onClick={startNew} className="gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            New tool
          </Button>
        }
      />

      <div className="flex gap-4 flex-1 min-h-0">
        <div className="w-72 shrink-0 flex flex-col gap-2 overflow-hidden">
          <span className="px-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            {tools.length === 0 ? "Tools" : `Tools · ${tools.length}`}
          </span>

          <div className="flex-1 overflow-y-auto scrollbar-thin space-y-2 pr-1">
            {isLoading && (
              <>
                <Skeleton className="h-16 w-full" />
                <Skeleton className="h-16 w-full" />
                <Skeleton className="h-16 w-full" />
              </>
            )}

            {!isLoading && isError && (
              <Card className="p-4 text-center">
                <p className="text-xs text-muted-foreground mb-2">
                  Couldn&apos;t load tools — the Elliot MCP plugin didn&apos;t respond.
                </p>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void refetch()}
                  className="gap-1.5"
                >
                  Retry
                </Button>
              </Card>
            )}

            {!isLoading && !isError && tools.length === 0 && (
              <Card className="p-4 text-center">
                <p className="text-xs text-muted-foreground mb-2">No tools defined yet.</p>
                <Button size="sm" variant="outline" onClick={startNew} className="gap-1.5">
                  <Plus className="h-3.5 w-3.5" />
                  Create your first tool
                </Button>
              </Card>
            )}

            {tools.map((tool) => (
              <ToolCard
                key={tool.id}
                tool={tool}
                selected={tool.id === selectedId}
                onClick={() => {
                  setSelectedId(tool.id);
                  setCreatingNew(false);
                }}
              />
            ))}
          </div>
        </div>

        <Card className="flex-1 overflow-y-auto scrollbar-thin p-0">
          {creatingNew || selectedTool ? (
            <ToolEditor tool={creatingNew ? null : selectedTool} onSaved={handleSaved} />
          ) : (
            <div className="flex items-center justify-center h-full p-8">
              <EmptyState
                icon={Wrench}
                title="No tool selected"
                description="Pick a tool from the list, or create a new one to start designing an agent contract."
                action={
                  <Button size="sm" onClick={startNew} className="gap-1.5">
                    <Plus className="h-3.5 w-3.5" />
                    New tool
                  </Button>
                }
                className="border-0 bg-transparent"
              />
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
