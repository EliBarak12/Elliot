import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { callTool } from '@/lib/mcp-client';
import { useCallTool } from '@/hooks/useTools';
import { useTools } from '@/hooks/useTools';
import type { SkillDefinition, ToolDefinition } from '@/types/api';

interface SkillStep {
  alias: string;
  tool_id: string;
  params: Record<string, string>;
}

interface Props {
  skill: SkillDefinition | null;
  onSaved: () => void;
}

export function SkillEditor({ skill, onSaved }: Props) {
  const { data: toolsRaw } = useTools();
  const tools = Array.isArray(toolsRaw) ? (toolsRaw as ToolDefinition[]) : [];
  const { mutateAsync: callToolMutation, isPending: isTesting } = useCallTool();

  const [name, setName] = useState(skill?.name ?? '');
  const [description, setDescription] = useState(skill?.description ?? '');
  const [whenToUse, setWhenToUse] = useState(skill?.when_to_use ?? '');
  const [instructions, setInstructions] = useState(skill?.instructions ?? '');
  const [steps, setSteps] = useState<SkillStep[]>(
    (skill?.steps ?? []).map((s) => ({
      alias: s.alias,
      tool_id: s.tool_id,
      params: s.params as Record<string, string>,
    })),
  );
  const [testInputs, setTestInputs] = useState<Record<string, string>>({});
  const [testResult, setTestResult] = useState<unknown | null>(null);
  const [status, setStatus] = useState<{ type: 'ok' | 'error'; message: string } | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setName(skill?.name ?? '');
    setDescription(skill?.description ?? '');
    setWhenToUse(skill?.when_to_use ?? '');
    setInstructions(skill?.instructions ?? '');
    setSteps(
      (skill?.steps ?? []).map((s) => ({
        alias: s.alias,
        tool_id: s.tool_id,
        params: s.params as Record<string, string>,
      })),
    );
    setSaved(false);
    setStatus(null);
    // Clear transient test state so the previous skill's inputs/output don't
    // linger under the newly-selected skill.
    setTestInputs({});
    setTestResult(null);
  }, [skill]);

  const addStep = () =>
    setSteps((prev) => [...prev, { alias: `step${prev.length + 1}`, tool_id: '', params: {} }]);

  const updateStep = (i: number, s: SkillStep) => {
    const next = [...steps];
    next[i] = s;
    setSteps(next);
  };

  const handleSave = async () => {
    setStatus(null);
    try {
      const toolName = skill ? 'elliot_update_skill' : 'elliot_create_skill';
      await callTool(toolName, {
        skill: { name, description, steps, instructions, when_to_use: whenToUse },
      });
      setSaved(true);
      setStatus({ type: 'ok', message: 'Saved ✓' });
      onSaved();
    } catch (err) {
      setStatus({ type: 'error', message: err instanceof Error ? err.message : String(err) });
    }
  };

  const handleTest = async () => {
    setTestResult(null);
    try {
      const res = await callToolMutation({
        name: 'elliot_preview_skill',
        args: {
          skill: { name, description, steps, instructions, when_to_use: whenToUse },
          inputs: testInputs,
        },
      });
      setTestResult(res);
    } catch (err) {
      setTestResult({ error: err instanceof Error ? err.message : String(err) });
    }
  };

  return (
    <div className="space-y-4 p-4">
      <Input
        placeholder="Skill name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="h-8 text-sm"
      />
      <Textarea
        placeholder="Description"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        className="text-sm min-h-[60px]"
      />

      <div>
        <p className="text-xs font-medium text-muted-foreground mb-1">
          Workflow guide (optional)
        </p>
        <Input
          placeholder="When to use — e.g. when the user asks to reconcile invoices"
          value={whenToUse}
          onChange={(e) => setWhenToUse(e.target.value)}
          className="h-8 text-sm mb-2"
        />
        <Textarea
          placeholder="Instructions (markdown) — describe the workflow around your tools. Leave the steps below empty for a prose-only skill."
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          className="text-sm min-h-[100px] font-mono"
        />
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-medium text-muted-foreground">Steps</span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-6 text-xs"
            onClick={addStep}
          >
            + Add step
          </Button>
        </div>

        {steps.map((step, i) => {
          const selectedTool = tools.find((t) => t.id === step.tool_id);
          return (
            <div key={i} className="border rounded-md p-3 mb-2 space-y-2">
              <div className="flex gap-2 items-center">
                <Input
                  placeholder="alias"
                  value={step.alias}
                  onChange={(e) => updateStep(i, { ...step, alias: e.target.value })}
                  className="h-7 text-xs w-24"
                />
                <select
                  value={step.tool_id}
                  onChange={(e) => updateStep(i, { ...step, tool_id: e.target.value })}
                  className="flex-1 h-7 text-xs border rounded px-1"
                >
                  <option value="">— select tool —</option>
                  {tools.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="h-6 text-xs px-1"
                  onClick={() => setSteps((prev) => prev.filter((_, idx) => idx !== i))}
                >
                  ×
                </Button>
              </div>

              {selectedTool?.parameters.map((p) => (
                <div key={p.name} className="flex gap-2 items-center">
                  <span className="text-xs w-24 text-muted-foreground">{p.name}</span>
                  <Input
                    placeholder={`{{skill.input.${p.name}}}`}
                    value={step.params[p.name] ?? ''}
                    onChange={(e) =>
                      updateStep(i, {
                        ...step,
                        params: { ...step.params, [p.name]: e.target.value },
                      })
                    }
                    className="flex-1 h-7 text-xs"
                  />
                </div>
              ))}
            </div>
          );
        })}
      </div>

      {status && (
        <div
          className={`text-xs px-3 py-2 rounded border ${
            status.type === 'ok'
              ? 'bg-green-50 border-green-200 text-green-800'
              : 'bg-destructive/10 border-destructive/20 text-destructive'
          }`}
        >
          {status.message}
        </div>
      )}

      <Button size="sm" onClick={() => void handleSave()}>
        Save
      </Button>

      {saved && (
        <div className="border rounded-md p-3 space-y-2">
          <p className="text-xs font-medium text-muted-foreground">Test skill</p>
          <Input
            placeholder='{"input": "value"}'
            value={testInputs['input'] ?? ''}
            onChange={(e) => setTestInputs({ input: e.target.value })}
            className="h-7 text-xs"
          />
          <Button
            size="sm"
            variant="outline"
            disabled={isTesting}
            onClick={() => void handleTest()}
          >
            {isTesting ? 'Running…' : 'Test'}
          </Button>
          {testResult !== null && (
            <pre className="text-xs bg-muted rounded p-2 overflow-x-auto">
              {JSON.stringify(testResult, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
