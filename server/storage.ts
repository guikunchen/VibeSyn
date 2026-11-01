import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  renameSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { strFromU8, strToU8, unzipSync, zipSync } from "fflate";
import type {
  AgentConfig,
  Agents,
  GraphData,
  ResourceMeta,
  TaskMessage,
  TaskMessageView,
  TaskRecord,
  TaskView,
} from "../shared/types.ts";
import { ApiError } from "./errors.ts";

export const ROOT = resolve(import.meta.dir, "..");
export const AGENTS_FILE = join(ROOT, "src/chem_main/agents.json");
export const HISTORY_DIR = join(ROOT, "history_files");
export const TASKS_DIR = join(HISTORY_DIR, "tasks");
export const DELETED_TASKS_DIR = join(HISTORY_DIR, "deleted_tasks");
export const TMP_DIR = join(HISTORY_DIR, "tmp");
export const ICONS_DIR = join(ROOT, "src/chem_main/resource/agent_icons");

export function initializeRuntimeDirectories(): void {
  for (const path of [TASKS_DIR, DELETED_TASKS_DIR, TMP_DIR]) {
    mkdirSync(path, { recursive: true });
  }
}

export function readJson<T>(path: string): T {
  return JSON.parse(readFileSync(path, "utf8")) as T;
}

export function writeJson(path: string, value: unknown): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

export function readAgents(): Agents {
  return readJson<Agents>(AGENTS_FILE);
}

export function writeAgents(agents: Agents): void {
  writeJson(AGENTS_FILE, agents);
}

function assertAgentConfig(config: AgentConfig): void {
  if (!config || typeof config !== "object") {
    throw new ApiError(400, "Agent configuration is malformed.");
  }
  const stringFields = [
    config.system_prompt,
    config.model,
    config.background,
    config.workflow,
    config.api_key,
    config.api_url,
  ];
  const validOutputs =
    Array.isArray(config.output_format) &&
    config.output_format.every(
      (output) =>
        Array.isArray(output.to) &&
        output.to.length === 2 &&
        output.to.every((value) => typeof value === "string") &&
        typeof output.decision_type === "string" &&
        typeof output.format === "string",
    );
  if (
    stringFields.some((value) => typeof value !== "string") ||
    typeof config.enabled !== "boolean" ||
    typeof config.temperature !== "number" ||
    !Number.isFinite(config.temperature) ||
    !validOutputs
  ) {
    throw new ApiError(400, "Agent configuration is malformed.");
  }
}

export function setEnabledAgents(names: string[]): Agents {
  if (!Array.isArray(names) || names.some((name) => typeof name !== "string")) {
    throw new ApiError(400, "Enabled agent names must be strings.");
  }
  const agents = readAgents();
  const unknown = names.find((name) => !agents[name]);
  if (unknown) throw new ApiError(400, `Agent '${unknown}' does not exist.`);
  const requested = new Set(names);
  for (const [name, config] of Object.entries(agents)) {
    config.enabled = requested.has(name);
  }
  writeAgents(agents);
  return agents;
}

export function createAgent(name: string, config: AgentConfig): Agents {
  if (typeof name !== "string" || !config || typeof config !== "object") {
    throw new ApiError(400, "Agent name and configuration are required.");
  }
  const cleanName = name.trim();
  if (!cleanName) {
    throw new ApiError(400, "Agent name is required.");
  }
  const agents = readAgents();
  if (agents[cleanName]) {
    throw new ApiError(409, `Agent '${cleanName}' already exists.`);
  }
  assertAgentConfig(config);
  agents[cleanName] = config;
  writeAgents(agents);
  return agents;
}

export function updateAgent(name: string, config: AgentConfig): Agents {
  if (!config || typeof config !== "object") {
    throw new ApiError(400, "Agent configuration is required.");
  }
  const agents = readAgents();
  if (!agents[name]) {
    throw new ApiError(404, `Agent '${name}' does not exist.`);
  }
  assertAgentConfig(config);
  agents[name] = config;
  writeAgents(agents);
  return agents;
}

export function deleteAgent(name: string): Agents {
  const agents = readAgents();
  if (!agents[name]) {
    throw new ApiError(404, `Agent '${name}' does not exist.`);
  }
  delete agents[name];
  writeAgents(agents);
  return agents;
}

function category(name: string): "manager" | "agent" | "device" | "tool" | "other" {
  if (name === "ManagerAgent") return "manager";
  if (name.endsWith("Agent")) return "agent";
  if (name.endsWith("Device")) return "device";
  if (name.endsWith("Tool")) return "tool";
  return "other";
}

