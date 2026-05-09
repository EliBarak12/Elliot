import { useQuery } from "@tanstack/react-query";
import { callTool } from "@/lib/mcp-client";

export function useSources() {
  return useQuery({
    queryKey: ["sources"],
    queryFn: () => callTool("elliot_list_sources", {}),
  });
}
