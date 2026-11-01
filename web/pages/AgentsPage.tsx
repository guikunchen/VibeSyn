import { useEffect, useMemo, useState } from "react";
import { Download, Network, Plus, Settings2, Trash2, Upload } from "lucide-react";
import type {
  AgentConfig,
  Agents,
  GraphData,
  OutputRule,
  RecipientType,
} from "../../shared/types.ts";
import { api, download, upload } from "../api.ts";
import { usePolling } from "../hooks.ts";
import AgentGraph from "../components/AgentGraph.tsx";
import { Notice } from "../components/Notice.tsx";
import { Tabs } from "../components/Tabs.tsx";

const models = [
  "gpt-4o-2024-11-20",
  "gpt-o3-2025-04-16",
  "deepseek-v3",
  "glm-4-plus",
  "gpt-5-2025-08-07",
  "llama3.3:70b-instruct-fp16",
  "deepseek-r1",
];
const recipientTypes: RecipientType[] = ["Agent", "Device", "Tool", "Human", "Self", ""];
const deviceRecipients = [
  "ExtracExecDevice",
  "ExtracOptDevice",
  "PeptidesDevice",
  "ReacExecDevice",
  "ReacOptDevice",
  "SepExecDevice",
  "SepOptDevice",
];
const toolRecipients = [
  "BayesianTool",
  "ExtracExecPhotoTool",
  "ExtracOptPhotoTool",
  "HandbookSearchTool",
  "NMRTool",
  "ReactionPhotoTool",
  "ReadJSONTool",
  "RetroDesTool",
  "RetroEvalTool",
  "SepExecPhotoTool",
  "SepOptPhotoTool",
];

function defaultAgent(): AgentConfig {
  return {
    is_memory_forgot: false,
    system_prompt: "",
    enabled: true,
    model: models[0],
    temperature: 0.5,
    background: "",
    output_format: [],
    workflow: "",
    initial_assistant_message: "",
    api_key: "",
    api_url: "",
  };
}

function recipientNames(type: RecipientType, agents: Agents): string[] {
  if (type === "Agent") return Object.keys(agents);
  if (type === "Human") return ["Human"];
  if (type === "Self") return ["Self-reflection"];
  if (type === "Device") return deviceRecipients;
  if (type === "Tool") return toolRecipients;
  return [];
}

function OutputRows({
  value,
  agents,
  onChange,
}: {
  value: OutputRule[];
  agents: Agents;
  onChange: (value: OutputRule[]) => void;
}) {
  const update = (index: number, patch: Partial<OutputRule>) => {
    const next = value.map((item, itemIndex) =>
      itemIndex === index ? { ...item, ...patch } : item,
    );
    onChange(next);
  };
  return (
    <div className="output-editor">
      <div className="subsection-title">
        <h4>Output format</h4>
        <button
          type="button"
          className="button small secondary"
          onClick={() =>
            onChange([
              ...value,
              { to: ["Agent", Object.keys(agents)[0] ?? ""], decision_type: "", format: "" },
            ])
          }
        >
          <Plus size={15} /> Add Output
        </button>
      </div>
      {value.length === 0 && <p className="field-help">No output routing rules.</p>}
      {value.map((output, index) => {
        const names = recipientNames(output.to[0], agents);
        return (
          <div className="output-row" key={index}>
            <label>
              Recipient type
              <select
                value={output.to[0]}
                onChange={(event) => {
                  const type = event.target.value as RecipientType;
                  update(index, { to: [type, recipientNames(type, agents)[0] ?? ""] });
                }}
              >
                {recipientTypes.map((type) => (
                  <option value={type} key={type || "empty"}>{type || "None"}</option>
                ))}
              </select>
            </label>
            <label>
              Recipient name
              <select
                value={output.to[1]}
                disabled={!names.length}
                onChange={(event) => update(index, { to: [output.to[0], event.target.value] })}
              >
                {!names.length && <option value="">None</option>}
                {names.map((name) => <option key={name}>{name}</option>)}
              </select>
            </label>
            <label>
              Decision type
              <input
                value={output.decision_type}
                onChange={(event) => update(index, { decision_type: event.target.value })}
              />
            </label>
            <label>
              Format specification
              <input value={output.format} onChange={(event) => update(index, { format: event.target.value })} />
            </label>
            <button
              className="icon-button danger output-delete"
              type="button"
              aria-label="Delete output"
              onClick={() => onChange(value.filter((_, itemIndex) => itemIndex !== index))}
            >
              <Trash2 size={17} />
            </button>
          </div>
        );
      })}
    </div>
  );
}

