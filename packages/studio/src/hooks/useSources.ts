import { useQuery } from "@tanstack/react-query";
import { callTool } from "@/lib/mcp-client";

interface SourceListEnvelope {
  sources?: unknown[];
  count?: number;
}

export function useSources() {
  return useQuery({
    queryKey: ["sources"],
    queryFn: async () => {
      const raw = (await callTool("elliot_list_sources", {})) as
        | SourceListEnvelope
        | unknown[];
      // The MCP tool returns { sources: [...], count: N }. Unwrap to a plain
      // array so consumers can do `sources.map(...)` without re-checking shape.
      if (Array.isArray(raw)) return raw;
      return Array.isArray(raw?.sources) ? raw.sources : [];
    },
    // Live-refresh so sources the agent discovers via MCP appear in the UI
    // without a page reload.
    refetchInterval: 4000,
    refetchOnWindowFocus: true,
  });
}
