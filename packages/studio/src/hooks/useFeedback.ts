// Agent feedback feed for the Agent Console.
//
// Every running connector exposes a built-in `submit_feedback` tool the agent
// calls to report how a tool behaved. The connector runtime persists those
// reports and serves them at /v1/feedback.
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { httpJson } from "@/lib/http";

export type FeedbackOutcome = "success" | "failure" | "partial";

export interface AgentFeedback {
  id: number;
  session_id: string | null;
  ts: number;
  connector_slug: string | null;
  tool_id: string;
  outcome: FeedbackOutcome;
  why_chosen: string | null;
  input_summary: string | null;
  output_summary: string | null;
  detail: string | null;
  agent_client: string | null;
  agent_model: string | null;
}

export const FEEDBACK_QUERY_KEY = ["feedback"] as const;

export function useFeedback(): UseQueryResult<AgentFeedback[]> {
  return useQuery<AgentFeedback[]>({
    queryKey: [...FEEDBACK_QUERY_KEY],
    queryFn: async () => {
      const data = await httpJson<{ feedback?: AgentFeedback[] }>("/v1/feedback?n=50");
      return Array.isArray(data.feedback) ? data.feedback : [];
    },
    refetchInterval: 60_000,
  });
}
