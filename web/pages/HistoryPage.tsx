import { useEffect, useRef, useState } from "react";
import { Archive, Download, RotateCcw, Trash2 } from "lucide-react";
import type { TaskView } from "../../shared/types.ts";
import { api, download } from "../api.ts";
import MessageTimeline, { type HumanDraft } from "../components/MessageTimeline.tsx";
import { Notice } from "../components/Notice.tsx";

interface TaskListItem {
  name: string;
  modifiedAt: string;
  status: string;
}

export default function HistoryPage() {
  const [tasks, setTasks] = useState<TaskListItem[]>([]);
  const [selected, setSelected] = useState("");
  const [view, setView] = useState<TaskView | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [displayMode, setDisplayMode] = useState<"static" | "dynamic">("static");
  const [boxIntervalMs, setBoxIntervalMs] = useState(1000);
  const [wordIntervalMs, setWordIntervalMs] = useState(120);
  const [visibleCount, setVisibleCount] = useState(0);
  const [humanDraft, setHumanDraft] = useState<HumanDraft | null>(null);
  const [playbackKey, setPlaybackKey] = useState(0);
  const timelineEndRef = useRef<HTMLDivElement>(null);
  const shouldFollowRef = useRef(true);
  const lastScrollYRef = useRef(0);

  const loadTasks = async (preferred?: string) => {
    try {
      const list = await api<TaskListItem[]>("/api/tasks");
      setTasks(list);
      const next = preferred && list.some((task) => task.name === preferred)
        ? preferred
        : list.some((task) => task.name === selected)
          ? selected
          : list[0]?.name ?? "";
      setSelected(next);
      if (next) setView(await api<TaskView>(`/api/tasks/${encodeURIComponent(next)}`));
      else setView(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load task history.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void loadTasks(); }, []);

  useEffect(() => {
    if (displayMode !== "dynamic" || !view) return;
    setVisibleCount(0);
    setHumanDraft(null);
    let timer: number | undefined;
    let cancelled = false;
    let nextIndex = 0;

    const scheduleNext = () => {
      timer = window.setTimeout(showNext, boxIntervalMs);
    };

    const commitHuman = (messageIndex: number) => {
      if (cancelled) return;
      setVisibleCount(messageIndex + 1);
      setHumanDraft(null);
      nextIndex = messageIndex + 1;
      scheduleNext();
    };

    const showNext = () => {
      if (cancelled || nextIndex >= view.messages.length) return;
      const messageIndex = nextIndex;
      const message = view.messages[messageIndex];

      if (message.sender !== "Human") {
        nextIndex += 1;
        setVisibleCount(nextIndex);
        scheduleNext();
        return;
      }

      const words = message.content.match(/\S+\s*/g) ?? [];
      let visibleWordCount = 0;
      setHumanDraft({ rawIndex: message.rawIndex, visibleWordCount, phase: "typing" });

      const finishDraft = () => {
        setHumanDraft({ rawIndex: message.rawIndex, visibleWordCount, phase: "complete" });
        timer = window.setTimeout(() => {
          if (cancelled) return;
          setHumanDraft({ rawIndex: message.rawIndex, visibleWordCount, phase: "leaving" });
          timer = window.setTimeout(() => commitHuman(messageIndex), 240);
        }, 1000);
      };

      if (!words.length) {
        finishDraft();
        return;
      }

      const showNextWord = () => {
        timer = window.setTimeout(() => {
          if (cancelled) return;
          visibleWordCount += 1;
          setHumanDraft({ rawIndex: message.rawIndex, visibleWordCount, phase: "typing" });
          if (visibleWordCount === words.length) finishDraft();
          else showNextWord();
        }, wordIntervalMs);
      };

      showNextWord();
    };

    scheduleNext();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [boxIntervalMs, displayMode, playbackKey, view?.task.task_name, wordIntervalMs]);

  useEffect(() => {
    if (displayMode !== "dynamic") return;
    shouldFollowRef.current = true;
    lastScrollYRef.current = window.scrollY;

    const handleScroll = () => {
      const scrollY = window.scrollY;
      const bottomDistance = document.documentElement.scrollHeight - window.innerHeight - scrollY;
      const nearBottom = bottomDistance <= 120;
      if (scrollY < lastScrollYRef.current - 2 && !nearBottom) shouldFollowRef.current = false;
      else if (nearBottom) shouldFollowRef.current = true;
      lastScrollYRef.current = scrollY;
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, [displayMode, playbackKey, view?.task.task_name]);

  useEffect(() => {
    if (displayMode !== "dynamic" || !shouldFollowRef.current) return;
    const frame = window.requestAnimationFrame(() => {
      if (!shouldFollowRef.current) return;
      const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const isTypingUpdate = humanDraft !== null && humanDraft.visibleWordCount > 0;
      timelineEndRef.current?.scrollIntoView({
        behavior: reduceMotion || isTypingUpdate ? "auto" : "smooth",
        block: "end",
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [displayMode, humanDraft, visibleCount]);

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Workflow archive</span>
          <h1>Task History</h1>
          <p>Inspect and manage previous chemistry tasks.</p>
        </div>
        <label className="history-selector">
          Choose a task
          <select
            value={selected}
            onChange={async (event) => {
              const name = event.target.value;
              setSelected(name);
              setLoading(true);
              try {
                setView(await api<TaskView>(`/api/tasks/${encodeURIComponent(name)}`));
              } catch (caught) {
                setError(caught instanceof Error ? caught.message : "Could not load task.");
              } finally {
                setLoading(false);
              }
            }}
          >
            {!tasks.length && <option value="">No tasks available</option>}
            {tasks.map((task) => <option key={task.name}>{task.name}</option>)}
          </select>
        </label>
      </header>
      {error && <Notice tone="error" onClose={() => setError("")}>{error}</Notice>}
      {notice && <Notice tone="success" onClose={() => setNotice("")}>{notice}</Notice>}
      {!loading && view && (
        <div className="history-display-controls">
          <label>
            Display mode
            <select value={displayMode} onChange={(event) => setDisplayMode(event.target.value as "static" | "dynamic")}>
              <option value="static">Static</option>
              <option value="dynamic">Dynamic</option>
            </select>
          </label>
          {displayMode === "dynamic" && (
            <>
              <label>
                Box interval (ms)
                <input
                  type="number"
                  min="1"
                  value={boxIntervalMs}
                  onChange={(event) => setBoxIntervalMs(Math.max(1, Number(event.target.value)))}
                />
              </label>
              <label>
                Human word interval (ms)
                <input
                  type="number"
                  min="1"
                  value={wordIntervalMs}
                  onChange={(event) => setWordIntervalMs(Math.max(1, Number(event.target.value)))}
                />
              </label>
              <button
                className="button secondary"
                type="button"
                onClick={() => {
                  setVisibleCount(0);
                  setPlaybackKey((key) => key + 1);
                }}
              >
                <RotateCcw size={16} /> Restart
              </button>
            </>
          )}
        </div>
      )}
      <section className="panel history-content">
        {loading ? (
          <div className="skeleton page-skeleton" />
        ) : view ? (
          <>
            <div className="section-heading history-heading">
              <div>
                <span className="eyebrow">Selected task</span>
                <h2>{view.task.task_name}</h2>
              </div>
              <div className="history-actions">
                <div className="history-status">
                  <span>Status</span>
                  <strong>{view.task.task_status}</strong>
                </div>
                <button
                  className="button secondary"
                  onClick={() => download(`/api/tasks/${encodeURIComponent(view.task.task_name)}/export`)}
                >
                  <Download size={17} /> Save Current
                </button>
                <button
                  className="button danger"
                  disabled={view.task.task_status === "waiting for server process"}
                  title={
                    view.task.task_status === "waiting for server process"
                      ? "Pause the task before deleting it"
                      : "Move task to deleted tasks"
                  }
                  onClick={async () => {
                    if (!window.confirm(`Move '${view.task.task_name}' to deleted tasks?`)) return;
                    try {
                      await api<void>(`/api/tasks/${encodeURIComponent(view.task.task_name)}`, { method: "DELETE" });
                      setNotice("Task moved to deleted tasks.");
                      await loadTasks();
                    } catch (caught) {
                      setError(caught instanceof Error ? caught.message : "Could not delete task.");
                    }
                  }}
                >
                  <Trash2 size={17} /> Delete
                </button>
              </div>
            </div>
            <div className="history-task-input">
              <span>Task input</span>
              <p>{view.task.task_description}</p>
            </div>
            <MessageTimeline
              view={view}
              onChange={setView}
              visibleCount={displayMode === "dynamic" ? visibleCount : view.messages.length}
              humanDraft={displayMode === "dynamic" ? humanDraft : null}
            />
            <div ref={timelineEndRef} className="timeline-end" aria-hidden="true" />
          </>
        ) : (
          <div className="empty-state"><Archive size={30} /><h3>No tasks available</h3><p>Create a task in Agent Execution first.</p></div>
        )}
      </section>
    </div>
  );
}
