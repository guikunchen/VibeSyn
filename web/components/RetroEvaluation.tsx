import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { RetroNode } from "../../shared/types.ts";
import { api } from "../api.ts";
import { Notice } from "./Notice.tsx";
import RetroGraph from "./RetroGraph.tsx";

function sections(content: string): Array<{ number: number; content: string }> {
  const matches = [...content.matchAll(/^Path\s+(\d+):\s*/gim)];
  return matches.map((match, index) => ({
    number: Number(match[1]),
    content: content.slice(match.index, matches[index + 1]?.index ?? content.length).trim(),
  }));
}

function PathVisualization({ baseUrl, number }: { baseUrl: string; number: number }) {
  const [root, setRoot] = useState<RetroNode | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setRoot(null);
    setError("");
    api<RetroNode>(`${baseUrl}/${number}`).then(setRoot).catch((caught) =>
      setError(caught instanceof Error ? caught.message : "Could not load pathway visualization."),
    );
  }, [baseUrl, number]);

  if (error) return <Notice tone="error">{error}</Notice>;
  if (!root) return <div className="skeleton retro-skeleton" />;
  return <RetroGraph root={root} />;
}

export default function RetroEvaluation({ content, baseUrl }: { content: string; baseUrl: string }) {
  return (
    <div className="retro-evaluation">
      {sections(content).map((section) => (
        <section key={section.number} className="retro-evaluation-path">
          <div className="markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{section.content}</ReactMarkdown>
          </div>
          <PathVisualization baseUrl={baseUrl} number={section.number} />
        </section>
      ))}
    </div>
  );
}
