import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Plus, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { SkillEditor } from "@/components/skills/SkillEditor";
import { useSkills } from "@/hooks/useSkills";
import { cn } from "@/lib/utils";
import type { SkillDefinition } from "@/types/api";

export default function SkillsPage() {
  const queryClient = useQueryClient();
  const { data: skillsRaw, isLoading } = useSkills();
  const skills = Array.isArray(skillsRaw) ? (skillsRaw as SkillDefinition[]) : [];

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creatingNew, setCreatingNew] = useState(false);

  const selectedSkill = skills.find((s) => s.id === selectedId) ?? null;

  const handleSaved = () => {
    void queryClient.invalidateQueries({ queryKey: ["skills"] });
    setCreatingNew(false);
  };

  const startNew = () => {
    setSelectedId(null);
    setCreatingNew(true);
  };

  return (
    <div className="flex flex-col gap-6 h-full">
      <PageHeader
        title="Skills"
        description="Multi-step recipes that compose your tools into higher-level agent capabilities."
        actions={
          <Button size="sm" onClick={startNew} className="gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            New skill
          </Button>
        }
      />

      <div className="flex gap-4 flex-1 min-h-0">
        <div className="w-72 shrink-0 flex flex-col gap-2 overflow-hidden">
          <span className="px-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            {skills.length === 0 ? "Skills" : `Skills · ${skills.length}`}
          </span>

          <div className="flex-1 overflow-y-auto scrollbar-thin space-y-2 pr-1">
            {isLoading && (
              <>
                <Skeleton className="h-14 w-full" />
                <Skeleton className="h-14 w-full" />
              </>
            )}

            {!isLoading && skills.length === 0 && (
              <Card className="p-4 text-center">
                <p className="text-xs text-muted-foreground mb-2">No skills defined yet.</p>
                <Button size="sm" variant="outline" onClick={startNew} className="gap-1.5">
                  <Plus className="h-3.5 w-3.5" />
                  Create your first skill
                </Button>
              </Card>
            )}

            {skills.map((skill) => {
              const active = selectedId === skill.id;
              return (
                <button
                  key={skill.id}
                  onClick={() => {
                    setSelectedId(skill.id);
                    setCreatingNew(false);
                  }}
                  className={cn(
                    "w-full text-left rounded-lg border p-3 transition-all duration-200 ease-apple",
                    active
                      ? "border-primary/40 bg-primary/5 shadow-sm ring-1 ring-primary/10"
                      : "border-border bg-card hover:bg-muted/50"
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm truncate">{skill.name}</span>
                    <Badge variant="muted" className="ml-auto shrink-0">
                      {skill.steps.length} {skill.steps.length === 1 ? "step" : "steps"}
                    </Badge>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <Card className="flex-1 overflow-y-auto scrollbar-thin p-0">
          {creatingNew || selectedSkill ? (
            <SkillEditor skill={creatingNew ? null : selectedSkill} onSaved={handleSaved} />
          ) : (
            <div className="flex items-center justify-center h-full p-8">
              <EmptyState
                icon={Zap}
                title="No skill selected"
                description="Pick a skill from the list, or create a new multi-step recipe."
                action={
                  <Button size="sm" onClick={startNew} className="gap-1.5">
                    <Plus className="h-3.5 w-3.5" />
                    New skill
                  </Button>
                }
                className="border-0 bg-transparent"
              />
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
