import {
  existsSync,
  readdirSync,
  readFileSync,
} from "node:fs";
import { join, relative } from "node:path";
import { MongoClient } from "mongodb";
import type {
  DeviceStatus,
  EndpointConfig,
  EndpointDescriptor,
  EndpointKind,
  EndpointState,
  ResourceMeta,
  RetroNode,
  TimelineSegment,
} from "../shared/types.ts";
import { ApiError } from "./errors.ts";
import {
  ROOT,
  latestTaskName,
  readAgents,
  readJson,
  readTask,
  resourceMeta,
  taskDir,
  writeJson,
  writeTask,
} from "./storage.ts";

const descriptors: Record<string, Omit<EndpointDescriptor, "kind">> = {
  ReacOptDevice: {
    name: "ReacOptDevice",
    title: "Reaction Optimization Device",
    supportsStatus: true,
    supportsSettings: true,
    supportsMongo: true,
    supportsReagents: true,
    supportsRetroPaths: false,
    resultRows: 5,
    metricFields: [
      { key: "Operations", label: "Latest Operation" },
      { key: "ReactorTemp-1", label: "Latest Reactor Temperature 1", unit: "°C" },
      { key: "ReactorTemp-2", label: "Latest Reactor Temperature 2", unit: "°C" },
    ],
  },
  ReacExecDevice: {
    name: "ReacExecDevice",
    title: "Reaction Execution Device",
    supportsStatus: true,
    supportsSettings: true,
    supportsMongo: true,
    supportsReagents: true,
    supportsRetroPaths: false,
    resultRows: 5,
    metricFields: [
      { key: "Operations", label: "Latest Operation" },
      { key: "ReactorTemp", label: "Latest Reactor Temperature", unit: "°C" },
    ],
  },
  ExtracExecDevice: {
    name: "ExtracExecDevice",
    title: "Extraction Execution Device",
    supportsStatus: true,
    supportsSettings: true,
    supportsMongo: true,
    supportsReagents: true,
    supportsRetroPaths: false,
    resultRows: 8,
    metricFields: [{ key: "Operations", label: "Latest Operation" }],
  },
  ExtracOptDevice: {
    name: "ExtracOptDevice",
    title: "Extraction Optimization Device",
    supportsStatus: true,
    supportsSettings: true,
    supportsMongo: true,
    supportsReagents: false,
    supportsRetroPaths: false,
    resultRows: 5,
    metricFields: [{ key: "Operations", label: "Latest Operation" }],
  },
  SepExecDevice: {
    name: "SepExecDevice",
    title: "Separation Execution Device",
    supportsStatus: true,
    supportsSettings: true,
    supportsMongo: true,
    supportsReagents: false,
    supportsRetroPaths: false,
    resultRows: 5,
    metricFields: [{ key: "Operations", label: "Latest Operation" }],
  },
  SepOptDevice: {
    name: "SepOptDevice",
    title: "Separation Optimization Device",
    supportsStatus: true,
    supportsSettings: true,
    supportsMongo: true,
    supportsReagents: false,
    supportsRetroPaths: false,
    resultRows: 5,
    metricFields: [{ key: "Operations", label: "Latest Operation" }],
  },
  PeptidesDevice: {
    name: "PeptidesDevice",
    title: "Peptides Device",
    supportsStatus: true,
    supportsSettings: true,
    supportsMongo: true,
    supportsReagents: false,
    supportsRetroPaths: false,
    resultRows: 5,
    metricFields: [{ key: "Operations", label: "Latest Operation" }],
  },
  RetroDesTool: {
    name: "RetroDesTool",
    title: "Retrosynthesis Design Tool",
    supportsStatus: true,
    supportsSettings: true,
    supportsMongo: false,
    supportsReagents: false,
    supportsRetroPaths: true,
    resultRows: 5,
    metricFields: [],
  },
  BayesianTool: {
    name: "BayesianTool",
    title: "Bayesian Tool",
    supportsStatus: true,
    supportsSettings: true,
    supportsMongo: false,
    supportsReagents: false,
    supportsRetroPaths: false,
    resultRows: 8,
    metricFields: [],
  },
  NMRTool: {
    name: "NMRTool",
    title: "NMR Tool",
    supportsStatus: true,
    supportsSettings: true,
    supportsMongo: false,
    supportsReagents: false,
    supportsRetroPaths: false,
    resultRows: 8,
    metricFields: [],
  },
  RetroEvalTool: {
    name: "RetroEvalTool",
    title: "Retrosynthesis Evaluation Tool",
    supportsStatus: false,
    supportsSettings: false,
    supportsMongo: false,
    supportsReagents: false,
    supportsRetroPaths: false,
    resultRows: 16,
    metricFields: [],
  },
  ReadJSONTool: {
    name: "ReadJSONTool",
    title: "Read JSON Tool",
    supportsStatus: false,
    supportsSettings: false,
    supportsMongo: false,
    supportsReagents: false,
    supportsRetroPaths: false,
    resultRows: 16,
    metricFields: [],
  },
  HandbookSearchTool: {
    name: "HandbookSearchTool",
    title: "Handbook Search Tool",
    supportsStatus: false,
    supportsSettings: false,
    supportsMongo: false,
    supportsReagents: false,
    supportsRetroPaths: false,
    resultRows: 16,
    metricFields: [],
  },
};

