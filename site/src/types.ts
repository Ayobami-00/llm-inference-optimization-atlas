export type NodeType =
  | "workload_archetype"
  | "study"
  | "workload"
  | "characteristic"
  | "traffic"
  | "quality_contract"
  | "slo"
  | "model"
  | "hardware"
  | "runtime"
  | "configuration"
  | "bottleneck"
  | "optimization"
  | "hypothesis"
  | "experiment"
  | "run"
  | "comparison"
  | "finding"
  | "decision"
  | "replication"
  | "source";

export interface GraphNode {
  id: string;
  type: NodeType;
  label: string;
  status: string;
  source_path: string;
  artifact_ref: string;
  summary: string;
  tags: string[];
  study?: string;
  detail_path?: string;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relation: string;
  assertion_level: string;
  evidence: string[];
  scope: Record<string, unknown>;
  confidence: "none" | "low" | "moderate" | "high";
  provenance: { source_path: string; derived?: boolean };
}

export interface GraphData {
  graph_version: 1;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface GraphView {
  id: "story" | "bottleneck" | "optimization" | "evidence" | "deployment" | "all";
  name: string;
  description: string;
  node_ids: string[];
  edge_ids: string[];
  default_layout: string;
  filters: Record<string, unknown>;
}

export interface GraphManifest {
  graph_version: 1;
  generated_at: string;
  repository_commit: string;
  scope: { type: "global" | "study"; study?: string };
  counts: { nodes: number; edges: number; entities: number };
  files: { graph: string; indexes: string; views: string[] };
}

export interface GraphIndexes {
  by_type: Record<string, string[]>;
  by_status: Record<string, string[]>;
  by_study: Record<string, string[]>;
  by_tag: Record<string, string[]>;
  referenced_by: Record<string, string[]>;
}

export interface EntityDetail {
  node: GraphNode;
  artifact: Record<string, unknown>;
  incoming: GraphEdge[];
  outgoing: GraphEdge[];
  referenced_by: string[];
}

export interface AtlasData {
  root: string;
  manifest: GraphManifest;
  graph: GraphData;
  indexes: GraphIndexes;
  views: Record<GraphView["id"], GraphView>;
}
