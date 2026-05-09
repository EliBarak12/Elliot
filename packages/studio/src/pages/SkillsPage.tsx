import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { callTool } from "@/lib/mcp-client";
import { SkillEditor } from "@/components/skills/SkillEditor";
import type { SkillDefinition } from "@/types/api";

export default function SkillsPage() {
  const queryClient = useQueryClient();
  const { data: skillsRaw, isLoading } = useQuery({
    queryKey: ["skills"],
    queryFn: () => callTool("elliot_list_skills", {}),
  });
  const skills = Array.isArray(skillsRaw) ? (skillsRaw as SkillDefinition[]) : [];

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creatingNew, setCreatingNew] = useState(false);

  const selectedSkill = skills.find((s) => s.id === selectedId) ?? null;

  const handleSaved = () => {
    void queryClient.invalidateQueries({ queryKey: ["skills"] });
    setCreatingNew(false);
  };

  return (
    <div className="flex gap-4 h-full">
      <div className="w-64 shrink-0 space-y-2 overflow-y-auto">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium">Skills ({skills.length})</span>
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs"
            onClick={() => {
              setSelectedId(null);
              setCreatingNew(true);
            }}
          >
            + New
          </Button>
        </div>

        {isLoading && <p className="text-xs text-muted-foreground">Loading…</p>}

        {skills.map((skill) => (
          <button
            key={skill.id}
            onClick={() => {
              setSelectedId(skill.id);
              setCreatingNew(false);
            }}
            className={`w-full text-left rounded-lg border p-3 transition-colors hover:bg-accent ${selectedId === skill.id ? "bg-accent border-primary" : ""}`}
          >
            <div className="flex items-center gap-2">
              <span className="font-medium text-sm truncate">{skill.name}</span>
              <Badge variant="secondary" className="text-xs ml-auto shrink-0">
                {skill.steps.length} steps
              </Badge>
            </div>
          </button>
        ))}
      </div>

      <div className="flex-1 border rounded-lg overflow-y-auto">
        {creatingNew || selectedSkill ? (
          <SkillEditor skill={creatingNew ? null : selectedSkill} onSaved={handleSaved} />
        ) : (
          <div className="flex items-center justify-center h-full">
            <Card>
              <CardContent className="py-8 text-sm text-muted-foreground">
                Select a skill or create a new one
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}
