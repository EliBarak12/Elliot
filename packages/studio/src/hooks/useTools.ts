import { useQuery, useMutation } from "@tanstack/react-query";
import { callTool, listTools } from "@/lib/mcp-client";

export function useTools() {
  return useQuery({
    queryKey: ["tools"],
    queryFn: listTools,
    // Auto-refresh so tools the agent registers via MCP appear without a
    // manual page reload. 30s keeps backend load sane at scale; window-focus
    // refetch gives an immediate update when the user returns to the tab.
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });
}

export function useCallTool() {
  return useMutation({
    mutationFn: ({ name, args }: { name: string; args: Record<string, unknown> }) =>
      callTool(name, args),
  });
}
