import { useEffect, useMemo, useState } from "react";
import { ExternalLink, FileText } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ResourceMeta } from "../../shared/types.ts";
import { Notice } from "./Notice.tsx";

type CurveData = Record<string, Array<number | string>>;

function TextResource({ resource }: { resource: ResourceMeta }) {
  const [text, setText] = useState<string | null>(null);
  const [data, setData] = useState<CurveData | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    fetch(resource.url)
      .then((response) => {
        if (!response.ok) throw new Error("Could not load resource.");
        return response.text();
      })
      .then((content) => {
        setText(content);
        try {
          const parsed = JSON.parse(content);
          if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
            setData(parsed as CurveData);
          }
        } catch {
          setData(null);
        }
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : "Could not load resource."));
  }, [resource.url]);

  const chart = useMemo(() => {
    if (!data) return null;
    const keys = ["UV value1", "UV value2", "EA:PE gradient (0-100)"].filter((key) =>
      Array.isArray(data[key]),
    );
    const length = Math.max(0, ...keys.map((key) => data[key].length));
    if (
      keys.length !== 3 ||
      !length ||
      keys.some((key) => data[key].length !== length)
    ) {
      return null;
    }
    const values = keys.flatMap((key) => data[key].map(Number)).filter(Number.isFinite);
    if (!values.length) return null;
    const times = Array.isArray(data.time) ? data.time.map(Number) : [];
    const numericTime = times.length === length && times.every(Number.isFinite);
    const timeMin = numericTime ? Math.min(...times) : 0;
    const timeRange = numericTime ? Math.max(...times) - timeMin || 1 : 1;
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    const colors = ["#06a8d8", "#f59e36", "#75b943"];
    return (
      <div className="curve-chart">
        <svg viewBox="0 0 900 280" role="img" aria-label="Result curve">
          <line x1="42" y1="12" x2="42" y2="246" className="axis" />
          <line x1="42" y1="246" x2="884" y2="246" className="axis" />
          {keys.map((key, keyIndex) => {
            const points = data[key]
              .map(Number)
              .map((value, index) => {
                const ratio = numericTime
                  ? (times[index] - timeMin) / timeRange
                  : index / Math.max(1, length - 1);
                const x = 42 + ratio * 842;
                const y = 246 - ((value - min) / range) * 224;
                return `${x},${y}`;
              })
              .join(" ");
            return <polyline key={key} points={points} fill="none" stroke={colors[keyIndex]} strokeWidth="3" />;
          })}
        </svg>
        <div className="chart-legend">
          {keys.map((key, index) => (
            <span key={key}><i style={{ background: colors[index] }} />{key}</span>
          ))}
        </div>
      </div>
    );
  }, [data]);

  if (error) return <Notice tone="error">{error}</Notice>;
  if (text === null) return <div className="skeleton short" />;
  if (chart) return chart;
  if (resource.kind === "json") {
    let formatted = text;
    try {
      formatted = JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      return <Notice tone="error">This JSON resource is malformed.</Notice>;
    }
    return <pre className="resource-text">{formatted}</pre>;
  }
  return (
    <div className="resource-text markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}

export default function ResourceView({ resource, compact = false }: { resource: ResourceMeta; compact?: boolean }) {
  if (resource.kind === "image") {
    return (
      <figure className={`resource-image ${compact ? "compact" : ""}`}>
        <img src={resource.url} alt={resource.name} loading="lazy" />
        <figcaption>{resource.name}</figcaption>
      </figure>
    );
  }
  if (resource.kind === "text" || resource.kind === "json") {
    return <TextResource resource={resource} />;
  }
  return (
    <a className="file-link" href={resource.url} target="_blank" rel="noreferrer">
      <FileText size={17} />
      {resource.name}
      <ExternalLink size={14} />
    </a>
  );
}
