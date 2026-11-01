import { useEffect, useRef, useState } from "react";
import {
  Download,
  Network,
  Octagon,
  Play,
  Send,
  Upload,
  Workflow,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { GraphData, TaskView } from "../../shared/types.ts";
import { api, download, upload } from "../api.ts";
import AgentGraph from "../components/AgentGraph.tsx";
import MessageTimeline from "../components/MessageTimeline.tsx";
import MoleculeEditor from "../components/MoleculeEditor.tsx";
import { Notice } from "../components/Notice.tsx";
import { Tabs } from "../components/Tabs.tsx";
import { usePolling } from "../hooks.ts";

export default function ExecutionPage() {
  const navigate = useNavigate();
  const executionEndRef = useRef<HTMLDivElement>(null);
  const [tab, setTab] = useState<"execution" | "graph" | "task">("execution");
  const [notice, setNotice] = useState("");
  const [actionError, setActionError] = useState("");
  const [humanInput, setHumanInput] = useState("");
  const [taskName, setTaskName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const latest = usePolling<TaskView | null>(
    () => api("/api/tasks/latest"),
    20_000,
    [],
  );
  const highlighted = latest.data?.task.current_agent ?? "";
  const graph = usePolling<GraphData>(
    () =>
      api(
        `/api/graph?context=execution&highlighted=${encodeURIComponent(highlighted)}`,
      ),
    tab === "graph" ? 5_000 : null,
    [tab, highlighted],
  );

  useEffect(() => {
    if (tab !== "execution" || !latest.data) return;
    executionEndRef.current?.scrollIntoView({ block: "end" });
  }, [latest.data, tab]);

  const act = async (action: "continue" | "stop") => {
    if (!latest.data) return;
    setBusy(true);
    setActionError("");
    try {
      if (action === "continue") {
        const result = await api<{
          task: TaskView;
          requiresEndpoint: boolean;
          target?: string;
        }>(
          `/api/tasks/${encodeURIComponent(latest.data.task.task_name)}/actions/continue`,
          { method: "POST", body: "{}" },
        );
        latest.setData(result.task);
        if (result.requiresEndpoint && result.target) {
          const page = result.target.endsWith("Device") ? "/hardware" : "/tools";
          setNotice(`The workflow is waiting for ${result.target}. Open its status page to continue.`);
          window.setTimeout(() => navigate(page), 1100);
        } else {
          setNotice("Workflow continues.");
        }
      } else {
        latest.setData(
          await api<TaskView>(
            `/api/tasks/${encodeURIComponent(latest.data.task.task_name)}/actions/stop`,
            { method: "POST", body: "{}" },
          ),
        );
        setNotice("Workflow paused.");
      }
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "Task action failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Live workflow</span>
          <h1>Agent Execution</h1>
          <p>Create, monitor, and control the current chemistry task.</p>
        </div>
        <div className="button-row execution-actions">
          <button className="button primary" disabled={!latest.data || busy} onClick={() => void act("continue")}>
            <Play size={17} /> Continue
          </button>
          <button className="button danger" disabled={!latest.data || busy} onClick={() => void act("stop")}>
            <Octagon size={17} /> Emergency Stop
          </button>
          <button
            className="button secondary"
            disabled={!latest.data}
            onClick={() =>
              latest.data &&
              download(`/api/tasks/${encodeURIComponent(latest.data.task.task_name)}/export`)
            }
          >
            <Download size={17} /> Save Current
          </button>
          <label className="button secondary file-button">
            <Upload size={17} /> Load Previous
            <input
              type="file"
              accept=".zip,application/zip"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) {
                  void upload<TaskView>("/api/tasks/import", file)
                    .then((view) => {
                      latest.setData(view);
                      setNotice(`Loaded ${view.task.task_name}.`);
                    })
                    .catch((caught) =>
                      setActionError(caught instanceof Error ? caught.message : "Task import failed."),
                    );
                }
                event.target.value = "";
              }}
            />
          </label>
        </div>
      </header>
      {notice && <Notice tone="success" onClose={() => setNotice("")}>{notice}</Notice>}
      {(actionError || latest.error) && (
        <Notice tone="error" onClose={() => { setActionError(""); latest.setError(""); }}>
          {actionError || latest.error}
        </Notice>
      )}
      {latest.data && (
        <div className="task-summary">
          <div>
            <span>Current task</span>
            <strong>{latest.data.task.task_name}</strong>
          </div>
          <span className={`status-pill ${latest.data.task.task_status.replaceAll(" ", "-")}`}>
            {latest.data.task.task_status}
          </span>
          <div>
            <span>Current agent</span>
            <strong>{latest.data.task.current_agent ?? "N.A."}</strong>
          </div>
        </div>
      )}
      <Tabs
        value={tab}
        onChange={setTab}
        options={[
          { id: "execution", label: "Agent Execution", icon: <Workflow size={16} /> },
          { id: "graph", label: "Agent Graph", icon: <Network size={16} /> },
          { id: "task", label: "Task Input", icon: <Send size={16} /> },
        ]}
      />
      {tab === "execution" && (
        <section className="panel">
          {latest.loading ? (
            <div className="skeleton page-skeleton" />
          ) : latest.data ? (
            <>
              <MessageTimeline view={latest.data} compactResources onChange={latest.setData} />
              <form
                className="human-input"
                onSubmit={async (event) => {
                  event.preventDefault();
                  if (!humanInput.trim()) return;
                  setBusy(true);
                  setActionError("");
                  try {
                    latest.setData(
                      await api<TaskView>(
                        `/api/tasks/${encodeURIComponent(latest.data!.task.task_name)}/actions/human`,
                        { method: "POST", body: JSON.stringify({ response: humanInput }) },
                      ),
                    );
                    setHumanInput("");
                    setNotice("Human response sent.");
                  } catch (caught) {
                    setActionError(caught instanceof Error ? caught.message : "Could not send response.");
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <input
                  value={humanInput}
                  onChange={(event) => setHumanInput(event.target.value)}
                  placeholder="Human input"
                  aria-label="Human input"
                />
                <button className="button primary" disabled={busy}><Send size={17} /> Send</button>
              </form>
              <div ref={executionEndRef} />
            </>
          ) : (
            <div className="empty-state">
              <Workflow size={30} />
              <h3>No tasks yet</h3>
              <p>Open Task Input to create the first workflow.</p>
            </div>
          )}
        </section>
      )}
      {tab === "graph" && (
        <section className="panel">
          {graph.error ? <Notice tone="error">{graph.error}</Notice> : graph.data ? <AgentGraph graph={graph.data} /> : <div className="skeleton graph-skeleton" />}
        </section>
      )}
      {tab === "task" && (
        <section className="panel task-form-panel">
          <div className="section-heading">
            <div><h2>Submit a New Task</h2><p>Describe the chemical workflow for ManagerAgent.</p></div>
          </div>
          <div className="form-grid two">
            <label>
              Task name
              <textarea
                rows={3}
                value={taskName}
                onChange={(event) => setTaskName(event.target.value)}
                placeholder="The name of the task"
              />
            </label>
            <label>
              Task description
              <textarea
                rows={3}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="Describe your chemical task"
              />
            </label>
          </div>
          <h3>Draw your molecule</h3>
          <MoleculeEditor />
          <button
            className="button primary wide-button"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setActionError("");
              try {
                const view = await api<TaskView>("/api/tasks", {
                  method: "POST",
                  body: JSON.stringify({ name: taskName, description }),
                });
                latest.setData(view);
                setTaskName("");
                setDescription("");
                setNotice("Task submitted successfully.");
                setTab("execution");
              } catch (caught) {
                setActionError(caught instanceof Error ? caught.message : "Could not create task.");
              } finally {
                setBusy(false);
              }
            }}
          >
            <Send size={17} /> Submit Task
          </button>
        </section>
      )}
    </div>
  );
}