function TextOrFile({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="wide-field">
      <span className="label-with-upload">
        {label}
        <span>
          <Upload size={14} />
          Load .txt or .md
          <input
            type="file"
            accept=".txt,.md,text/plain,text/markdown"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void file.text().then(onChange);
              event.target.value = "";
            }}
          />
        </span>
      </span>
      <textarea rows={7} value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function AgentEditor({
  name,
  initial,
  agents,
  isNew = false,
  onSaved,
  onDeleted,
}: {
  name: string;
  initial: AgentConfig;
  agents: Agents;
  isNew?: boolean;
  onSaved: (agents: Agents) => void;
  onDeleted?: (agents: Agents) => void;
}) {
  const [draft, setDraft] = useState<AgentConfig>(() => structuredClone(initial));
  const [newName, setNewName] = useState(name);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => setDraft(structuredClone(initial)), [initial]);
  const set = <K extends keyof AgentConfig>(key: K, value: AgentConfig[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const updated = isNew
        ? await api<Agents>("/api/agents", {
            method: "POST",
            body: JSON.stringify({ name: newName, config: draft }),
          })
        : await api<Agents>(`/api/agents/${encodeURIComponent(name)}`, {
            method: "PUT",
            body: JSON.stringify(draft),
          });
      setNotice(isNew ? `Agent '${newName}' added.` : `Agent '${name}' updated.`);
      if (isNew) {
        setNewName("");
        setDraft(defaultAgent());
      }
      onSaved(updated);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save agent.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={isNew ? "new-agent-form" : "agent-form"}>
      {notice && <Notice tone="success" onClose={() => setNotice("")}>{notice}</Notice>}
      {error && <Notice tone="error" onClose={() => setError("")}>{error}</Notice>}
      <div className="form-grid two">
        {isNew && (
          <label>
            Agent name
            <input value={newName} onChange={(event) => setNewName(event.target.value)} />
          </label>
        )}
        <label>
          Model
          <select value={draft.model} onChange={(event) => set("model", event.target.value)}>
            {models.map((model) => <option key={model}>{model}</option>)}
          </select>
        </label>
        <label>
          Temperature
          <input
            type="number"
            min="0"
            max="2"
            step="0.1"
            value={draft.temperature}
            onChange={(event) => set("temperature", Number(event.target.value))}
          />
        </label>
      </div>
      <label className="wide-field">
        System prompt
        <textarea rows={8} value={draft.system_prompt} onChange={(event) => set("system_prompt", event.target.value)} />
      </label>
      <TextOrFile label="Background" value={draft.background} onChange={(value) => set("background", value)} />
      <TextOrFile label="Workflow" value={draft.workflow} onChange={(value) => set("workflow", value)} />
      <div className="form-grid two">
        <label>
          API key
          <input type="password" value={draft.api_key} onChange={(event) => set("api_key", event.target.value)} autoComplete="off" />
        </label>
        <label>
          API URL
          <input value={draft.api_url} onChange={(event) => set("api_url", event.target.value)} />
        </label>
      </div>
      <label className="checkbox-field">
        <input
          type="checkbox"
          checked={Boolean(draft.is_memory_forgot)}
          onChange={(event) => set("is_memory_forgot", event.target.checked)}
        />
        Forget memory after submitting to ManagerAgent
      </label>
      <OutputRows value={draft.output_format} agents={agents} onChange={(value) => set("output_format", value)} />
      <div className="button-row">
        <button className="button primary" type="button" disabled={busy} onClick={() => void save()}>
          {isNew ? <Plus size={17} /> : <Settings2 size={17} />}
          {isNew ? "Add New Agent" : "Update Agent"}
        </button>
        {!isNew && onDeleted && (
          <button
            className="button danger"
            type="button"
            disabled={busy}
            onClick={async () => {
              if (!window.confirm(`Delete '${name}'?`)) return;
              setBusy(true);
              try {
                onDeleted(await api<Agents>(`/api/agents/${encodeURIComponent(name)}`, { method: "DELETE" }));
              } catch (caught) {
                setError(caught instanceof Error ? caught.message : "Could not delete agent.");
              } finally {
                setBusy(false);
              }
            }}
          >
            <Trash2 size={17} /> Delete Agent
          </button>
        )}
      </div>
    </div>
  );
}

