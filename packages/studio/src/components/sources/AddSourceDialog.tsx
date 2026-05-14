import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Database, FileText, Globe } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { callTool } from "@/lib/mcp-client";
import { cn } from "@/lib/utils";

type SourceType = "rest" | "file" | "postgres";

interface Props {
  open: boolean;
  onClose: () => void;
}

const SOURCE_OPTIONS: { value: SourceType; label: string; icon: typeof Database; hint: string }[] = [
  { value: "rest", label: "HTTP API", icon: Globe, hint: "REST or JSON endpoint" },
  { value: "file", label: "File", icon: FileText, hint: "CSV or JSON file on disk" },
  { value: "postgres", label: "Postgres", icon: Database, hint: "PostgreSQL connection string" },
];

export function AddSourceDialog({ open, onClose }: Props) {
  const queryClient = useQueryClient();
  const [sourceType, setSourceType] = useState<SourceType>("rest");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [path, setPath] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      // Reject inline credentials in postgres connection strings.
      // CLAUDE.md: "Secrets never in logs, never hardcoded — use
      // `{{ env:VAR }}` in connector files." A `:password@` pattern
      // would land verbatim in the saved connector and in any audit
      // log of this call.
      if (sourceType === "postgres" && /:[^@\s/]+@/.test(url)) {
        setError(
          "Inline credentials are not allowed. Use a {{ env:VAR }} placeholder " +
            "(e.g. postgresql://user:{{ env:DB_PASSWORD }}@host/db) so the secret " +
            "stays in your environment, not in the connector file."
        );
        setLoading(false);
        return;
      }
      const config =
        sourceType === "rest" ? { url } : sourceType === "file" ? { path } : { url };
      await callTool("elliot_discover_source", {
        source_type: sourceType,
        name,
        config,
      });
      await queryClient.invalidateQueries({ queryKey: ["sources"] });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add source");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Add a source</DialogTitle>
          <DialogDescription>
            Discover the schema of an API, file, or database to power agent tools.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
          <div className="space-y-1.5">
            <Label className="text-xs uppercase tracking-wider text-muted-foreground">
              Source type
            </Label>
            <div className="grid grid-cols-3 gap-2">
              {SOURCE_OPTIONS.map(({ value, label, icon: Icon, hint }) => {
                const active = sourceType === value;
                return (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setSourceType(value)}
                    className={cn(
                      "flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-all duration-200 ease-apple",
                      active
                        ? "border-primary bg-primary/5 shadow-sm ring-1 ring-primary/20"
                        : "border-input bg-card hover:bg-accent/50"
                    )}
                  >
                    <Icon
                      className={cn(
                        "h-4 w-4",
                        active ? "text-primary" : "text-muted-foreground"
                      )}
                    />
                    <span className="text-sm font-medium">{label}</span>
                    <span className="text-2xs text-muted-foreground">{hint}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="source-name">Name</Label>
            <Input
              id="source-name"
              placeholder="e.g. Production DB"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="source-target">
              {sourceType === "file" ? "Path" : sourceType === "postgres" ? "Connection string" : "URL"}
            </Label>
            {sourceType === "file" ? (
              <Input
                id="source-target"
                placeholder="/path/to/file.csv"
                value={path}
                onChange={(e) => setPath(e.target.value)}
                required
              />
            ) : (
              <Input
                id="source-target"
                placeholder={
                  sourceType === "rest"
                    ? "https://api.example.com/data"
                    : "postgresql://user:pass@host/db"
                }
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                required
              />
            )}
          </div>

          {error && (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {error}
            </div>
          )}

          <DialogFooter className="pt-2">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={loading || !name.trim()}>
              {loading ? "Discovering…" : "Add source"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
