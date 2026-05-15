import * as React from "react";
import { Check, Copy, Sparkles, Terminal } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

const EXAMPLE_PROMPT =
  "I have an API at https://api.example.com — help me build a connector for it.";

type InstallOption = {
  id: string;
  agent: string;
  blurb: string;
  commands: string[];
};

const INSTALL_OPTIONS: InstallOption[] = [
  {
    id: "local-dev",
    agent: "Local dev (this repo)",
    blurb:
      "Recommended today: boots plugin + runtime + studio AND wires every detected agent. Everything below this option still requires the server to be running.",
    commands: ["make dev"],
  },
  {
    id: "claude-code",
    agent: "Claude Code marketplace",
    blurb:
      "Marketplace install (works once these manifests are on the repo's default branch). Wires the URL only — you still need a running Elliot server.",
    commands: [
      "/plugin marketplace add EliBarak12/elliot",
      "/plugin install elliot@elliot",
    ],
  },
  {
    id: "codex",
    agent: "Codex marketplace",
    blurb:
      "Experimental: Codex plugins shipped Mar 2026; treat as evolving. Same caveat as Claude Code — URL-only, server must be running.",
    commands: [
      "codex plugin marketplace add EliBarak12/elliot",
      "/plugin install elliot",
    ],
  },
  {
    id: "any-agent",
    agent: "Cursor, VS Code, Windsurf",
    blurb:
      "Not yet published to npm. Logic lives in packages/mcp-plugin/scripts/install.py; will detect every coding agent and write the right MCP config.",
    commands: ["npx @elliot/connect"],
  },
];

interface AgentOnboardingProps {
  /** When `true`, render the compact one-line variant. */
  compact?: boolean;
}

export function AgentOnboarding({ compact = false }: AgentOnboardingProps) {
  // React's Rules of Hooks: every hook must run on every render, in the same
  // order. Call useState BEFORE any conditional return — otherwise the hook
  // count changes when `compact` flips (e.g. when the audit log gets its first
  // entry and Dashboard re-renders with compact={true}), and the entire
  // Dashboard subtree crashes with "Rendered fewer hooks than during the
  // previous render."
  const [selectedId, setSelectedId] = React.useState<string>(INSTALL_OPTIONS[0].id);

  if (compact) {
    return <CompactReconnectHint />;
  }

  const selected =
    INSTALL_OPTIONS.find((o) => o.id === selectedId) ?? INSTALL_OPTIONS[0];

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
              Elliot is built for agents, not clicks. Install once for the agent you use, then
              describe what you want — it will discover sources, draft tools, lint, and deploy.
              This dashboard is here to <em>watch</em>, not to drive.
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <OnboardingStep
          number={1}
          title="Install Elliot for your agent"
          description="One command installs the MCP server AND the six skills (`getting-started`, `discover-source`, `build-connector`, `lint-connector`, `run-eval`, `deploy`) into your agent."
        >
          <div className="flex flex-wrap gap-1.5">
            {INSTALL_OPTIONS.map((opt) => (
              <button
                key={opt.id}
                type="button"
                onClick={() => setSelectedId(opt.id)}
                aria-pressed={selectedId === opt.id}
                className={cn(
                  "rounded-full border px-3 py-1 text-2xs font-medium transition-colors",
                  selectedId === opt.id
                    ? "border-primary/60 bg-primary/10 text-foreground"
                    : "border-border/60 bg-card text-muted-foreground hover:text-foreground"
                )}
              >
                {opt.agent}
              </button>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">{selected.blurb}</p>
          <div className="space-y-1.5">
            {selected.commands.map((cmd) => (
              <CopyableCommand key={cmd} command={cmd} />
            ))}
          </div>
        </OnboardingStep>

        <OnboardingStep
          number={2}
          title="Tell your agent what to build"
          description="Open the agent you just wired up and ask it. On first connect it will call `prompts/get name=getting_started` and then walk through `discover-source` → `build-connector` → `lint-connector` → `run-eval` → `deploy`."
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
        <span>Re-install any time:</span>
        <CopyableCommand command="/plugin install elliot@elliot" compact />
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
        className={cn(
          "shrink-0 text-muted-foreground",
          compact ? "h-3 w-3" : "h-3.5 w-3.5"
        )}
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
        <p className="text-sm italic text-foreground">&quot;{prompt}&quot;</p>
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
      // navigator.clipboard rejects under non-secure origins
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