export default function AgentsPage() {
  const [tab, setTab] = useState<"configuration" | "graph">("configuration");
  const [agents, setAgents] = useState<Agents | null>(null);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const graph = usePolling<GraphData>(
    () => api("/api/graph?context=config"),
    tab === "graph" ? 5_000 : null,
    [tab, agents],
  );

  useEffect(() => {
    void api<Agents>("/api/agents").then(setAgents).catch((caught) =>
      setError(caught instanceof Error ? caught.message : "Could not load agents."),
    );
  }, []);

  const enabled = useMemo(
    () => (agents ? Object.entries(agents).filter(([, config]) => config.enabled).map(([name]) => name) : []),
    [agents],
  );

  if (!agents) {
    return <div className="page">{error ? <Notice tone="error">{error}</Notice> : <div className="skeleton page-skeleton" />}</div>;
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">System design</span>
          <h1>Agent Configuration</h1>
          <p>Manage agent capabilities, model settings, and workflow handoffs.</p>
        </div>
        <div className="button-row">
          <label className="button secondary file-button">
            <Upload size={17} /> Import Configuration
            <input
              type="file"
              accept=".zip,application/zip"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) {
                  void upload<Agents>("/api/config/import", file).then(setAgents).catch((caught) =>
                    setError(caught instanceof Error ? caught.message : "Import failed."),
                  );
                }
                event.target.value = "";
              }}
            />
          </label>
          <button className="button secondary" onClick={() => download("/api/config/export")}>
            <Download size={17} /> Export Configuration
          </button>
        </div>
      </header>
      {error && <Notice tone="error" onClose={() => setError("")}>{error}</Notice>}
      <Tabs
        value={tab}
        onChange={setTab}
        options={[
          { id: "configuration", label: "Agent Configuration", icon: <Settings2 size={16} /> },
          { id: "graph", label: "Agent Graph", icon: <Network size={16} /> },
        ]}
      />
      {tab === "graph" ? (
        <section className="panel">
          {graph.error ? <Notice tone="error">{graph.error}</Notice> : graph.data ? <AgentGraph graph={graph.data} /> : <div className="skeleton graph-skeleton" />}
        </section>
      ) : (
        <>
          <section className="panel">
            <div className="section-heading">
              <div>
                <h2>Enabled Agents</h2>
                <p>Select which agents may participate in workflows.</p>
              </div>
              <span className="count-badge">{enabled.length} enabled</span>
            </div>
            <div className="agent-toggles">
              {Object.entries(agents).map(([name, config]) => (
                <label key={name} className={config.enabled ? "enabled" : ""}>
                  <input
                    type="checkbox"
                    checked={config.enabled}
                    onChange={async (event) => {
                      const names = event.target.checked
                        ? [...enabled, name]
                        : enabled.filter((item) => item !== name);
                      try {
                        setAgents(await api<Agents>("/api/agents/enabled", {
                          method: "PUT",
                          body: JSON.stringify({ names }),
                        }));
                      } catch (caught) {
                        setError(caught instanceof Error ? caught.message : "Could not update enabled agents.");
                      }
                    }}
                  />
                  <span>{name}</span>
                </label>
              ))}
            </div>
          </section>
          <section className="panel">
            <div className="section-heading">
              <div>
                <h2>Agent Details</h2>
                <p>Open an agent to edit its complete configuration.</p>
              </div>
            </div>
            <div className="accordion-list">
              {Object.entries(agents).map(([name, config]) => (
                <details
                  key={name}
                  open={expanded === name}
                  onToggle={(event) => {
                    if ((event.currentTarget as HTMLDetailsElement).open) setExpanded(name);
                    else if (expanded === name) setExpanded(null);
                  }}
                >
                  <summary>
                    <span><i className={config.enabled ? "online-dot" : "offline-dot"} />{name}</span>
                    <small>{config.model}</small>
                  </summary>
                  <AgentEditor
                    name={name}
                    initial={config}
                    agents={agents}
                    onSaved={setAgents}
                    onDeleted={setAgents}
                  />
                </details>
              ))}
            </div>
          </section>
          <section className="panel">
            <div className="section-heading">
              <div><h2>Add New Agent</h2><p>Create an agent and its first output rules.</p></div>
            </div>
            <AgentEditor name="" initial={defaultAgent()} agents={agents} isNew onSaved={setAgents} />
          </section>
        </>
      )}
    </div>
  );
}