export function buildAgentGraph(highlighted?: string): GraphData {
  const agents = readAgents();
  const enabled = Object.entries(agents).filter(([, config]) => config.enabled);
  const enabledNames = new Set(enabled.map(([name]) => name));
  const names = new Set<string>();
  const pairs = new Set<string>();

  for (const [source, config] of enabled) {
    for (const output of config.output_format) {
      const targetType = output.to?.[0];
      const target = output.to?.[1];
      if (!target || (targetType === "Agent" && !enabledNames.has(target))) continue;
      names.add(source);
      names.add(target);
      pairs.add(`${source}\0${target}`);
    }
  }

  const nodes = [...names].map((name) => ({
    id: name,
    label: name,
    category: category(name),
    highlighted: name === highlighted,
  }));
  const edges: GraphData["edges"] = [];
  for (const pair of pairs) {
    const [source, target] = pair.split("\0");
    edges.push({
      id: `out-${source}-${target}`,
      source,
      target,
      dashed: true,
    });
    edges.push({
      id: `return-${target}-${source}`,
      source: target,
      target: source,
      dashed: false,
    });
  }
  return { nodes, edges };
}

function assertTaskName(name: string): string {
  if (!name || name.includes("/") || name.includes("\\") || name === "." || name === "..") {
    throw new ApiError(400, "Invalid task name.");
  }
  return name;
}

export function taskDir(name: string): string {
  return join(TASKS_DIR, assertTaskName(name));
}

export function taskFile(name: string): string {
  return join(taskDir(name), "task.json");
}

export function listTasks(): Array<{ name: string; modifiedAt: string; status: string }> {
  return readdirSync(TASKS_DIR, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && existsSync(join(TASKS_DIR, entry.name, "task.json")))
    .map((entry) => {
      const path = join(TASKS_DIR, entry.name, "task.json");
      const task = readJson<TaskRecord>(path);
      return {
        name: entry.name,
        modifiedAt: statSync(join(TASKS_DIR, entry.name)).mtime.toISOString(),
        status: task.task_status,
      };
    })
    .sort((a, b) => b.modifiedAt.localeCompare(a.modifiedAt));
}

export function latestTaskName(): string | null {
  return listTasks()[0]?.name ?? null;
}

export function readTask(name: string): TaskRecord {
  const path = taskFile(name);
  if (!existsSync(path)) {
    throw new ApiError(404, `Task '${name}' does not exist.`);
  }
  return readJson<TaskRecord>(path);
}

export function writeTask(task: TaskRecord): void {
  writeJson(taskFile(task.task_name), task);
}

function iconUrl(name?: string): string | undefined {
  if (!name) return undefined;
  const fileName = basename(name);
  return existsSync(join(ICONS_DIR, `${fileName}.png`))
    ? `/assets/icons/${encodeURIComponent(fileName)}.png`
    : "/assets/home.png";
}

function resourceKind(path: string): ResourceMeta["kind"] {
  const lowered = path.toLowerCase();
  if (/\.(png|jpe?g|gif|webp|svg)$/.test(lowered)) return "image";
  if (lowered.endsWith(".txt")) return "text";
  if (lowered.endsWith(".json")) return "json";
  return "file";
}

export function resourceMeta(taskName: string, sourcePath: string): ResourceMeta | null {
  const base = taskDir(taskName);
  const normalized = sourcePath.replaceAll("\\", "/");
  const resourceIndex = normalized.lastIndexOf("/resources/");
  const taskLocalPath = resourceIndex >= 0
    ? normalized.slice(resourceIndex + 1)
    : normalized.startsWith("resources/")
      ? normalized
      : null;
  if (!taskLocalPath) return null;
  const absolute = resolve(base, taskLocalPath);
  const local = relative(base, absolute);
  if (local.startsWith("..") || isAbsolute(local)) return null;
  return {
    name: basename(absolute),
    path: local.split(sep).join("/"),
    url: `/api/resources/${encodeURIComponent(taskName)}?path=${encodeURIComponent(local.split(sep).join("/"))}`,
    kind: resourceKind(absolute),
  };
}

