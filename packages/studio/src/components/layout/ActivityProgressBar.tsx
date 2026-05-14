import { cn } from "@/lib/utils";

interface Props {
  isActive: boolean;
}

/**
 * Thin gradient bar that pulses across the top of the Header whenever the
 * agent just added something (a source / tool / skill / connector). Sits in
 * the Header so it scrolls with sticky positioning instead of floating over
 * the full viewport. Decorative only — toasts carry the actual messages.
 */
export function ActivityProgressBar({ isActive }: Props) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "absolute left-0 right-0 bottom-0 h-[2px] overflow-hidden transition-opacity duration-300",
        isActive ? "opacity-100" : "opacity-0"
      )}
    >
      <div className="h-full w-1/3 bg-gradient-to-r from-transparent via-primary to-transparent animate-activity-sweep" />
    </div>
  );
}
