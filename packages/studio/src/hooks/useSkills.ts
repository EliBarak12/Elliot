import { useQuery } from "@tanstack/react-query";
import { callTool } from "@/lib/mcp-client";

interface SkillListEnvelope {
  skills?: unknown[];
  count?: number;
}

// Poll so skills the agent creates over MCP show up in the Studio live.
const LIVE_REFETCH_MS = 3_000;

export function useSkills() {
  return useQuery({
    queryKey: ["skills"],
    queryFn: async () => {
      const raw = (await callTool("elliot_list_skills", {})) as
        | SkillListEnvelope
        | unknown[];
      // elliot_list_skills returns { skills: [...], count: N }. Unwrap into a
      // plain array so consumers can do `skills.map(...)` directly.
      if (Array.isArray(raw)) return raw;
      return Array.isArray(raw?.skills) ? raw.skills : [];
    },
    refetchInterval: LIVE_REFETCH_MS,
    refetchOnWindowFocus: true,
  });
}
