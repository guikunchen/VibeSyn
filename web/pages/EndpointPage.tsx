import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  Beaker,
  Cable,
  Database,
  FlaskConical,
  Gauge,
  RefreshCw,
  Save,
  Send,
  Settings,
  Wrench,
} from "lucide-react";
import type {
  DeviceStatus,
  EndpointConfig,
  EndpointDescriptor,
  EndpointKind,
  EndpointState,
  RetroNode,
} from "../../shared/types.ts";
import { api } from "../api.ts";
import { usePolling } from "../hooks.ts";
import { Notice } from "../components/Notice.tsx";
import ResourceView from "../components/ResourceView.tsx";
import RetroGraph from "../components/RetroGraph.tsx";
import { Tabs, type TabOption } from "../components/Tabs.tsx";

type EndpointTab = "interaction" | "status" | "settings";

function StatusTimeline({ status }: { status: DeviceStatus }) {
  if (!status.timeline.length) return <div className="empty-inline">No timeline data available.</div>;
  const starts = status.timeline.map((segment) => new Date(segment.start).getTime());
  const finishes = status.timeline.map((segment) => new Date(segment.finish).getTime());
  const min = Math.min(...starts);
  const max = Math.max(...finishes);
  const range = max - min || 1;
  const colors = ["#08a9d8", "#75b943", "#f5a33b", "#f15b43", "#7a83d8"];
  return (
    <div className="timeline">
      {status.timeline.map((segment, index) => {
        const left = ((new Date(segment.start).getTime() - min) / range) * 100;
        const width = Math.max(2, ((new Date(segment.finish).getTime() - new Date(segment.start).getTime()) / range) * 100);
        return (
          <div className="timeline-row" key={`${segment.operation}-${segment.start}`}>
            <strong>{segment.operation}</strong>
            <div>
              <span
                style={{
                  left: `${left}%`,
                  width: `${width}%`,
                  background: colors[index % colors.length],
                }}
                title={`${segment.start} – ${segment.finish}`}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function EndpointInteraction({
  kind,
  name,
  state,
  onChange,
}: {
  kind: EndpointKind;
  name: string;
  state: EndpointState;
  onChange: (state: EndpointState) => void;
}) {
  const [input, setInput] = useState(state.taskInput ?? "");
  const [feedback, setFeedback] = useState(state.result ?? "");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [pathNumber, setPathNumber] = useState(1);
  const [retro, setRetro] = useState<RetroNode | null>(null);
  const [retroError, setRetroError] = useState("");

  useEffect(() => setInput(state.taskInput ?? ""), [state.taskInput]);
  useEffect(() => setFeedback(state.result ?? ""), [state.result]);
  useEffect(() => {
    if (!state.descriptor.supportsRetroPaths || state.retroPathCount < 1) {
      setRetro(null);
      return;
    }
    void api<RetroNode>(`/api/endpoints/tools/RetroDesTool/retro/${pathNumber}`)
      .then((data) => {
        setRetro(data);
        setRetroError("");
      })
      .catch((caught) => {
        setRetro(null);
        setRetroError(caught instanceof Error ? caught.message : "Could not load retrosynthesis path.");
      });
  }, [state.descriptor.supportsRetroPaths, state.retroPathCount, pathNumber]);

  const post = async (suffix: "dispatch" | "feedback", body: object) => {
    setBusy(true);
    setError("");
    try {
      const updated = await api<EndpointState>(
        `/api/endpoints/${kind}/${encodeURIComponent(name)}/${suffix}`,
        { method: "POST", body: JSON.stringify(body) },
      );
      onChange(updated);
      setNotice(suffix === "dispatch" ? `Task sent to ${name}.` : "Results sent back.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Request failed.");
    } finally {
      setBusy(false);
    }
  };

  const visibleResources = state.resources.filter(
    (resource) => !(state.descriptor.supportsRetroPaths && /^path\d+_info\.json$/.test(resource.name)),
  );
  return (
    <div className="endpoint-stack">
      {error && <Notice tone="error" onClose={() => setError("")}>{error}</Notice>}
      {notice && <Notice tone="success" onClose={() => setNotice("")}>{notice}</Notice>}
      <section className="subpanel">
        <div className="section-heading">
          <div><h2>{kind === "devices" ? "Device" : "Tool"} Interaction</h2><p>Review and dispatch the current pending JSON task.</p></div>
          <span className={`status-pill ${state.taskStatus?.replaceAll(" ", "-") ?? ""}`}>{state.taskStatus ?? "No task"}</span>
        </div>
        <label className="wide-field">
          Enter task data in JSON format
          <textarea rows={9} value={input} onChange={(event) => setInput(event.target.value)} placeholder="No pending task" />
        </label>
        <button
          className="button primary wide-button"
          disabled={busy || state.taskInput === null}
          onClick={() => void post("dispatch", { input })}
        >
          <Send size={17} /> Send Task
        </button>
      </section>
      {state.result !== null && (
        <section className="subpanel result-panel">
          <div className="section-heading">
            <div><h2>Task Results</h2><p>The task completed and is ready to return to the workflow.</p></div>
            <span className="success-badge">Completed</span>
          </div>
          <label className="wide-field">
            Task result
            <textarea
              rows={state.descriptor.resultRows}
              value={feedback}
              onChange={(event) => setFeedback(event.target.value)}
            />
          </label>
          <button className="button primary" disabled={busy} onClick={() => void post("feedback", { feedback })}>
            <Send size={17} /> Send Back
          </button>
        </section>
      )}
      {visibleResources.length > 0 && (
        <section className="subpanel">
          <div className="section-heading"><div><h2>Latest Resources</h2><p>Files generated by the latest execution.</p></div></div>
          <div className="resource-grid large">
            {visibleResources.map((resource) => <ResourceView key={resource.path} resource={resource} />)}
          </div>
        </section>
      )}
      {state.descriptor.supportsRetroPaths && state.retroPathCount > 0 && (
        <section className="subpanel">
          <div className="section-heading">
            <div><h2>Retrosynthesis Pathway</h2><p>Select a route and inspect its chemical conditions.</p></div>
            <label className="inline-field">
              Path
              <input
                type="number"
                min="1"
                max={state.retroPathCount}
                value={pathNumber}
                onChange={(event) => setPathNumber(Number(event.target.value))}
              />
            </label>
          </div>
          {retroError ? <Notice tone="error">{retroError}</Notice> : retro ? <RetroGraph root={retro} /> : <div className="skeleton graph-skeleton" />}
        </section>
      )}
    </div>
  );
}

function EndpointStatus({
  name,
  descriptor,
}: {
  name: string;
  descriptor: EndpointDescriptor;
}) {
  const [taskId, setTaskId] = useState("");
  const [retrieving, setRetrieving] = useState(false);
  const [status, setStatus] = useState<DeviceStatus | null>(null);
  const [error, setError] = useState("");

  const retrieve = async () => {
    if (!taskId.trim()) return;
    try {
      setError("");
      setStatus(
        await api<DeviceStatus>(
          `/api/endpoints/devices/${encodeURIComponent(name)}/status?taskId=${encodeURIComponent(taskId)}`,
        ),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not query device status.");
    }
  };

  useEffect(() => {
    if (!retrieving || !taskId.trim()) return;
    void retrieve();
    const timer = window.setInterval(() => void retrieve(), 60_000);
    return () => window.clearInterval(timer);
  }, [retrieving, taskId, name]);

  if (!descriptor.supportsMongo) {
    return (
      <div className="empty-state"><Gauge size={30} /><h3>Tool Status Information</h3><p>This tool does not publish a status timeline.</p></div>
    );
  }
  return (
    <div className="endpoint-stack">
      {error && <Notice tone="error" onClose={() => setError("")}>{error}</Notice>}
      <section className="subpanel">
        <div className="section-heading"><div><h2>Status Dashboard</h2><p>Query device operations for a RunningTaskId.</p></div></div>
        <div className="status-query">
          <label>
            RunningTaskId
            <input value={taskId} onChange={(event) => setTaskId(event.target.value)} placeholder="T-20250327-000000-task-1" />
          </label>
          <label className="switch-field">
            <input type="checkbox" checked={retrieving} onChange={(event) => setRetrieving(event.target.checked)} />
            <span />
            Retrieving Status
          </label>
          <button className="button secondary" disabled={!taskId.trim()} onClick={() => void retrieve()}>
            <RefreshCw size={17} /> Retrieve Now
          </button>
        </div>
      </section>
      {status && (
        <>
          {status.device_status === "error" && <Notice tone="error">{status.error ?? "MongoDB query failed."}</Notice>}
          <section className="metric-grid">
            <div className="metric-card"><span>Device Status</span><strong>{status.device_status}</strong></div>
            <div className="metric-card"><span>Latest Record</span><strong>{String(status.latest_record.time ?? "N.A.")}</strong></div>
            {descriptor.metricFields.map((metric) => (
              <div className="metric-card" key={metric.key}>
                <span>{metric.label}</span>
                <strong>
                  {status.latest_record[metric.key] === undefined
                    ? "N.A."
                    : `${String(status.latest_record[metric.key])}${metric.unit ?? ""}`}
                </strong>
              </div>
            ))}
          </section>
          <section className="subpanel">
            <div className="section-heading"><div><h2>Operation Timeline</h2><p>{status.total_records} database records.</p></div></div>
            <StatusTimeline status={status} />
          </section>
        </>
      )}
      {!status && <div className="empty-state"><Activity size={30} /><h3>No status query running</h3><p>Enter a task ID and enable retrieval.</p></div>}
    </div>
  );
}

function EndpointSettings({
  kind,
  name,
  state,
  onChange,
}: {
  kind: EndpointKind;
  name: string;
  state: EndpointState;
  onChange: (state: EndpointState) => void;
}) {
  const [config, setConfig] = useState<EndpointConfig>(() => structuredClone(state.config ?? {}));
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => setConfig(structuredClone(state.config ?? {})), [state.config]);
  const connection = config.connection_settings ?? {};
  const setConnection = (key: keyof NonNullable<EndpointConfig["connection_settings"]>, value: string) =>
    setConfig((current) => ({
      ...current,
      connection_settings: { ...current.connection_settings, [key]: value },
    }));

  const save = async (next = config) => {
    setBusy(true);
    setError("");
    try {
      const saved = await api<EndpointConfig>(
        `/api/endpoints/${kind}/${encodeURIComponent(name)}/config`,
        { method: "PUT", body: JSON.stringify(next) },
      );
      setConfig(saved);
      onChange({ ...state, config: saved });
      setNotice("Settings saved.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save settings.");
    } finally {
      setBusy(false);
    }
  };

  const test = async (target: "http" | "mongo") => {
    setBusy(true);
    setError("");
    try {
      const saved = await api<EndpointConfig>(
        target === "http"
          ? `/api/endpoints/${kind}/${encodeURIComponent(name)}/test-http`
          : `/api/endpoints/devices/${encodeURIComponent(name)}/test-mongo`,
        { method: "POST", body: "{}" },
      );
      setConfig(saved);
      onChange({ ...state, config: saved });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Connection test failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="endpoint-stack">
      {error && <Notice tone="error" onClose={() => setError("")}>{error}</Notice>}
      {notice && <Notice tone="success" onClose={() => setNotice("")}>{notice}</Notice>}
      <section className="subpanel">
        <div className="section-heading"><div><h2>Connection Settings</h2><p>Configure the endpoint used by the Python worker.</p></div></div>
        <div className="form-grid two">
          <label>
            HTTP address
            <input value={connection.http_url ?? ""} onChange={(event) => setConnection("http_url", event.target.value)} />
          </label>
          {state.descriptor.supportsMongo && (
            <>
              <label>
                MongoDB database
                <input value={connection.mongodb_database ?? ""} onChange={(event) => setConnection("mongodb_database", event.target.value)} />
              </label>
              <label className="span-two">
                MongoDB address
                <textarea rows={3} value={connection.mongodb_address ?? ""} onChange={(event) => setConnection("mongodb_address", event.target.value)} />
              </label>
              <label>
                MongoDB collection
                <input value={connection.mongodb_collection ?? ""} onChange={(event) => setConnection("mongodb_collection", event.target.value)} />
              </label>
            </>
          )}
        </div>
        <button className="button primary" disabled={busy} onClick={() => void save()}><Save size={17} /> Save Connection Settings</button>
      </section>
      <section className="subpanel">
        <div className="section-heading"><div><h2>Connectivity Testing</h2><p>Run the same endpoint checks as the original interface.</p></div></div>
        <div className="connection-tests">
          <button className="button secondary" disabled={busy} onClick={() => void test("http")}><Cable size={17} /> Test HTTP</button>
          <span className={`connection-result ${connection.http_status === true ? "ok" : connection.http_status === false ? "failed" : ""}`}>
            {connection.http_status === true ? "HTTP OK" : connection.http_status === false ? "HTTP Failed" : "HTTP Untested"}
          </span>
          {state.descriptor.supportsMongo && (
            <>
              <button className="button secondary" disabled={busy} onClick={() => void test("mongo")}><Database size={17} /> Test MongoDB</button>
              <span className={`connection-result ${connection.mongodb_status === true ? "ok" : connection.mongodb_status === false ? "failed" : ""}`}>
                {connection.mongodb_status === true ? "MongoDB OK" : connection.mongodb_status === false ? "MongoDB Failed" : "MongoDB Untested"}
              </span>
            </>
          )}
        </div>
      </section>
      {state.descriptor.supportsReagents && config.reagent_settings && (
        <section className="subpanel">
          <div className="section-heading"><div><h2>Reagent Location Configuration</h2><p>Map each hardware location to a reagent.</p></div></div>
          <div className="reagent-grid">
            {Object.entries(config.reagent_settings).map(([location, reagent]) => (
              <label key={location}>
                <span>{location.startsWith("#") ? `Location ${location.slice(1)}` : `Location ${location}`}</span>
                <input
                  value={reagent}
                  placeholder="Enter reagent name"
                  onChange={(event) =>
                    setConfig((current) => ({
                      ...current,
                      reagent_settings: { ...current.reagent_settings, [location]: event.target.value },
                    }))
                  }
                />
              </label>
            ))}
          </div>
          <div className="button-row">
            <button className="button primary" disabled={busy} onClick={() => void save()}><Save size={17} /> Save Reagent Settings</button>
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => {
                const next: EndpointConfig = {
                  ...config,
                  reagent_settings: Object.fromEntries(Object.keys(config.reagent_settings ?? {}).map((key) => [key, ""])),
                };
                setConfig(next);
                void save(next);
              }}
            >
              Clear All
            </button>
          </div>
        </section>
      )}
    </div>
  );
}

export default function EndpointPage({ kind }: { kind: EndpointKind }) {
  const [selected, setSelected] = useState("");
  const [tab, setTab] = useState<EndpointTab>("interaction");
  const endpoints = usePolling<EndpointDescriptor[]>(
    () => api(`/api/endpoints/${kind}`),
    null,
    [kind],
  );
  useEffect(() => {
    if (!selected && endpoints.data?.length) setSelected(endpoints.data[0].name);
  }, [selected, endpoints.data]);
  const state = usePolling<EndpointState | null>(
    () =>
      selected
        ? api(`/api/endpoints/${kind}/${encodeURIComponent(selected)}`)
        : Promise.resolve(null),
    selected ? (kind === "devices" ? 60_000 : 5_000) : null,
    [kind, selected],
  );
  useEffect(() => {
    if (!state.data) return;
    if (tab === "status" && !state.data.descriptor.supportsStatus) setTab("interaction");
    if (tab === "settings" && !state.data.descriptor.supportsSettings) setTab("interaction");
  }, [state.data, tab]);

  const tabs = useMemo(() => {
    const options: Array<TabOption<EndpointTab>> = [
      { id: "interaction", label: "Interaction", icon: <Beaker size={16} /> },
    ];
    if (state.data?.descriptor.supportsStatus) options.push({ id: "status", label: "Status", icon: <Gauge size={16} /> });
    if (state.data?.descriptor.supportsSettings) options.push({ id: "settings", label: "Settings", icon: <Settings size={16} /> });
    return options;
  }, [state.data]);

  const PageIcon = kind === "devices" ? FlaskConical : Wrench;
  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">{kind === "devices" ? "Laboratory hardware" : "Analysis services"}</span>
          <h1>{kind === "devices" ? "Hardware Status" : "Tool Status"}</h1>
          <p>Manage tasks, results, status, and connections for the selected {kind === "devices" ? "device" : "tool"}.</p>
        </div>
        <div className="endpoint-selector">
          <PageIcon size={19} />
          <label>
            Choose a {kind === "devices" ? "device" : "tool"}
            <select value={selected} onChange={(event) => { setSelected(event.target.value); setTab("interaction"); }}>
              {endpoints.data?.map((endpoint) => <option key={endpoint.name} value={endpoint.name}>{endpoint.name}</option>)}
            </select>
          </label>
        </div>
      </header>
      {(endpoints.error || state.error) && <Notice tone="error">{endpoints.error || state.error}</Notice>}
      {state.data ? (
        <>
          <div className="endpoint-title-card">
            <span className="feature-icon cyan"><PageIcon size={22} /></span>
            <div><h2>{state.data.descriptor.title}</h2><p>{state.data.taskName ? `Latest task: ${state.data.taskName}` : "No current task"}</p></div>
          </div>
          <Tabs options={tabs} value={tab} onChange={setTab} />
          <section className="panel">
            {tab === "interaction" && <EndpointInteraction kind={kind} name={selected} state={state.data} onChange={state.setData} />}
            {tab === "status" && <EndpointStatus name={selected} descriptor={state.data.descriptor} />}
            {tab === "settings" && <EndpointSettings kind={kind} name={selected} state={state.data} onChange={state.setData} />}
          </section>
        </>
      ) : (
        <div className="skeleton page-skeleton" />
      )}
    </div>
  );
}
