import { useQuery, useMutation } from "@tanstack/react-query";
import { callTool, listTools } from "@/lib/mcp-client";

export function useTools() {
  return useQuery({
    queryKey: ["tools"],
    queryFn: listTools,
    // Auto-refresh so tools the agent registers via MCP appear without a
    // manual page reload. 4s is a good balance between latency-to-show
    // (agent does work, user sees it within seconds) and request load.
    refetchInterval: 4000,
    refetchOnWindowFocus: true,
  });
}

export function useCallTool() {
  return useMutation({
    mutationFn: ({ name, args }: { name: string; args: Record<string, unknown> }) =>
      callTool(name, args),
  });
}
