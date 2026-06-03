// TypeScript types mirroring the Python Pydantic models in elliot-core.
// These are used as type-only imports to avoid pulling Node.js modules into the browser build.

import type { FilterGroup } from "@/components/tools/FilterGroupBuilder";
import type { ReturnField } from "@/components/tools/ReturnFieldSelector";
import type { ApiRequestMapping } from "@/components/tools/ApiMappingForm";

export interface ParameterDefinition {
  name: string;
  type: "string" | "integer" | "number" | "boolean" | "date";
  required: boolean;
  description: string;
  default: unknown;
}

export interface SourceConfig {
  id: string;
  name: string;
  type: "rest" | "postgres" | "mysql" | "file";
  url: string | null;
  auth: { type: string; secret_key: string } | null;
  data_path: string | null;
}

export interface ToolDefinition {
  id: string;
  name: string;
  description: string;
  category: "READ" | "WRITE" | "ACTION" | "AGGREGATE";
  source_ids: string[];
  sql: string | null;
  parameters: ParameterDefinition[];
  filter_groups?: FilterGroup[];
  return_fields?: ReturnField[];
  api_mapping?: ApiRequestMapping | null;
}

export interface SkillStep {
  alias: string;
  tool_id: string;
  params: Record<string, unknown>;
}

export interface SkillDefinition {
  id: string;
  name: string;
  description: string;
  // Optional: a skill can be pure prose (instructions only) or a deterministic
  // step chain, or both.
  steps?: SkillStep[];
  input_parameters: ParameterDefinition[];
  // Free-form markdown workflow guidance, exported as a SKILL.md body.
  instructions?: string;
  // Frontmatter trigger line for the exported SKILL.md.
  when_to_use?: string;
}

export interface ConnectorConfig {
  name: string;
  slug: string;
  version: string;
  description: string;
  sources: SourceConfig[];
  tools: ToolDefinition[];
  skills: SkillDefinition[];
}
