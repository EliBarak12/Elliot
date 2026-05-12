import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { ToolDefinition } from "@/types/api";

const CATEGORY_VARIANT: Record<string, "default" | "warning" | "destructive" | "secondary"> = {
  READ: "default",
  WRITE: "warning",
  ACTION: "destructive",
  AGGREGATE: "secondary",
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
        "group w-full text-left rounded-lg border p-3 transition-all duration-200 ease-apple",
        selected
          ? "border-primary/40 bg-primary/5 shadow-sm ring-1 ring-primary/10"
          : "border-border bg-card hover:bg-muted/50 hover:border-border"
      )}
    >
      <div className="flex items-center gap-2 mb-1">
        <span
          className={cn(
            "font-medium text-sm truncate",
            selected ? "text-foreground" : "text-foreground"
          )}
        >
          {tool.name}
        </span>
        <Badge variant={CATEGORY_VARIANT[tool.category] ?? "muted"} className="ml-auto shrink-0">
          {tool.category}
        </Badge>
      </div>
      <p className="text-xs text-muted-foreground line-clamp-2 leading-snug">
        {tool.description || "No description"}
      </p>
    </button>
  );
}
