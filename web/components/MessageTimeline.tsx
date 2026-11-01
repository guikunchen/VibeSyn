import { useState } from "react";
import { ArrowRight, Pencil, Trash2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { TaskView } from "../../shared/types.ts";
import { api } from "../api.ts";
import { Notice } from "./Notice.tsx";
import ResourceView from "./ResourceView.tsx";
import RetroEvaluation from "./RetroEvaluation.tsx";

export interface HumanDraft {
  rawIndex: number;
  visibleWordCount: number;
  phase: "typing" | "complete" | "leaving";
}

export default function MessageTimeline({
  view,
  compactResources = false,
  onChange,
  visibleCount = view.messages.length,
  humanDraft = null,
}: {
  view: TaskView;
  compactResources?: boolean;
  onChange: (view: TaskView) => void;
  visibleCount?: number;
  humanDraft?: HumanDraft | null;
}) {
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const displayedMessages = view.messages.slice(0, visibleCount);
  const activeHumanMessage = humanDraft
    ? view.messages.find((message) => message.rawIndex === humanDraft.rawIndex)
    : undefined;

  const save = async (rawIndex: number) => {
    setBusy(true);
    setError("");
    try {
      const updated = await api<TaskView>(
        `/api/tasks/${encodeURIComponent(view.task.task_name)}/messages/${rawIndex}`,
        { method: "PATCH", body: JSON.stringify({ content: draft }) },
      );
      setEditing(null);
      onChange(updated);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not edit message.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (rawIndex: number) => {
    if (!window.confirm("Delete the latest message and roll the task back?")) return;
    setBusy(true);
    setError("");
    try {
      const updated = await api<TaskView>(
        `/api/tasks/${encodeURIComponent(view.task.task_name)}/messages/${rawIndex}`,
        { method: "DELETE" },
      );
      onChange(updated);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not delete message.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="message-list">
      {error && <Notice tone="error" onClose={() => setError("")}>{error}</Notice>}
      {displayedMessages.map((message) => {
        return (
          <article
            key={message.rawIndex}
            className={`message-card ${message.isNarration ? "narration" : ""}`}
          >
            <header>
              <div className="message-route">
                {message.sender ? (
                  <>
                    <img src={message.senderIcon} alt="" />
                    <strong>{message.sender}</strong>
                    <ArrowRight size={16} />
                    <img src={message.recipientIcon} alt="" />
                    <strong>{message.recipient}</strong>
                  </>
                ) : (
                  <strong>{message.type}</strong>
                )}
              </div>
                <div className="message-meta">
                  <span>{message.type}</span>
                  <time>{message.time}</time>
                </div>
            </header>
            {editing === message.rawIndex ? (
              <div className="edit-message">
                <textarea value={draft} onChange={(event) => setDraft(event.target.value)} rows={8} />
                <div className="button-row">
                  <button className="button secondary" type="button" onClick={() => setEditing(null)}>Cancel</button>
                  <button className="button primary" type="button" disabled={busy} onClick={() => void save(message.rawIndex)}>Save Message</button>
                </div>
              </div>
            ) : (
              message.retroPathBaseUrl ? (
                <RetroEvaluation content={message.content} baseUrl={message.retroPathBaseUrl} />
              ) : (
                <div className="markdown">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {message.content}
                  </ReactMarkdown>
                </div>
              )
            )}
            {message.resources.length > 0 && (
              <div className="resource-grid">
                {message.resources.map((resource) => (
                  <ResourceView key={resource.path} resource={resource} compact={compactResources} />
                ))}
              </div>
            )}
              <footer>
                <button
                  type="button"
                  className="icon-button labelled"
                  disabled={!message.editable || busy}
                  title={message.editable ? "Edit message" : "Only a paused next step can be edited"}
                  onClick={() => {
                    setEditing(message.rawIndex);
                    setDraft(message.rawContent);
                  }}
                >
                  <Pencil size={15} /> Edit
                </button>
                <button
                  type="button"
                  className="icon-button labelled danger"
                  disabled={!message.deletable || message.displayIndex !== view.messages.length - 1 || busy}
                  title={
                    view.task.task_status === "paused" || view.task.task_status === "completed"
                      ? "Only the latest message after the first two can be deleted"
                      : "Pause the task before deleting a message"
                  }
                  onClick={() => void remove(message.rawIndex)}
                >
                  <Trash2 size={15} /> Delete
                </button>
              </footer>
          </article>
        );
      })}
      {activeHumanMessage && humanDraft && (
        <section
          key={`draft-${activeHumanMessage.rawIndex}`}
          className={`human-composer ${humanDraft.phase}`}
          aria-label="Human response playback"
        >
          <div className="human-composer-heading">
            <span className="human-composer-label"><Pencil size={16} /> Human input</span>
            <span className="human-composer-status" role="status">
              {humanDraft.phase === "typing" ? "Drafting response…" : "Response complete"}
            </span>
          </div>
          <div className="human-composer-text">
            <span>{(activeHumanMessage.content.match(/\S+\s*/g) ?? []).slice(0, humanDraft.visibleWordCount).join("")}</span>
            {humanDraft.phase === "typing" && <i className="typing-cursor" aria-hidden="true" />}
          </div>
          <div className="human-composer-footer">
            <span>To {activeHumanMessage.recipient || "Agent"}</span>
            <ArrowRight size={18} aria-hidden="true" />
          </div>
        </section>
      )}
    </div>
  );
}
