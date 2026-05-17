import { useQuery } from "@tanstack/react-query";
import { callTool } from "@/lib/mcp-client";

export function useSessionState() {
  return useQuery({
    queryKey: ["session"],
    queryFn: () => callTool("elliot_get_session_state", {}),
    // Session state changes slowly; 30s is plenty and avoids hammering the
    // backend with per-tab polling at scale.
    refetchInterval: 30_000,
  });
}
