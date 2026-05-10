import { useQuery } from "@tanstack/react-query";
import { callTool } from "@/lib/mcp-client";

export function useMetrics(days = 30) {
  return useQuery({
    queryKey: ["metrics", days],
    queryFn: () => callTool("studio_get_metrics", { days }),
    refetchInterval: 30_000,
  });
}