for (const [name, metadata] of Object.entries({
  ReactionPhotoTool: { title: "Reaction Photo Tool", resultRows: 8 },
  ExtracExecPhotoTool: { title: "Extraction Execution Photo Tool", resultRows: 5 },
  ExtracOptPhotoTool: { title: "Extraction Optimization Photo Tool", resultRows: 5 },
  SepExecPhotoTool: { title: "Separation Execution Photo Tool", resultRows: 5 },
  SepOptPhotoTool: { title: "Separation Optimization Photo Tool", resultRows: 5 },
})) {
  descriptors[name] = {
    name,
    title: metadata.title,
    supportsStatus: false,
    supportsSettings: false,
    supportsMongo: false,
    supportsReagents: false,
    supportsRetroPaths: false,
    resultRows: metadata.resultRows,
    metricFields: [],
  };
}

function endpointDescriptor(kind: EndpointKind, name: string): EndpointDescriptor {
  const descriptor = descriptors[name];
  if (!descriptor) {
    throw new ApiError(404, `Endpoint '${name}' is not supported.`);
  }
  if (kind === "devices" && !name.endsWith("Device")) {
    throw new ApiError(404, `Device '${name}' does not exist.`);
  }
  if (kind === "tools" && !name.endsWith("Tool")) {
    throw new ApiError(404, `Tool '${name}' does not exist.`);
  }
  return { ...descriptor, kind };
}

export function listEndpoints(kind: EndpointKind): EndpointDescriptor[] {
  const agents = readAgents();
  const names = new Set<string>();
  const source =
    kind === "devices"
      ? Object.values(agents)
      : Object.values(agents).filter((agent) => agent.enabled);
  for (const agent of source) {
    for (const output of agent.output_format) {
      const name = output.to?.[1];
      if (name?.endsWith(kind === "devices" ? "Device" : "Tool")) names.add(name);
    }
  }
  names.add(kind === "devices" ? "ReacOptDevice" : "RetroDesTool");
  return [...names]
    .filter((name) => descriptors[name])
    .sort()
    .map((name) => endpointDescriptor(kind, name));
}

function configFile(kind: EndpointKind, name: string): string {
  endpointDescriptor(kind, name);
  return join(
    ROOT,
    "src/chem_main",
    kind === "devices" ? "devices" : "tools",
    "config",
    `${name}.json`,
  );
}

export function readEndpointConfig(kind: EndpointKind, name: string): EndpointConfig | null {
  const path = configFile(kind, name);
  if (!existsSync(path)) return null;
  const config = readJson<EndpointConfig>(path);
  if (
    config.connection_settings &&
    !config.connection_settings.mongodb_address &&
    Bun.env.MONGODB_URI
  ) {
    config.connection_settings.mongodb_address = Bun.env.MONGODB_URI;
  }
  return config;
}

