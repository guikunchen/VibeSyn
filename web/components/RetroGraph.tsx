import { useMemo, useState } from "react";
import { Background, Controls, MarkerType, ReactFlow, type Edge, type Node } from "@xyflow/react";
import type { RetroNode } from "../../shared/types.ts";
import MoleculeSvg from "./MoleculeSvg.tsx";

function layout(root: RetroNode) {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const procedures = new Map<string, string>();
  let leaf = 0;
  const visit = (node: RetroNode, depth: number, parent?: string): number => {
    const childYs = node.children.map((child) => visit(child, depth + 1, node.id));
    const y = childYs.length ? (Math.min(...childYs) + Math.max(...childYs)) / 2 : leaf++ * 165;
    nodes.push({
      id: node.id,
      position: { x: -depth * 245, y },
      data: {
        label:
          node.type === "chemical" ? (
            <MoleculeSvg smiles={node.smiles ?? ""} />
          ) : (
            <div className="condition-label">{node.label}</div>
          ),
      },
      style:
        node.type === "chemical"
          ? { width: 205, height: 130, background: "#fff", border: "1px solid #aac0cc", borderRadius: 12, padding: 6 }
          : { width: 170, background: "#fff8e7", border: "2px dashed #f59e36", borderRadius: 12, padding: 10, whiteSpace: "pre-line", fontSize: 12 },
    });
    if (node.procedure) procedures.set(node.id, node.procedure);
    if (parent) {
      edges.push({
        id: `${parent}-${node.id}`,
        source: parent,
        target: node.id,
        markerEnd: { type: MarkerType.ArrowClosed },
        style: { stroke: "#71899a" },
      });
    }
    return y;
  };
  visit(root, 0);
  return { nodes, edges, procedures };
}

export default function RetroGraph({ root }: { root: RetroNode }) {
  const graph = useMemo(() => layout(root), [root]);
  const [procedure, setProcedure] = useState("");
  return (
    <>
      <div className="retro-canvas">
        <ReactFlow
          nodes={graph.nodes}
          edges={graph.edges}
          fitView
          nodesDraggable={false}
          nodesConnectable={false}
          onNodeClick={(_, node) => setProcedure(graph.procedures.get(node.id) ?? "")}
        >
          <Background color="#d8e6ee" gap={22} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <div className="procedure-panel">
        <strong>Preparation procedure</strong>
        <p>{procedure || "Select a condition node to view its procedure."}</p>
      </div>
    </>
  );
}
