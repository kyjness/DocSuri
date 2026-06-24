export type CitationTreeStatus = 'Success' | 'Partial' | 'Unavailable' | 'RateLimited';

export interface CitationNode {
  nodeId: string;
  title: string;
  year?: number | null;
  citationCount?: number | null;
  depth: number;
  arxivId?: string | null;
  url?: string | null;
  inCorpus?: boolean;
  saveable: boolean;
  alreadyShown: boolean;
}

export interface CitationEdge {
  source: string;
  target: string;
}

export interface CitationTreeResponse {
  status: CitationTreeStatus;
  rootPaperId: string;
  nodes: CitationNode[];
  edges: CitationEdge[];
  unresolved: string[];
  depthReturned: number;
  truncated: boolean;
  remainingEstimate?: number | null;
  cacheHit: boolean;
  providerStatus: string;
}

export interface CitationTreeQuery {
  expandNodeId?: string;
  refresh?: boolean;
}