export function writeEndpointConfig(
  kind: EndpointKind,
  name: string,
  config: EndpointConfig,
): EndpointConfig {
  const descriptor = endpointDescriptor(kind, name);
  if (!descriptor.supportsSettings) {
    throw new ApiError(409, `${descriptor.title} has no settings.`);
  }
  writeJson(configFile(kind, name), config);
  return config;
}

function latestExecutionDirectory(taskName: string, endpoint: string): string | null {
  const base = join(taskDir(taskName), "resources", endpoint);
  if (!existsSync(base)) return null;
  const candidates = readdirSync(base, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && /^Execution_\d+$/.test(entry.name))
    .sort((a, b) => Number(b.name.split("_")[1]) - Number(a.name.split("_")[1]));
  return candidates[0] ? join(base, candidates[0].name) : null;
}

function filesRecursively(directory: string): string[] {
  const files: string[] = [];
  const walk = (current: string) => {
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      const path = join(current, entry.name);
      if (entry.isDirectory()) walk(path);
      else if (entry.isFile()) files.push(path);
    }
  };
  walk(directory);
  return files;
}

function endpointResources(taskName: string, endpoint: string): ResourceMeta[] {
  const execution = latestExecutionDirectory(taskName, endpoint);
  if (!execution) return [];
  return filesRecursively(execution)
    .map((path) => resourceMeta(taskName, relative(ROOT, path)))
    .filter((item): item is ResourceMeta => item !== null);
}

function formatTaskValue(value: unknown): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

export function readEndpointState(kind: EndpointKind, name: string): EndpointState {
  const descriptor = endpointDescriptor(kind, name);
  const latest = latestTaskName();
  const config = readEndpointConfig(kind, name);
  if (!latest) {
    return {
      descriptor,
      config,
      taskName: null,
      taskStatus: null,
      taskInput: null,
      result: null,
      resources: [],
      retroPathCount: 0,
    };
  }
  const task = readTask(latest);
  const waiting = task.waiting_info?.[name];
  const taskInput =
    waiting && !waiting.task_send_flag && waiting.task !== undefined
      ? formatTaskValue(waiting.task)
      : null;
  const current = task.cur_task_content ?? {};
  const result =
    task.cur_task_type === "tool or device send feedback" && current.sender === name
      ? formatTaskValue(current.feedback)
      : null;
  const resources = endpointResources(latest, name);
  const retroPathCount = descriptor.supportsRetroPaths
    ? resources.filter((resource) => /^path\d+_info\.json$/.test(resource.name)).length
    : 0;
  return {
    descriptor,
    config,
    taskName: latest,
    taskStatus: task.task_status,
    taskInput,
    result,
    resources,
    retroPathCount,
  };
}

export function dispatchEndpointTask(
  kind: EndpointKind,
  name: string,
  input: string,
): EndpointState {
  if (typeof input !== "string") throw new ApiError(400, "Task input must be text.");
  endpointDescriptor(kind, name);
  const latest = latestTaskName();
  if (!latest) throw new ApiError(404, "No task exists.");
  const task = readTask(latest);
  if (task.task_status !== "paused" || task.cur_task_type !== "waiting tool or device") {
    throw new ApiError(409, "The task is not paused for tool or device input.");
  }
  const waiting = task.waiting_info?.[name];
  if (!waiting) throw new ApiError(409, `${name} has no pending task.`);
  let parsed: unknown;
  try {
    parsed = JSON.parse(input);
  } catch {
    throw new ApiError(400, "Task input must be valid JSON.");
  }
  waiting.task = input;
  task.task_status = "waiting for server process";
  for (const message of task.messages.slice(-2)) {
    if (typeof message.task_content === "object" && message.task_content) {
      message.task_content.task = parsed;
    }
  }
  writeTask(task);
  return readEndpointState(kind, name);
}

