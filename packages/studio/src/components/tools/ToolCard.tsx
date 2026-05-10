import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { ToolDefinition } from "@/types/api";

const CATEGORY_STYLES: Record<string, string> = {
  READ: "bg-blue-100 text-blue-800 border-blue-200",
  WRITE: "bg-orange-100 text-orange-800 border-orange-200",
  ACTION: "bg-red-100 text-red-800 border-red-200",
  AGGREGATE: "bg-purple-100 text-purple-800 border-purple-200",
};

interface Props {
  tool: ToolDefinition;
  selected: boolean;
  onClick: () => void;
}

export function ToolCard({ tool, selected, onClick }: Props) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full text-left rounded-lg border p-3 transition-colors hover:bg-accent",
        selected && "bg-accent border-primary"
      )}
    >
      <div className="flex items-center gap-2 mb-1">
        <span className="font-medium text-sm truncate">{tool.name}</span>
        <Badge className={cn("text-xs border ml-auto shrink-0", CATEGORY_STYLES[tool.category])}>
          {tool.category}
        </Badge>
      </div>
      <p className="text-xs text-muted-foreground truncate">
        {tool.description.length > 80 ? tool.description.slice(0, 77) + "…" : tool.description}
      </p>
    </button>
  );
}
