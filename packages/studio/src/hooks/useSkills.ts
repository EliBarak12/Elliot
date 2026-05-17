import { useQuery } from "@tanstack/react-query";
import { callTool } from "@/lib/mcp-client";

interface SkillListEnvelope {
  skills?: unknown[];
  count?: number;
}

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
    // Live-refresh so skills the agent creates appear in the UI without a
    // page reload. 30s keeps backend load sane at scale; window-focus refetch
    // gives an immediate update when the user returns to the tab.
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });
}