export function submitEndpointFeedback(
  kind: EndpointKind,
  name: string,
  feedback: string,
): EndpointState {
  if (typeof feedback !== "string") throw new ApiError(400, "Feedback must be text.");
  endpointDescriptor(kind, name);
  const latest = latestTaskName();
  if (!latest) throw new ApiError(404, "No task exists.");
  const task = readTask(latest);
  if (
    task.task_status !== "paused" ||
    task.cur_task_type !== "tool or device send feedback" ||
    task.cur_task_content.sender !== name
  ) {
    throw new ApiError(409, `${name} has no result ready to send back.`);
  }
  const last = task.messages.at(-1);
  if (last?.task_type !== "tool or device send feedback") {
    throw new ApiError(409, "Unexpected task history state.");
  }
  task.task_status = "waiting for server process";
  task.cur_task_content.feedback = feedback;
  if (typeof last.task_content === "object" && last.task_content) {
    last.task_content.feedback = feedback;
  }
  writeTask(task);
  return readEndpointState(kind, name);
}

export async function testHttpEndpoint(
  kind: EndpointKind,
  name: string,
): Promise<EndpointConfig> {
  const config = readEndpointConfig(kind, name);
  const url = config?.connection_settings?.http_url;
  if (!config || !url) throw new ApiError(400, "HTTP address is not configured.");
  let ok = false;
  try {
    const response = await fetch(`${url.replace(/\/$/, "")}/ping`, {
      signal: AbortSignal.timeout(10_000),
    });
    ok = response.status === 200;
  } catch {
    ok = false;
  }
  config.connection_settings!.http_status = ok;
  writeJson(configFile(kind, name), config);
  return config;
}

export async function testMongoEndpoint(name: string): Promise<EndpointConfig> {
  const kind: EndpointKind = "devices";
  const config = readEndpointConfig(kind, name);
  const uri = config?.connection_settings?.mongodb_address;
  if (!config || !uri) throw new ApiError(400, "MongoDB address is not configured.");
  const client = new MongoClient(uri, { serverSelectionTimeoutMS: 10_000 });
  let ok = false;
  try {
    await client.db("admin").command({ ping: 1 });
    ok = true;
  } catch {
    ok = false;
  } finally {
    await client.close();
  }
  config.connection_settings!.mongodb_status = ok;
  writeJson(configFile(kind, name), config);
  return config;
}

function timelineFromRecords(records: Array<Record<string, unknown>>): TimelineSegment[] {
  const sorted = records
    .map((record) => ({
      operation: String(record.Operations ?? "Unknown"),
      time: String(record.time ?? ""),
      date: new Date(String(record.time ?? "")),
    }))
    .filter((record) => !Number.isNaN(record.date.getTime()))
    .sort((a, b) => a.date.getTime() - b.date.getTime());
  if (!sorted.length) return [];
  const segments: TimelineSegment[] = [];
  let start = 0;
  for (let index = 1; index <= sorted.length; index += 1) {
    if (index < sorted.length && sorted[index].operation === sorted[start].operation) continue;
    const startDate = sorted[start].date;
    let finishDate = index < sorted.length ? sorted[index].date : sorted[index - 1].date;
    if (finishDate.getTime() === startDate.getTime()) {
      finishDate = new Date(startDate.getTime() + 60_000);
    }
    segments.push({
      operation: sorted[start].operation,
      start: startDate.toISOString(),
      finish: finishDate.toISOString(),
    });
    start = index;
  }
  return segments;
}

