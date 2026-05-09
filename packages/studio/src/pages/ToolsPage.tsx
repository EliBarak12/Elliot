import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { useTools } from "@/hooks/useTools";
import { ToolCard } from "@/components/tools/ToolCard";
import { ToolEditor } from "@/components/tools/ToolEditor";
import type { ToolDefinition } from "@/types/api";

export default function ToolsPage() {
  const queryClient = useQueryClient();
  const { data: toolsRaw, isLoading } = useTools();
  const tools = Array.isArray(toolsRaw) ? (toolsRaw as ToolDefinition[]) : [];

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creatingNew, setCreatingNew] = useState(false);

  const selectedTool = tools.find((t) => t.id === selectedId) ?? null;

  const handleSaved = () => {
    void queryClient.invalidateQueries({ queryKey: ["tools"] });
    setCreatingNew(false);
  };

  return (
    <div className="flex gap-4 h-full">
      <div className="w-64 shrink-0 space-y-2 overflow-y-auto">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium">Tools ({tools.length})</span>
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs"
            onClick={() => {
              setSelectedId(null);
              setCreatingNew(true);
            }}
          >
            + New
          </Button>
        </div>

        {isLoading && <p className="text-xs text-muted-foreground">Loading…</p>}

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

      <div className="flex-1 border rounded-lg overflow-y-auto">
        {creatingNew || selectedTool ? (
          <ToolEditor tool={creatingNew ? null : selectedTool} onSaved={handleSaved} />
        ) : (
          <div className="flex items-center justify-center h-full text-sm text-muted-foreground">
            Select a tool or create a new one
          </div>
        )}
      </div>
    </div>
  );
}
