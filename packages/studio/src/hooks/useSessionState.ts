import { useQuery } from "@tanstack/react-query";
import { callTool } from "@/lib/mcp-client";

export function useSessionState() {
  return useQuery({
    queryKey: ["session"],
    queryFn: () => callTool("elliot_get_session_state", {}),
    refetchInterval: 5000,
  });
}
