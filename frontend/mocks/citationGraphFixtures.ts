import type { CitationTreeResponse } from '@/types/citationGraph';

const rootNodes = [
  {
    nodeId: '1706.03762',
    title: 'Attention Is All You Need',
    year: 2017,
    citationCount: 120000,
    depth: 1,
    arxivId: '1706.03762',
    url: 'https://arxiv.org/abs/1706.03762',
    inCorpus: true,
    saveable: true,
    alreadyShown: false,
  },
  {
    nodeId: 'doi:10.5555/3295222.3295349',
    title: 'Deep Residual Learning for Image Recognition',
    year: 2016,
    citationCount: 180000,
    depth: 1,
    url: 'https://doi.org/10.5555/3295222.3295349',
    inCorpus: false,
    saveable: false,
    alreadyShown: false,
  },
];

const expandedNodesByParent = {
  '1706.03762': [
    {
      nodeId: '1409.0473',
      title: 'Neural Machine Translation by Jointly Learning to Align and Translate',
      year: 2015,
      citationCount: 31000,
      depth: 2,
      arxivId: '1409.0473',
      url: 'https://arxiv.org/abs/1409.0473',
      inCorpus: false,
      saveable: true,
      alreadyShown: false,
    },
  ],
  'doi:10.5555/3295222.3295349': [
    {
      nodeId: '1512.03385',
      title: 'Batch Normalization: Accelerating Deep Network Training',
      year: 2015,
      citationCount: 45000,
      depth: 2,
      arxivId: '1512.03385',
      url: 'https://arxiv.org/abs/1512.03385',
      inCorpus: false,
      saveable: true,
      alreadyShown: false,
    },
  ],
};

export function mockCitationTree(paperId: string, expandNodeId?: string): CitationTreeResponse {
  if (expandNodeId) {
    const expandedNodes =
      expandedNodesByParent[expandNodeId as keyof typeof expandedNodesByParent] ?? [];
    return {
      status: 'Success',
      rootPaperId: paperId,
      nodes: expandedNodes,
      edges: expandedNodes.map((node) => ({ source: expandNodeId, target: node.nodeId, depth: 2 })),
      unresolved: [],
      depthReturned: 2,
      truncated: false,
      remainingEstimate: 0,
      cacheHit: true,
      providerStatus: 'mock-expanded',
    };
  }

  return {
    status: 'Partial',
    rootPaperId: paperId,
    nodes: rootNodes,
    edges: rootNodes.map((node) => ({ source: paperId, target: node.nodeId, depth: 1 })),
    unresolved: [{ title: 'OpenReview workshop record without stable arXiv ID', year: 2024, reason: 'unresolved' }],
    depthReturned: 1,
    truncated: true,
    remainingEstimate: 3,
    cacheHit: false,
    providerStatus: 'mock-root',
  };
}
