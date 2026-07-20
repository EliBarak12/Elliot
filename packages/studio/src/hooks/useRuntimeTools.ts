import { useMutation, useQuery } from "@tanstack/react-query";
import { callRuntimeTool, listRuntimeTools } from "@/lib/runtime-mcp";

/** Tools served by the connector runtime (:3001) — what agents actually see,
 * including the preloaded demo connector on a fresh install. */
export function useRuntimeTools() {
  return useQuery({
    queryKey: ["runtime-tools"],
    queryFn: listRuntimeTools,
    refetchOnWindowFocus: true,
    retry: 1,
  });
}

export function useCallRuntimeTool() {
  return useMutation({
    mutationFn: ({ name, args }: { name: string; args: Record<string, unknown> }) =>
      callRuntimeTool(name, args),
  });
}