export async function queryDeviceStatus(name: string, taskId: string): Promise<DeviceStatus> {
  const descriptor = endpointDescriptor("devices", name);
  if (!descriptor.supportsMongo) {
    throw new ApiError(409, `${descriptor.title} has no MongoDB status view.`);
  }
  if (!taskId.trim()) throw new ApiError(400, "RunningTaskId is required.");
  const config = readEndpointConfig("devices", name);
  const settings = config?.connection_settings;
  if (
    !settings?.mongodb_address ||
    !settings.mongodb_database ||
    !settings.mongodb_collection
  ) {
    throw new ApiError(400, "MongoDB connection settings are incomplete.");
  }
  const client = new MongoClient(settings.mongodb_address, {
    serverSelectionTimeoutMS: 10_000,
  });
  try {
    const collection = client
      .db(settings.mongodb_database)
      .collection(settings.mongodb_collection);
    const filter = { "RunningTask.RunningTaskId": taskId };
    const [records, count] = await Promise.all([
      collection.find(filter).sort({ timestamp: -1, _id: -1 }).toArray(),
      collection.countDocuments(filter),
    ]);
    const normalized = JSON.parse(JSON.stringify(records)) as Array<Record<string, unknown>>;
    if (!normalized.length) {
      return {
        device_status: "no_data",
        total_records: 0,
        latest_record: {},
        all_records: [],
        query_task_id: taskId,
        timeline: [],
      };
    }
    const latest = normalized[0];
    let status = String(latest.DeviceStatus ?? "unknown");
    const latestTime = new Date(String(latest.time ?? ""));
    if (!Number.isNaN(latestTime.getTime()) && Date.now() - latestTime.getTime() > 600_000) {
      status = "offline";
    }
    return {
      device_status: status,
      total_records: count,
      latest_record: latest,
      all_records: normalized,
      query_task_id: taskId,
      timeline: timelineFromRecords(normalized),
    };
  } catch (error) {
    return {
      device_status: "error",
      total_records: 0,
      latest_record: {},
      all_records: [],
      query_task_id: taskId,
      error: error instanceof Error ? error.message : "Unknown MongoDB error",
      timeline: [],
    };
  } finally {
    await client.close();
  }
}

function conditionLabel(raw: Record<string, unknown>): { label: string; procedure: string } {
  const conditions =
    raw.reaction_conditions && typeof raw.reaction_conditions === "object"
      ? (raw.reaction_conditions as Record<string, unknown>)
      : {};
  const field = (name: string) => {
    const value = conditions[name];
    return value && value !== "N/A" ? String(value) : "";
  };
  const reagent = field("reagent") || field("base") || field("ligand");
  const catalyst = field("catalyst");
  const solvent = field("solvent");
  const temperature = field("temperature");
  const time = field("time");
  const yieldValue = field("yield");
  const lines = [
    [reagent, catalyst].filter(Boolean).join(" + ") || "Conditions",
    solvent,
    [temperature ? `${temperature} °C` : "", time].filter(Boolean).join(", "),
    yieldValue ? `Yield: ${yieldValue}%` : "",
  ].filter(Boolean);
  return {
    label: lines.join("\n"),
    procedure: field("preparation") || "No procedure provided.",
  };
}

function convertRetroNode(raw: Record<string, unknown>): RetroNode {
  const id = String(raw.id ?? crypto.randomUUID());
  const children = Array.isArray(raw.children)
    ? (raw.children as Array<Record<string, unknown>>)
    : [];
  const chemical: RetroNode = {
    id,
    type: "chemical",
    smiles: String(raw.smiles ?? ""),
    label: typeof raw.label === "string" ? raw.label : undefined,
    children: [],
  };
  if (children.length) {
    const condition = conditionLabel(raw);
    chemical.children.push({
      id: `cond_${id}`,
      type: "condition",
      label: condition.label,
      procedure: condition.procedure,
      children: children.map(convertRetroNode),
    });
  }
  return chemical;
}

export function readRetroPath(
  pathNumber: number,
  taskName = latestTaskName(),
  executionName?: string,
): RetroNode {
  if (!Number.isInteger(pathNumber) || pathNumber < 1) {
    throw new ApiError(400, "Path number must be a positive integer.");
  }
  if (!taskName) throw new ApiError(404, "No task exists.");
  if (executionName && !/^Execution_\d+$/.test(executionName)) {
    throw new ApiError(400, "Invalid retrosynthesis execution.");
  }
  const execution = executionName
    ? join(taskDir(taskName), "resources", "RetroDesTool", executionName)
    : latestExecutionDirectory(taskName, "RetroDesTool");
  if (!execution) throw new ApiError(404, "No retrosynthesis execution exists.");
  const path = join(execution, `path${pathNumber}_info.json`);
  if (!existsSync(path)) {
    throw new ApiError(404, `Retrosynthesis path ${pathNumber} does not exist.`);
  }
  return convertRetroNode(JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>);
}
