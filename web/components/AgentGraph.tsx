import { useMemo } from "react";
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import type { GraphData } from "../../shared/types.ts";

const colors = {
  manager: { background: "#ffebe8", border: "#f15b43", color: "#772216" },
  agent: { background: "#edf9e8", border: "#6dab43", color: "#31541f" },
  device: { background: "#e7f7fc", border: "#19a8d4", color: "#0b536a" },
  tool: { background: "#fff3df", border: "#f59e36", color: "#71420d" },
  other: { background: "#f1f4f7", border: "#95a4b2", color: "#344354" },
};

export default function AgentGraph({ graph }: { graph: GraphData }) {
  const { nodes, edges } = useMemo(() => {
    const grouped = {
      manager: graph.nodes.filter((node) => node.category === "manager"),
      agent: graph.nodes.filter((node) => node.category === "agent"),
      other: graph.nodes.filter((node) => !["manager", "agent"].includes(node.category)),
    };
    const xByCategory = { manager: 20, agent: 340, device: 670, tool: 670, other: 670 };
    const counters: Record<string, number> = {};
    const flowNodes: Node[] = graph.nodes.map((node) => {
      const column = node.category === "manager" ? grouped.manager : node.category === "agent" ? grouped.agent : grouped.other;
      const index = column.findIndex((item) => item.id === node.id);
      counters[node.category] = (counters[node.category] ?? 0) + 1;
      const palette = colors[node.category];
      return {
        id: node.id,
        position: {
          x: xByCategory[node.category],
          y: 35 + index * 92,
        },
        data: { label: node.label },
        style: {
          width: 210,
          padding: "13px 16px",
          borderRadius: 12,
          background: palette.background,
          border: `${node.highlighted ? 3 : 1.5}px solid ${palette.border}`,
          color: palette.color,
          fontWeight: node.highlighted ? 750 : 650,
          boxShadow: node.highlighted ? `0 0 0 5px ${palette.border}22` : "0 6px 20px rgba(17,45,67,.06)",
        },
      };
    });
    const flowEdges: Edge[] = graph.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      animated: !edge.dashed,
      markerEnd: { type: MarkerType.ArrowClosed, color: "#597184" },
      style: {
        stroke: "#71899a",
        strokeWidth: 1.5,
        strokeDasharray: edge.dashed ? "6 5" : undefined,
      },
    }));
    return { nodes: flowNodes, edges: flowEdges };
  }, [graph]);

  if (!nodes.length) return <div className="empty-state">No enabled agent connections.</div>;
  return (
    <div className="graph-canvas">
      <ReactFlow nodes={nodes} edges={edges} fitView nodesDraggable={false} nodesConnectable={false}>
        <Background color="#d8e6ee" gap={22} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
