// Trace-hook controls for the Agent Console.
//
// MCP tool calls reach the console on their own, but the user's prompt, the
// model's reasoning and the final answer only arrive once the Elliot trace
// hook is installed into the local coding agent's config. These call the
// plugin's elliot_*_trace_hook MCP tools so the user can enable it from Studio.
import { useQuery, useMutation, type UseQueryResult } from "@tanstack/react-query";
import { callTool } from "@/lib/mcp-client";

export type Harness = "claude-code" | "codex" | "cursor";

export interface HarnessHookStatus {
  harness: Harness;
  installed: boolean;
  config_path: string;
}

export interface TraceHookStatus {
  runtime_url: string;
  harnesses: HarnessHookStatus[];
}

export const TRACE_HOOK_QUERY_KEY = ["trace-hook-status"] as const;

export function useTraceHookStatus(): UseQueryResult<TraceHookStatus> {
  return useQuery<TraceHookStatus>({
    queryKey: [...TRACE_HOOK_QUERY_KEY],
    queryFn: () => callTool("elliot_trace_hook_status", {}) as Promise<TraceHookStatus>,
    refetchInterval: 30_000,
  });
}

export function useToggleTraceHook() {
  return useMutation({
    mutationFn: ({ harness, install }: { harness: Harness; install: boolean }) =>
      callTool(install ? "elliot_install_trace_hook" : "elliot_uninstall_trace_hook", {
        harness,
      }),
  });
}
