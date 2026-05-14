import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useSessionState } from "./useSessionState";

interface SessionSnapshot {
  source_count?: number;
  tool_count?: number;
  skill_count?: number;
  connector_built?: boolean;
}

type CountKey = "source_count" | "tool_count" | "skill_count";

const LABELS: Record<CountKey, { singular: string; plural: string }> = {
  source_count: { singular: "New source added", plural: "new sources added" },
  tool_count: { singular: "New tool added", plural: "new tools added" },
  skill_count: { singular: "New skill added", plural: "new skills added" },
};

const ACTIVE_WINDOW_MS = 6_000;
const STORAGE_KEY = "elliot_last_session_snapshot_v1";

function loadPrev(): SessionSnapshot | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as SessionSnapshot) : null;
  } catch {
    return null;
  }
}

function savePrev(snap: SessionSnapshot) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(snap));
  } catch {
    // sessionStorage can fail in private-browsing mode; the in-memory ref
    // is the source of truth either way.
  }
}

/**
 * Watches the session state for count increases (sources, tools, skills,
 * connector_built) and fires user-visible toasts whenever the agent adds
 * something. Returns ``isActive`` which stays true for a short window
 * after each event — page headers use it to show a "live" pulse.
 *
 * Mount this exactly once at the app root; the previous snapshot is
 * persisted to sessionStorage so a hot-reload doesn't double-fire.
 */
export function useAgentActivity(): { isActive: boolean; lastEventAt: number | null } {
  const { data: rawSession } = useSessionState();
  const session = (rawSession ?? null) as SessionSnapshot | null;

  // In-memory ref tracks the most recent snapshot; sessionStorage is the
  // fallback used on first render so reload doesn't fire a flood of toasts.
  const prev = useRef<SessionSnapshot | null>(null);
  if (prev.current === null) {
    prev.current = loadPrev();
  }

  const [lastEventAt, setLastEventAt] = useState<number | null>(null);
  const [isActive, setIsActive] = useState(false);

  useEffect(() => {
    if (!session) return;

    const previous = prev.current;
    prev.current = session;
    savePrev(session);

    // First-ever load — no toast spam, just record the baseline.
    if (!previous) return;

    const events: string[] = [];
    (Object.keys(LABELS) as CountKey[]).forEach((key) => {
      const before = previous[key] ?? 0;
      const after = session[key] ?? 0;
      if (after > before) {
        const delta = after - before;
        events.push(delta === 1 ? LABELS[key].singular : `${delta} ${LABELS[key].plural}`);
      }
    });
    if (session.connector_built && !previous.connector_built) {
      events.push("Connector built");
    }

    if (events.length === 0) return;

    console.info("[agent-activity]", events);
    for (const event of events) {
      toast.success(event, { duration: 4000 });
    }
    const now = Date.now();
    setLastEventAt(now);
    setIsActive(true);
    const t = window.setTimeout(() => setIsActive(false), ACTIVE_WINDOW_MS);
    return () => window.clearTimeout(t);
  }, [session]);

  return { isActive, lastEventAt };
}
