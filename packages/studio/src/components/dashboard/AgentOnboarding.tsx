import * as React from "react";
import { Check, Copy, Sparkles, Terminal } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const CONNECT_COMMAND = "make dev";
const EXAMPLE_PROMPT =
  "I have an API at https://api.example.com — help me build a connector for it.";

const SUPPORTED_AGENTS = [
  { name: "Claude Code", note: ".mcp.json" },
  { name: "Cursor", note: ".cursor/mcp.json" },
  { name: "VS Code / Copilot", note: ".vscode/mcp.json" },
  { name: "Windsurf", note: "~/.codeium/windsurf" },
  { name: "Codex", note: ".codex/config.toml" },
];

interface AgentOnboardingProps {
  /** When `true`, render the compact one-line variant. Used after the agent
   *  has already touched Elliot (a connector is built or audit entries
   *  exist), so the onboarding stays out of the way without disappearing. */
  compact?: boolean;
}

export function AgentOnboarding({ compact = false }: AgentOnboardingProps) {
  if (compact) {
    return <CompactReconnectHint />;
  }

  return (
    <Card className="border-primary/30 bg-gradient-to-br from-primary/5 via-card to-card">
      <CardHeader>
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Sparkles className="h-4 w-4" />
          </div>
          <div className="space-y-1">
            <CardTitle>Let your agent do the work</CardTitle>
            <CardDescription>
              Elliot is built for agents, not clicks. Wire your agent up once, then describe what
              you want — it will discover sources, draft tools, and build the connector. This
              dashboard is here to <em>watch</em>, not to drive.
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <OnboardingStep
          number={1}
          title="Start Elliot and auto-register your agent"
          description="`make dev` runs `elliot connect` first, which detects every coding agent on this machine and writes the right MCP config for each."
        >
          <CopyableCommand command={CONNECT_COMMAND} />
          <div className="mt-3 flex flex-wrap gap-1.5">
            {SUPPORTED_AGENTS.map((agent) => (
              <span
                key={agent.name}
                title={agent.note}
                className="inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-card px-2.5 py-0.5 text-2xs font-medium text-muted-foreground"
              >
                <span className="h-1 w-1 rounded-full bg-success/70" />
                {agent.name}
              </span>
            ))}
          </div>
        </OnboardingStep>

        <OnboardingStep
          number={2}
          title="Tell your agent what to build"
          description="Open the agent you just wired up and ask it. It will call Elliot's MCP tools to discover the API, draft tools, and run evals."
        >
          <CopyablePrompt prompt={EXAMPLE_PROMPT} />
        </OnboardingStep>

        <OnboardingStep
          number={3}
          title="Watch the agent work, right here"
          description="Every tool call, token cost, and error shows up below. When the connector is built, the runtime URL is auto-registered too (run `elliot connect --runtime` to re-verify the handshake)."
          last
        />
      </CardContent>
    </Card>
  );
}

function CompactReconnectHint() {
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3 text-sm text-muted-foreground">
        <span className="inline-flex items-center gap-2 text-foreground">
          <Sparkles className="h-3.5 w-3.5 text-primary" />
          <span className="font-medium">Your agent runs the show.</span>
        </span>
        <span>Re-wire any time:</span>
        <CopyableCommand command={CONNECT_COMMAND} compact />
      </CardContent>
    </Card>
  );
}

function OnboardingStep({
  number,
  title,
  description,
  children,
  last = false,
}: {
  number: number;
  title: string;
  description: string;
  children?: React.ReactNode;
  last?: boolean;
}) {
  return (
    <div className="flex gap-4">
      <div className="flex flex-col items-center">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-primary/30 bg-primary/10 font-mono text-xs font-semibold text-primary">
          {number}
        </div>
        {!last && <div className="mt-1 w-px flex-1 bg-border/70" />}
      </div>
      <div className={cn("flex-1 min-w-0 space-y-2", last ? "pb-0" : "pb-2")}>
        <div className="space-y-0.5">
          <p className="text-sm font-medium text-foreground">{title}</p>
          <p className="text-sm text-muted-foreground [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-2xs">
            {renderInlineCode(description)}
          </p>
        </div>
        {children}
      </div>
    </div>
  );
}

/** Tiny markdown-ish helper so `code` segments render in <code> without
 *  pulling a markdown lib for one paragraph. */
function renderInlineCode(text: string): React.ReactNode {
  const parts = text.split(/(`[^`]+`)/g);
  return parts.map((part, i) =>
    part.startsWith("`") && part.endsWith("`") ? (
      <code key={i}>{part.slice(1, -1)}</code>
    ) : (
      <React.Fragment key={i}>{part}</React.Fragment>
    )
  );
}

function CopyableCommand({ command, compact = false }: { command: string; compact?: boolean }) {
  return (
    <div
      className={cn(
        "group flex items-center gap-2 rounded-md border border-border/70 bg-muted/40 font-mono text-sm",
        compact ? "px-2 py-1" : "px-3 py-2"
      )}
    >
      <Terminal
        className={cn("shrink-0 text-muted-foreground", compact ? "h-3 w-3" : "h-3.5 w-3.5")}
      />
      <code className="flex-1 truncate text-foreground">$ {command}</code>
      <CopyButton value={command} label={`Copy command: ${command}`} />
    </div>
  );
}

function CopyablePrompt({ prompt }: { prompt: string }) {
  return (
    <div className="rounded-md border border-border/70 bg-muted/40 p-3">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm italic text-foreground">"{prompt}"</p>
        <CopyButton value={prompt} label="Copy example prompt" />
      </div>
    </div>
  );
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = React.useState(false);

  const handleCopy = React.useCallback(async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // navigator.clipboard rejects under non-secure origins; the user can
      // still select the text manually. Don't surface a fake error toast.
    }
  }, [value]);

  return (
    <button
      type="button"
      onClick={handleCopy}
      aria-label={label}
      className={cn(
        "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted-foreground",
        "transition-colors hover:bg-muted hover:text-foreground",
        copied && "text-success"
      )}
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}
