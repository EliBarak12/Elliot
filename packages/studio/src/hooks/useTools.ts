import { useQuery, useMutation } from "@tanstack/react-query";
import { callTool, listTools } from "@/lib/mcp-client";

export function useTools() {
  return useQuery({ queryKey: ["tools"], queryFn: listTools });
}

export function useCallTool() {
  return useMutation({
    mutationFn: ({ name, args }: { name: string; args: Record<string, unknown> }) =>
      callTool(name, args),
  });
}
