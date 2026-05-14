import { useQuery } from "@tanstack/react-query";
import { callTool } from "@/lib/mcp-client";

interface SourceListEnvelope {
  sources?: unknown[];
  count?: number;
}

// Poll so sources the agent discovers over MCP (elliot_discover_source) show
// up in the Studio without a manual refresh.
const LIVE_REFETCH_MS = 3_000;

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
    refetchInterval: LIVE_REFETCH_MS,
    refetchOnWindowFocus: true,
  });
}
