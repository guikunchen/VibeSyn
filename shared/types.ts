export type RecipientType = "Agent" | "Device" | "Tool" | "Human" | "Self" | "";
export type EndpointKind = "devices" | "tools";

export interface OutputRule {
  to: [RecipientType, string];
  decision_type: string;
  format: string;
}

export interface AgentConfig {
  is_memory_forgot?: boolean;
  system_prompt: string;
  enabled: boolean;
  model: string;
  temperature: number;
  background: string;
  output_format: OutputRule[];
  workflow: string;
  initial_assistant_message?: string;
  api_key: string;
  api_url: string;
}

export type Agents = Record<string, AgentConfig>;

export interface WaitingEntry {
  sender?: string;
  task?: unknown;
  results?: unknown;
  resource_paths?: string[];
  task_send_flag?: boolean;
  [key: string]: unknown;
}

export interface TaskMessage {
  role: string;
  time: string;
  content?: string;
  task_type?: string;
  task_content?: Record<string, unknown> | string;
  waiting_info?: Record<string, WaitingEntry>;
}

export interface TaskRecord {
  task_name: string;
  task_description: string;
  messages: TaskMessage[];
  task_status: string;
  cur_task_type: string;
  cur_task_content: Record<string, unknown>;
  current_agent?: string;
  waiting_info?: Record<string, WaitingEntry>;
  final_results?: unknown;
}

export interface ResourceMeta {
  name: string;
  path: string;
  url: string;
  kind: "image" | "text" | "json" | "file";
}

export interface TaskMessageView {
  rawIndex: number;
  displayIndex: number;
  time: string;
  type: string;
  sender?: string;
  recipient?: string;
  senderIcon?: string;
  recipientIcon?: string;
  content: string;
  rawContent: string;
  isNarration: boolean;
  resources: ResourceMeta[];
  retroPathBaseUrl?: string;
  editable: boolean;
  deletable: boolean;
}

export interface TaskView {
  task: TaskRecord;
  messages: TaskMessageView[];
}

export interface GraphNodeData {
  id: string;
  label: string;
  category: "manager" | "agent" | "device" | "tool" | "other";
  highlighted: boolean;
}

export interface GraphEdgeData {
  id: string;
  source: string;
  target: string;
  dashed: boolean;
}

export interface GraphData {
  nodes: GraphNodeData[];
  edges: GraphEdgeData[];
}

export interface EndpointDescriptor {
  name: string;
  title: string;
  kind: EndpointKind;
  supportsStatus: boolean;
  supportsSettings: boolean;
  supportsMongo: boolean;
  supportsReagents: boolean;
  supportsRetroPaths: boolean;
  resultRows: number;
  metricFields: Array<{ key: string; label: string; unit?: string }>;
}

export interface EndpointConfig {
  connection_settings?: {
    http_url?: string;
    http_status?: boolean | null;
    mongodb_address?: string;
    mongodb_database?: string;
    mongodb_collection?: string;
    mongodb_status?: boolean | null;
  };
  reagent_settings?: Record<string, string>;
  [key: string]: unknown;
}

export interface EndpointState {
  descriptor: EndpointDescriptor;
  config: EndpointConfig | null;
  taskName: string | null;
  taskStatus: string | null;
  taskInput: string | null;
  result: string | null;
  resources: ResourceMeta[];
  retroPathCount: number;
}

export interface TimelineSegment {
  operation: string;
  start: string;
  finish: string;
}

export interface DeviceStatus {
  device_status: string;
  total_records: number;
  latest_record: Record<string, unknown>;
  all_records: Array<Record<string, unknown>>;
  query_task_id?: string;
  error?: string;
  timeline: TimelineSegment[];
}

export interface RetroNode {
  id: string;
  type: "chemical" | "condition";
  smiles?: string;
  label?: string;
  procedure?: string;
  children: RetroNode[];
}
