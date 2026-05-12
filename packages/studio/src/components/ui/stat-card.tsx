import * as React from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";

interface StatCardProps extends React.HTMLAttributes<HTMLDivElement> {
  label: string;
  value: React.ReactNode;
  icon?: LucideIcon;
  hint?: React.ReactNode;
  tone?: "default" | "primary" | "success" | "warning" | "destructive";
}

const toneMap: Record<NonNullable<StatCardProps["tone"]>, string> = {
  default: "text-foreground",
  primary: "text-primary",
  success: "text-success",
  warning: "text-warning",
  destructive: "text-destructive",
};

const iconToneMap: Record<NonNullable<StatCardProps["tone"]>, string> = {
  default: "bg-muted text-muted-foreground",
  primary: "bg-primary/10 text-primary",
  success: "bg-success/10 text-success",
  warning: "bg-warning/10 text-warning",
  destructive: "bg-destructive/10 text-destructive",
};

export function StatCard({
  label,
  value,
  icon: Icon,
  hint,
  tone = "default",
  className,
  ...props
}: StatCardProps) {
  return (
    <Card
      className={cn("p-5 hover:shadow-md", className)}
      {...props}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1 min-w-0">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            {label}
          </p>
          <p
            className={cn(
              "text-3xl font-semibold tabular-nums tracking-[-0.02em]",
              toneMap[tone]
            )}
          >
            {value}
          </p>
          {hint && (
            <p className="text-xs text-muted-foreground pt-0.5">{hint}</p>
          )}
        </div>
        {Icon && (
          <div
            className={cn(
              "flex h-9 w-9 items-center justify-center rounded-lg shrink-0",
              iconToneMap[tone]
            )}
          >
            <Icon className="h-4.5 w-4.5" />
          </div>
        )}
      </div>
    </Card>
  );
}
