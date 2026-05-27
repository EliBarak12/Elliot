import { useState } from "react";
import { ChevronDown, ChevronRight, MessageSquare } from "lucide-react";
import { type AgentFeedback, type FeedbackOutcome, useFeedback } from "@/hooks/useFeedback";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";

function outcomeVariant(outcome: FeedbackOutcome): "success" | "destructive" | "warning" {
  if (outcome === "success") return "success";
  if (outcome === "failure") return "destructive";
  return "warning";
}

function FeedbackField({ label, text }: { label: string; text: string }) {
  return (
    <div className="space-y-1">
      <p className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="text-xs text-foreground whitespace-pre-wrap break-words">{text}</p>
    </div>
  );
}

function FeedbackRow({ item }: { item: AgentFeedback }) {
  const [open, setOpen] = useState(false);
  const time = new Date(item.ts * 1000).toLocaleTimeString();
  const hasDetail = Boolean(
    item.why_chosen || item.input_summary || item.output_summary || item.detail
  );

  return (
    <div className="border-b border-border/60 last:border-0">
      <button
        data-testid="feedback-row"
        disabled={!hasDetail}
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-muted/40"
      >
        {hasDetail ? (
          open ? (
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          )
        ) : (
          <span className="w-3.5 shrink-0" />
        )}
        <span className="font-mono text-xs font-medium text-foreground truncate max-w-[12rem]">
          {item.tool_id}
        </span>
        <Badge variant={outcomeVariant(item.outcome)}>{item.outcome}</Badge>
        {item.agent_client && (
          <Badge variant="outline" className="font-mono text-2xs">
            {item.agent_client}
            {item.agent_model ? `/${item.agent_model}` : ""}
          </Badge>
        )}
        <span className="ml-auto text-2xs text-muted-foreground tabular-nums shrink-0">{time}</span>
      </button>
      {open && hasDetail && (
        <div className="space-y-3 bg-muted/30 px-9 py-3 animate-fade-in-up">
          {item.why_chosen && <FeedbackField label="Why this tool" text={item.why_chosen} />}
          {item.input_summary && <FeedbackField label="Input" text={item.input_summary} />}
          {item.output_summary && <FeedbackField label="Output" text={item.output_summary} />}
          {item.detail && <FeedbackField label="Detail / notes" text={item.detail} />}
        </div>
      )}
    </div>
  );
}

export function FeedbackPanel() {
  const { data, isLoading } = useFeedback();
  const feedback = Array.isArray(data) ? data : [];

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>
          Agent Feedback
          {feedback.length > 0 && (
            <span className="ml-2 text-xs font-normal text-muted-foreground tabular-nums">
              ({feedback.length})
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {isLoading && (
          <div className="space-y-2 px-4 pb-4">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        )}
        {!isLoading && feedback.length === 0 && (
          <div className="px-4 pb-4">
            <EmptyState
              icon={MessageSquare}
              title="No agent feedback yet"
              description="Every connector exposes a submit_feedback tool. When an agent reports how a tool worked, it appears here."
              className="border-0 bg-transparent"
            />
          </div>
        )}
        {feedback.map((item) => (
          <FeedbackRow key={item.id} item={item} />
        ))}
      </CardContent>
    </Card>
  );
}