function messageType(message: TaskMessage, next?: TaskMessage): string {
  const taskType = message.task_type ?? "unknown";
  const mapping: Record<string, string> = {
    "send task to others": "Task Assignment",
    "tool or device send feedback": "Feedback",
    "agent send back": "Conclusion",
    "self reflection": "Self Reflection",
    completed: "Completion",
  };
  if (taskType !== "agent next step") {
    return mapping[taskType] ?? taskType.replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  const content =
    typeof message.task_content === "object" && message.task_content
      ? message.task_content
      : {};
  const results = content.results;
  if (results != null && String(results).toLowerCase() !== "none") return "Conclusion";
  if (next?.task_type === "send task to others") {
    const nextContent =
      typeof next.task_content === "object" && next.task_content ? next.task_content : {};
    const sender = String(nextContent.sender ?? "");
    const recipient = String(nextContent.recipient ?? "");
    const senderConfig = readAgents()[sender];
    const rule = senderConfig?.output_format.find((item) => item.to?.[1] === recipient);
    return rule?.decision_type || "Task Assignment";
  }
  if (next?.task_type === "self reflection") return "Self Reflection";
  return "Waiting for Next Step";
}

function contentText(message: TaskMessage): string {
  if (message.role === "user" && message.task_content === undefined) {
    return message.content ?? "";
  }
  if (message.task_type === "completed") {
    return typeof message.task_content === "string"
      ? message.task_content
      : JSON.stringify(message.task_content ?? "", null, 2);
  }
  const content =
    typeof message.task_content === "object" && message.task_content
      ? message.task_content
      : {};
  for (const key of ["task", "feedback", "results"]) {
    const value = content[key];
    if (value === undefined || value === null || String(value).toLowerCase() === "none") continue;
    if (typeof value === "string") {
      if (
        key === "task" &&
        typeof content.recipient === "string" &&
        (content.recipient.endsWith("Tool") || content.recipient.endsWith("Device"))
      ) {
        return `Send to ${content.recipient}\n\n${value}`;
      }
      return value.replaceAll("•", "-");
    }
    return `\`\`\`json\n${JSON.stringify(value, null, 2)}\n\`\`\``;
  }
  return `ERROR: ${JSON.stringify(content)}`;
}

function messageResources(taskName: string, message: TaskMessage): ResourceMeta[] {
  if (message.task_type !== "tool or device send feedback") return [];
  const content =
    typeof message.task_content === "object" && message.task_content
      ? message.task_content
      : {};
  const sender = String(content.sender ?? "");
  if (sender === "RetroDesTool") return [];
  const paths = message.waiting_info?.[sender]?.resource_paths ?? [];
  return paths
    .map((path) => resourceMeta(taskName, path))
    .filter((item): item is ResourceMeta => item !== null);
}

function retroPathBaseUrl(taskName: string, message: TaskMessage): string | undefined {
  if (message.task_type !== "tool or device send feedback") return undefined;
  const content =
    typeof message.task_content === "object" && message.task_content
      ? message.task_content
      : {};
  if (content.sender !== "RetroEvalTool") return undefined;
  const rawTask = message.waiting_info?.RetroEvalTool?.task;
  const task = typeof rawTask === "string" ? JSON.parse(rawTask) as Record<string, unknown> : rawTask;
  if (!task || typeof task !== "object" || !("folder" in task)) return undefined;
  const match = String(task.folder).match(/^resources\/RetroDesTool\/(Execution_\d+)$/);
  if (!match) return undefined;
  return `/api/tasks/${encodeURIComponent(taskName)}/retro/${encodeURIComponent(match[1])}`;
}

export function taskMessages(task: TaskRecord): TaskMessageView[] {
  const views: TaskMessageView[] = [];
  for (let rawIndex = 0; rawIndex < task.messages.length; rawIndex += 1) {
    const message = task.messages[rawIndex];
    if (
      rawIndex > 0 &&
      message.task_type !== "completed" &&
      task.messages[rawIndex - 1]?.task_type === "agent next step" &&
      message.task_type !== "agent next step"
    ) {
      continue;
    }
    const content =
      typeof message.task_content === "object" && message.task_content
        ? message.task_content
        : {};
    const rawSender = String(content.sender ?? "") || undefined;
    const sender = rawSender === "User" ? "Human" : rawSender;
    const recipient = String(content.recipient ?? "") || undefined;
    views.push({
      rawIndex,
      displayIndex: views.length,
      time: message.time,
      type: message.role === "user" && !message.task_content ? "Narration" : messageType(message, task.messages[rawIndex + 1]),
      sender,
      recipient,
      senderIcon: iconUrl(sender),
      recipientIcon: iconUrl(recipient),
      content: contentText(message),
      rawContent: JSON.stringify(message.task_content ?? {}, null, 2),
      isNarration:
        (message.role === "user" && message.task_content === undefined) ||
        message.task_type === "completed",
      resources: messageResources(task.task_name, message),
      retroPathBaseUrl: retroPathBaseUrl(task.task_name, message),
      editable: task.task_status === "paused" && message.task_type === "agent next step",
      deletable:
        (task.task_status === "paused" || task.task_status === "completed") &&
        views.length >= 2,
    });
  }
  return views;
}

export function taskView(name: string): TaskView {
  const task = readTask(name);
  return { task, messages: taskMessages(task) };
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function taskTimestamp(date = new Date()): string {
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(
    date.getHours(),
  )}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

export function createTask(displayName: string, description: string): TaskView {
  if (typeof displayName !== "string" || typeof description !== "string") {
    throw new ApiError(400, "Task name and description must be strings.");
  }
  const normalizedName = displayName.trim().replaceAll(" ", "_");
  if (!normalizedName || !description.trim()) {
    throw new ApiError(400, "Task name and description are required.");
  }
  if (normalizedName.includes("/") || normalizedName.includes("\\")) {
    throw new ApiError(400, "Task name cannot contain path separators.");
  }
  const name = `T-${taskTimestamp()}-${normalizedName}`;
  if (existsSync(taskDir(name))) {
    throw new ApiError(409, "Task name already exists.");
  }
  const now = new Date();
  const time = `C-${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}-${pad(
    now.getHours(),
  )}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  const task: TaskRecord = {
    task_name: name,
    task_description: description,
    messages: [
      { role: "user", time, content: "Synthesis process start!" },
      {
        role: "assistant",
        time,
        task_type: "send task to others",
        task_content: {
          recipient: "ManagerAgent",
          task: description,
          results: null,
          sender: "User",
        },
      },
    ],
    task_status: "paused",
    cur_task_type: "send task to others",
    cur_task_content: {
      sender: "Human",
      recipient: "ManagerAgent",
      task: description,
    },
    current_agent: "ManagerAgent",
  };
  writeTask(task);
  return { task, messages: taskMessages(task) };
}

export function continueTask(name: string): {
  task: TaskView;
  requiresEndpoint: boolean;
  target?: string;
} {
  const task = readTask(name);
  if (task.task_status !== "paused") {
    throw new ApiError(409, "Only a paused task can continue.");
  }
  if (
    task.cur_task_type === "waiting tool or device" ||
    task.cur_task_type === "tool or device send feedback"
  ) {
    const target = String(
      task.cur_task_content.recipient ?? task.cur_task_content.sender ?? "",
    );
    return { task: { task, messages: taskMessages(task) }, requiresEndpoint: true, target };
  }
  task.task_status = "waiting for server process";
  writeTask(task);
  return {
    task: { task, messages: taskMessages(task) },
    requiresEndpoint: false,
  };
}

export function stopTask(name: string): TaskView {
  const task = readTask(name);
  task.task_status = "paused";
  writeTask(task);
  return { task, messages: taskMessages(task) };
}

export function submitHumanResponse(name: string, response: string): TaskView {
  if (typeof response !== "string") throw new ApiError(400, "Human response must be text.");
  if (!response.trim()) throw new ApiError(400, "Human response is required.");
  const task = readTask(name);
  const human = task.waiting_info?.Human;
  if (task.cur_task_type !== "waiting tool or device" || !human || !Object.keys(human).length) {
    throw new ApiError(409, "Human input is not required for this task.");
  }
  human.results = response;
  task.task_status = "waiting for server process";
  writeTask(task);
  return { task, messages: taskMessages(task) };
}

export function editTaskMessage(name: string, rawIndex: number, value: string): TaskView {
  if (!Number.isInteger(rawIndex) || typeof value !== "string") {
    throw new ApiError(400, "A valid message index and JSON content are required.");
  }
  const task = readTask(name);
  const message = task.messages[rawIndex];
  if (!message) throw new ApiError(404, "Message does not exist.");
  if (task.task_status !== "paused") {
    throw new ApiError(409, "Cannot edit a task that is not paused.");
  }
  if (message.task_type !== "agent next step") {
    throw new ApiError(409, "Cannot edit a task step that has already completed.");
  }
  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(value) as Record<string, unknown>;
  } catch {
    throw new ApiError(400, "Message content must be valid JSON.");
  }
  message.task_content = parsed;
  task.cur_task_content = parsed;
  writeTask(task);
  return { task, messages: taskMessages(task) };
}

function restoreTaskState(task: TaskRecord): TaskRecord {
  const last = task.messages.at(-1);
  if (!last || !last.task_type || typeof last.task_content !== "object" || !last.task_content) {
    throw new ApiError(409, "Task history cannot be rolled back further.");
  }
  task.task_status = "paused";
  task.cur_task_type = last.task_type;
  task.cur_task_content = last.task_content.sender === "User"
    ? { ...last.task_content, sender: "Human" }
    : last.task_content;
  task.waiting_info = last.waiting_info;
  delete task.final_results;

  const sender = String(last.task_content.sender ?? "");
  const recipient = String(last.task_content.recipient ?? "");
  task.current_agent = sender.endsWith("Agent")
    ? sender
    : recipient.endsWith("Agent")
      ? recipient
      : sender || recipient;
  return task;
}

interface AgentHistory {
  messages?: unknown[];
  previous_memory?: unknown[][];
  [key: string]: unknown;
}

function removeAgentInvocation(histories: Record<string, AgentHistory>, agent: string): void {
  const messages = histories[agent]?.messages;
  if (!messages || messages.length < 2) {
    throw new ApiError(409, `Saved memory for '${agent}' cannot be rolled back.`);
  }
  histories[agent].messages = messages.slice(0, -2);
}

function restoreForgottenSender(
  histories: Record<string, AgentHistory>,
  transition: TaskMessage | undefined,
): void {
  if (transition?.task_type !== "agent send back") return;
  const content =
    typeof transition.task_content === "object" && transition.task_content
      ? transition.task_content
      : {};
  const sender = String(content.sender ?? "");
  if (!sender.endsWith("Agent")) return;

  const history = histories[sender];
  const archived = history?.previous_memory?.at(-1);
  if (history?.messages?.length !== 2) return;
  if (!archived) {
    throw new ApiError(409, `Saved memory for '${sender}' cannot be restored.`);
  }
  history.messages = archived;
  history.previous_memory = history.previous_memory!.slice(0, -1);
}

export function deleteTaskMessage(name: string, rawIndex: number): TaskView {
  const task = readTask(name);
  if (task.task_status !== "paused" && task.task_status !== "completed") {
    throw new ApiError(409, "Pause the task before deleting a message.");
  }
  const views = taskMessages(task);
  const selected = views.find((view) => view.rawIndex === rawIndex);
  if (!selected) throw new ApiError(404, "Message does not exist.");
  if (selected.displayIndex !== views.length - 1) {
    throw new ApiError(409, "Only the latest message can be deleted.");
  }
  if (selected.displayIndex < 2) {
    throw new ApiError(409, "The first two messages cannot be deleted.");
  }

  const historyPath = join(taskDir(name), "all_agent_history.json");
  const histories = existsSync(historyPath)
    ? readJson<Record<string, AgentHistory>>(historyPath)
    : {};

  const selectedMessage = task.messages[selected.rawIndex];
  const transition = task.messages[selected.rawIndex - 1];
  if (selectedMessage.task_type === "agent next step") {
    const content =
      typeof selectedMessage.task_content === "object" && selectedMessage.task_content
        ? selectedMessage.task_content
        : {};
    const sender = String(content.sender ?? "");
    if (!sender.endsWith("Agent")) {
      throw new ApiError(409, "Unexpected task history state.");
    }
    restoreForgottenSender(histories, transition);
    removeAgentInvocation(histories, sender);
  }

  task.messages = task.messages.slice(0, selected.rawIndex);
  restoreTaskState(task);
  writeTask(task);
  if (existsSync(historyPath) || Object.keys(histories).length > 0) {
    writeJson(historyPath, histories);
  }
  return { task, messages: taskMessages(task) };
}

export function deleteTask(name: string): void {
  const source = taskDir(name);
  if (!existsSync(source)) throw new ApiError(404, `Task '${name}' does not exist.`);
  if (readTask(name).task_status === "waiting for server process") {
    throw new ApiError(409, "Pause the task before deleting it.");
  }
  const destination = join(DELETED_TASKS_DIR, name);
  if (existsSync(destination)) {
    throw new ApiError(409, `Deleted task '${name}' already exists.`);
  }
  renameSync(source, destination);
}

function filesBelow(directory: string): Record<string, Uint8Array> {
  const files: Record<string, Uint8Array> = {};
  const walk = (current: string) => {
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      const path = join(current, entry.name);
      if (entry.isDirectory()) walk(path);
      else if (entry.isFile()) {
        files[relative(dirname(directory), path).split(sep).join("/")] = readFileSync(path);
      }
    }
  };
  walk(directory);
  return files;
}

export function exportTaskZip(name: string): Uint8Array {
  const directory = taskDir(name);
  if (!existsSync(directory)) throw new ApiError(404, `Task '${name}' does not exist.`);
  return zipSync(filesBelow(directory), { level: 6 });
}

function safeArchivePath(path: string): boolean {
  return (
    path.length > 0 &&
    !path.startsWith("/") &&
    !path.startsWith("\\") &&
    !path.split(/[\\/]/).includes("..")
  );
}

function unzipArchive(bytes: Uint8Array): Record<string, Uint8Array> {
  try {
    return unzipSync(bytes);
  } catch {
    throw new ApiError(400, "Uploaded file is not a valid ZIP archive.");
  }
}

export function importTaskZip(bytes: Uint8Array): TaskView {
  const files = unzipArchive(bytes);
  const entries = Object.entries(files);
  for (const [path] of entries) {
    if (!safeArchivePath(path)) throw new ApiError(400, "ZIP contains an invalid path.");
  }
  const taskEntry = entries.find(([path]) => path === "task.json" || path.endsWith("/task.json"));
  if (!taskEntry) throw new ApiError(400, "ZIP does not contain task.json.");
  let task: TaskRecord;
  try {
    task = JSON.parse(strFromU8(taskEntry[1])) as TaskRecord;
  } catch {
    throw new ApiError(400, "task.json is not valid JSON.");
  }
  if (
    !task ||
    typeof task.task_name !== "string" ||
    typeof task.task_description !== "string" ||
    !Array.isArray(task.messages) ||
    typeof task.task_status !== "string" ||
    typeof task.cur_task_type !== "string" ||
    !task.cur_task_content ||
    typeof task.cur_task_content !== "object" ||
    Array.isArray(task.cur_task_content)
  ) {
    throw new ApiError(400, "task.json does not contain a valid task record.");
  }
  assertTaskName(task.task_name);
  const destination = taskDir(task.task_name);
  if (existsSync(destination)) {
    throw new ApiError(409, `Task '${task.task_name}' already exists.`);
  }
  const prefix = taskEntry[0].slice(0, -"task.json".length);
  mkdirSync(destination, { recursive: true });
  for (const [archivePath, data] of entries) {
    if (archivePath.endsWith("/")) continue;
    const local = prefix && archivePath.startsWith(prefix)
      ? archivePath.slice(prefix.length)
      : archivePath;
    if (!local) continue;
    const output = resolve(destination, local);
    const inside = relative(destination, output);
    if (inside.startsWith("..") || isAbsolute(inside)) {
      throw new ApiError(400, "ZIP contains an invalid path.");
    }
    mkdirSync(dirname(output), { recursive: true });
    writeFileSync(output, data);
  }
  return taskView(task.task_name);
}

export function exportConfigZip(): Uint8Array {
  return zipSync({ "agents.json": strToU8(JSON.stringify(readAgents(), null, 2)) }, { level: 6 });
}

export function importConfigZip(bytes: Uint8Array): Agents {
  const files = unzipArchive(bytes);
  const entry = Object.entries(files).find(([path]) => basename(path) === "agents.json");
  if (!entry) throw new ApiError(400, "ZIP does not contain agents.json.");
  let agents: Agents;
  try {
    agents = JSON.parse(strFromU8(entry[1])) as Agents;
  } catch {
    throw new ApiError(400, "agents.json is not valid JSON.");
  }
  if (!agents || Array.isArray(agents) || typeof agents !== "object") {
    throw new ApiError(400, "agents.json must contain an object.");
  }
  for (const config of Object.values(agents)) assertAgentConfig(config);
  writeAgents(agents);
  return agents;
}

export function readResource(taskName: string, parts: string[]): string {
  const base = taskDir(taskName);
  const output = resolve(base, ...parts);
  const inside = relative(base, output);
  if (inside.startsWith("..") || isAbsolute(inside)) {
    throw new ApiError(400, "Invalid resource path.");
  }
  if (!existsSync(output) || !statSync(output).isFile()) {
    throw new ApiError(404, "Resource does not exist.");
  }
  return output;
}
