// Mock search fixtures — derived from shared/dtos/search.schema.json (BR-U5-19).
// Exercises every SearchResponse branch. Cross-lingual sample: a Korean query
// surfaces English arXiv papers (TD-3, MR-2). Phase 2 (Q2): the multi-source corpus
// is exercised with one card per source — arXiv, Semantic Scholar, OpenAlex —
// carrying source-neutral sourceName/sourceUrl.
import type {
  SearchResultPageDTO,
  AbstainDTO,
  DegradedResultDTO,
  ValidationErrorDTO,
  ResultCardVM,
} from '@/types/generated';

const CARDS: ResultCardVM[] = [
  {
    title: 'Attention Is All You Need',
    authors: ['Ashish Vaswani', 'Noam Shazeer', 'Niki Parmar'],
    year: 2017,
    arxivId: '1706.03762v5',
    abstractSnippet:
      'The dominant sequence transduction models are based on complex recurrent or convolutional neural networks…',
    relevance: '높음',
    arxivUrl: 'https://arxiv.org/abs/1706.03762',
  },
  {
    title: 'BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding',
    authors: ['Jacob Devlin', 'Ming-Wei Chang', 'Kenton Lee', 'Kristina Toutanova'],
    year: 2018,
    arxivId: '1810.04805v2',
    abstractSnippet:
      'We introduce a new language representation model called BERT, which stands for Bidirectional Encoder Representations…',
    relevance: '높음',
    arxivUrl: 'https://arxiv.org/abs/1810.04805',
  },
  {
    title: 'Deep Residual Learning for Image Recognition',
    authors: ['Kaiming He', 'Xiangyu Zhang', 'Shaoqing Ren', 'Jian Sun'],
    year: 2015,
    arxivId: '1512.03385v1',
    abstractSnippet:
      'Deeper neural networks are more difficult to train. We present a residual learning framework…',
    relevance: '보통',
    arxivUrl: 'https://arxiv.org/abs/1512.03385',
    sourceName: 'arXiv',
    sourceUrl: 'https://arxiv.org/abs/1512.03385',
  },
  {
    // Sourced via Semantic Scholar (Phase 2 Q2) — the link-out points to S2, not arXiv.
    title: 'Language Models are Few-Shot Learners',
    authors: ['Tom B. Brown', 'Benjamin Mann', 'Nick Ryder'],
    year: 2020,
    arxivId: '2005.14165v4',
    abstractSnippet:
      'We show that scaling up language models greatly improves task-agnostic, few-shot performance…',
    relevance: '높음',
    arxivUrl: 'https://arxiv.org/abs/2005.14165',
    sourceName: 'Semantic Scholar',
    sourceUrl: 'https://www.semanticscholar.org/paper/6b85b63579a916f705a8e10a49bd8d849d91b1fc',
  },
  {
    // Sourced via OpenAlex (Phase 2 Q2) — the link-out points to OpenAlex.
    title: 'Denoising Diffusion Probabilistic Models',
    authors: ['Jonathan Ho', 'Ajay Jain', 'Pieter Abbeel'],
    year: 2020,
    arxivId: '2006.11239v2',
    abstractSnippet:
      'We present high quality image synthesis results using diffusion probabilistic models…',
    relevance: '보통',
    arxivUrl: 'https://arxiv.org/abs/2006.11239',
    sourceName: 'OpenAlex',
    sourceUrl: 'https://openalex.org/W3030163527',
  },
];

export const pageResponse: SearchResultPageDTO = {
  cards: CARDS,
  meta: { resultCount: CARDS.length, degraded: false },
};

// US-P4 (#155): a page whose order the LIVE personalization re-rank actually boosted —
// meta.personalized=true drives the '내 관심 주제 반영' indicator + settings off entry point.
export const personalizedPageResponse: SearchResultPageDTO = {
  cards: CARDS,
  meta: { resultCount: CARDS.length, degraded: false, personalized: true },
};

export const emptyResponse: SearchResultPageDTO = {
  cards: [],
  meta: { resultCount: 0, degraded: false },
};

export const abstainResponse: AbstainDTO = {
  reason: 'out-of-corpus',
};

export const degradedResponse: DegradedResultDTO = {
  cards: CARDS.slice(0, 2),
  meta: { resultCount: 2, degraded: true, degradationMode: 'lexical-only' },
  mode: 'lexical-only',
};

export const validationErrorResponse: ValidationErrorDTO = {
  field: 'query',
  message: '검색어를 확인해 주세요.',
};
