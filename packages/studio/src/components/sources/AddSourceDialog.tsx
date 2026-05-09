import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { callTool } from "@/lib/mcp-client";

type SourceType = "rest" | "file" | "postgres";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function AddSourceDialog({ open, onClose }: Props) {
  const queryClient = useQueryClient();
  const [sourceType, setSourceType] = useState<SourceType>("rest");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [path, setPath] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const config =
        sourceType === "rest"
          ? { url }
          : sourceType === "file"
            ? { path }
            : { url };
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
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-background rounded-lg border shadow-lg w-full max-w-md p-6">
        <h2 className="text-lg font-semibold mb-4">Add Source</h2>

        <div className="flex gap-2 mb-4">
          {(["rest", "file", "postgres"] as SourceType[]).map((t) => (
            <button key={t} onClick={() => setSourceType(t)} type="button">
              <Badge variant={sourceType === t ? "default" : "outline"} className="cursor-pointer">
                {t === "rest" ? "API" : t === "file" ? "File" : "DB"}
              </Badge>
            </button>
          ))}
        </div>

        <form onSubmit={(e) => void handleSubmit(e)} className="space-y-3">
          <Input
            placeholder="Source name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          {sourceType === "rest" && (
            <Input
              placeholder="https://api.example.com/data"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              required
            />
          )}
          {sourceType === "file" && (
            <Input
              placeholder="/path/to/file.csv"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              required
            />
          )}
          {sourceType === "postgres" && (
            <Input
              placeholder="postgresql://user:pass@host/db"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              required
            />
          )}

          {error && <p className="text-sm text-destructive">{error}</p>}

          <div className="flex gap-2 justify-end pt-2">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? "Adding…" : "Add Source"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
