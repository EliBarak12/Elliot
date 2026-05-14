import { useQuery, useMutation } from "@tanstack/react-query";
import { callTool, listTools } from "@/lib/mcp-client";

// Polled at ~3s so tools the *agent* creates over MCP (elliot_create_tool)
// show up in the Studio without the user having to refresh — Studio-side
// mutations still invalidate explicitly for an instant update.
const LIVE_REFETCH_MS = 3_000;

export function useTools() {
  return useQuery({
    queryKey: ["tools"],
    queryFn: listTools,
    refetchInterval: LIVE_REFETCH_MS,
    refetchOnWindowFocus: true,
  });
}

export function useCallTool() {
  return useMutation({
    mutationFn: ({ name, args }: { name: string; args: Record<string, unknown> }) =>
      callTool(name, args),
  });
}
