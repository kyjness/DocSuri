// Dev-only summarize/translate/full-text fixtures (mock transport layer, same as
// searchFixtures). Production is real-first (real BFF) — these are never shipped;
// they let the U7 surface be previewed in dev (NEXT_PUBLIC_DOCSURI_REAL_API unset).
import type {
  SummaryOkDTO,
  TranslationOkDTO,
  AssetsOkDTO,
  DocModelOkDTO,
  DocSection,
} from '@/types/generated';
import type { GlossaryUpsertResultDTO, GlossaryTermDTO } from '@/types/glossary';

// Extra body sections so the dev preview is long enough to scroll (exercises the "맨 위로"
// button and the block-zoom from a scrolled position). English for 본문, Korean for 본문 번역.
function _fillerSections(lang: 'en' | 'ko'): DocSection[] {
  const en = [
    [
      'Background',
      'Recurrent and convolutional models dominated sequence transduction, but their sequential computation limited parallelism and made long-range dependencies expensive to learn. This section reviews that prior work and motivates an attention-only design.',
    ],
    [
      'Training',
      'Models were trained on the standard WMT 2014 English-German and English-French datasets using byte-pair encoding. We used the Adam optimizer with a warmup schedule, label smoothing, and residual dropout, and averaged the last checkpoints for evaluation.',
    ],
    [
      'Results',
      'On English-German the model establishes a new state of the art while training in a fraction of the time of prior best models. On English-French it reaches competitive quality at substantially lower training cost, confirming that attention alone is sufficient.',
    ],
    [
      'Analysis',
      'We ablate the number of attention heads, the key dimension, and the model size. Too few heads hurt quality, while excessively large key dimensions provide no benefit, suggesting a sweet spot that balances capacity and optimization difficulty.',
    ],
    [
      'Conclusion',
      'The Transformer replaces recurrence entirely with self-attention, enabling far more parallelism and shorter paths between any two positions. We expect attention-based architectures to generalize beyond text to other modalities and tasks.',
    ],
  ];
  const ko = [
    [
      '배경',
      '순환·합성곱 모델이 시퀀스 변환을 지배했지만, 순차적 계산이 병렬화를 제한하고 장거리 의존성 학습을 비싸게 만들었다. 이 절에서는 선행 연구를 정리하고 어텐션 전용 설계의 동기를 설명한다.',
    ],
    [
      '학습',
      '표준 WMT 2014 영어-독일어 및 영어-프랑스어 데이터셋에서 바이트-페어 인코딩으로 학습했다. 워밍업 스케줄을 가진 Adam 최적화기, 레이블 스무딩, 잔차 드롭아웃을 사용하고 마지막 체크포인트들을 평균했다.',
    ],
    [
      '결과',
      '영어-독일어에서 이전 최고 모델 대비 훨씬 짧은 학습 시간으로 새로운 최고 성능을 달성한다. 영어-프랑스어에서도 더 낮은 학습 비용으로 경쟁력 있는 품질에 도달하여, 어텐션만으로 충분함을 확인한다.',
    ],
    [
      '분석',
      '어텐션 헤드 수, 키 차원, 모델 크기를 제거 실험한다. 헤드가 너무 적으면 품질이 떨어지고, 키 차원이 지나치게 크면 이득이 없어, 용량과 최적화 난이도 사이의 적정점이 존재함을 시사한다.',
    ],
    [
      '결론',
      'Transformer는 순환을 셀프 어텐션으로 완전히 대체하여 병렬성을 크게 높이고 임의의 두 위치 사이 경로를 짧게 만든다. 어텐션 기반 구조가 텍스트를 넘어 다른 모달리티와 과제로 일반화될 것으로 기대한다.',
    ],
  ];
  const rows = lang === 'en' ? en : ko;
  return rows.map(([title, text], i) => ({
    id: `s${10 + i}`,
    title,
    blocks: [
      { id: `s${10 + i}.p1`, type: 'paragraph', text },
      { id: `s${10 + i}.p2`, type: 'paragraph', text },
      { id: `s${10 + i}.p3`, type: 'paragraph', text },
    ],
  }));
}

export const summaryResponse: SummaryOkDTO = {
  status: 'ok',
  task: 'summary',
  meta: { source: 'full_text' },
  cached: false,
  summary: {
    tldr: 'RNN·CNN 없이 어텐션만으로 시퀀스 변환을 수행하는 Transformer를 제안한다. 병렬화가 쉬워 학습이 빠르고 번역 품질도 최고 수준이다.',
    contributions: [
      '순환·합성곱 구조를 제거하고 셀프 어텐션만으로 인코더-디코더를 구성',
      '멀티헤드 어텐션으로 서로 다른 표현 부분공간을 동시에 학습',
      'WMT 2014 영-독/영-불 번역에서 당시 SOTA 달성',
    ],
    method:
      '인코더와 디코더를 각각 6개 층으로 쌓고, 각 층은 멀티헤드 셀프 어텐션과 위치별 피드포워드 네트워크로 구성한다. 순서 정보는 사인·코사인 위치 인코딩으로 주입한다.',
    results:
      '영-독 28.4 BLEU, 영-불 41.8 BLEU로 기존 최고 모델을 능가하면서 학습 비용은 크게 줄였다(8 GPU로 3.5일).',
    limitations:
      '입력 길이에 대해 어텐션이 제곱 복잡도를 가져 매우 긴 시퀀스에는 비용이 크다. 위치 인코딩의 외삽 한계도 존재한다.',
    reproducibility: {
      code: '공개 — tensor2tensor 저장소에 구현 제공',
      data: '공개 — WMT 2014 표준 벤치마크 사용',
    },
    anchors: [
      { field: 'results', target: 'table', span: 'EN-DE 28.4 BLEU', label: '표 2' },
      { field: 'method', target: 'section', span: 'Multi-Head Attention', label: '§3.2' },
      { field: 'reproducibility', target: 'section', span: 'tensor2tensor', label: '§6.1' },
    ],
  },
};

// 입문자용(beginner) = SSOT §9.2 정책에 부합: "전문용어 첫 등장 시 괄호 설명 · 약어 첫 등장 시
// 원문 전개 · 이후 등장은 원어 유지". 핵심은 용어를 한글로 음차/치환하지 않고 **영문 원어로 두고**
// 첫 등장 때만 한국어로 괄호 풀이 → 원문·타 자료와 용어 연속성 유지.
export const beginnerSummaryResponse: SummaryOkDTO = {
  ...summaryResponse,
  summary: {
    ...summaryResponse.summary,
    tldr: '기존의 RNN·CNN(recurrent·convolutional neural network, 데이터를 순서대로/지역적으로 처리하던 신경망) 없이, attention(문장에서 단어들 사이의 관련성에 “집중”해 가중치를 매기는 계산)만으로 sequence transduction(한 문장을 다른 문장으로 바꾸는 작업 — 예: 번역)을 수행하는 Transformer를 제안한다. recurrence·convolution을 없애 병렬화가 쉬워 학습이 빠르고, 번역 품질도 당시 최고 수준이다.',
    method:
      'encoder(입력 문장을 이해해 내부 표현으로 바꾸는 부분)와 decoder(그 표현으로 출력 문장을 만드는 부분)를 각각 6개 층으로 쌓는다. 각 층은 multi-head self-attention(여러 관점에서 동시에 단어 간 관련성을 보는 attention)과 position-wise feed-forward network(각 단어를 개별적으로 변환하는 작은 신경망)로 구성된다. 순서 정보는 positional encoding(단어의 위치를 sine·cosine 패턴으로 표시)으로 더한다.',
  },
};

// Structured translation (BR-S18): the translation output is a "translated doc-model" — same
// structure/ids as the body, Korean text; formula LaTeX / table cells stay verbatim.
const _provenance = {
  sourceTier: 'ar5iv' as const,
  parserVersion: 'docmodel-parser@1',
  schemaVersion: '1.0.0',
  generatedAt: '2026-06-23T00:00:00Z',
};

export const abstractTranslationResponse: TranslationOkDTO = {
  status: 'ok',
  task: 'translate',
  meta: { source: 'abstract' },
  cached: false,
  translation: {
    docModel: {
      meta: { paperId: '2401.00001', version: 1, title: '', provenance: _provenance },
      fullText:
        '지배적인 시퀀스 변환 모델들은 복잡한 순환 신경망이나 합성곱 신경망에 기반한다. 우리는 순환과 합성곱을 완전히 배제하고 오직 어텐션 메커니즘에만 기반한 새로운 단순 네트워크 구조인 Transformer를 제안한다.',
      sections: [
        {
          id: 's1',
          title: '',
          blocks: [
            {
              id: 's1.p1',
              type: 'paragraph',
              text: '지배적인 시퀀스 변환 모델들은 복잡한 순환 신경망이나 합성곱 신경망에 기반한다. 우리는 순환과 합성곱을 완전히 배제하고 오직 어텐션 메커니즘에만 기반한 새로운 단순 네트워크 구조인 Transformer를 제안한다.',
            },
          ],
        },
      ],
    },
    keptTerms: ['Transformer', 'attention', 'BLEU'],
    // seed keep-as-is present (English) + the attention mapping (Korean is in the text)
    standardGlossary: [
      { term: 'Transformer' },
      { term: 'BLEU' },
      { term: 'attention', translated: '어텐션' },
    ],
  },
};

// Mirrors `docModelResponse` (same ids → figures join `assetsResponse` by assetId), Korean text;
// formula LaTeX and table cells are preserved verbatim (D8/BR-S18).
export const fullTranslationResponse: TranslationOkDTO = {
  status: 'ok',
  task: 'translate',
  meta: { source: 'full_text' },
  cached: false,
  translation: {
    docModel: {
      meta: {
        paperId: '2401.00001',
        version: 1,
        title: '어텐션만 있으면 된다',
        provenance: _provenance,
      },
      fullText:
        '초록\n\n지배적인 시퀀스 변환 모델들은 인코더와 디코더를 포함한 복잡한 순환 신경망이나 합성곱 신경망에 기반한다. 우리는 순환과 합성곱을 완전히 배제하고 오직 어텐션 메커니즘에만 기반한 새로운 단순 네트워크 구조인 Transformer를 제안한다.\n\n모델 구조\n\nTransformer는 순환 대신 스케일드 닷-프로덕트 어텐션 \\(\\mathrm{Attention}(Q,K,V)\\)을 사용한다.\n\n\\mathrm{Attention}(Q,K,V)=\\mathrm{softmax}\\left(\\frac{QK^{T}}{\\sqrt{d_{k}}}\\right)V\n\nFigure 1 Transformer — 모델 구조.\n\n셀프 어텐션을 쓰는 이유\n\nTable 1 최대 경로 길이와 층별 복잡도.',
      sections: [
        {
          id: 's0',
          title: '초록',
          blocks: [
            {
              id: 's0.p1',
              type: 'paragraph',
              text: '지배적인 시퀀스 변환 모델들은 인코더와 디코더를 포함한 복잡한 순환 신경망이나 합성곱 신경망에 기반한다. 우리는 순환과 합성곱을 완전히 배제하고 오직 어텐션 메커니즘에만 기반한 새로운 단순 네트워크 구조인 Transformer를 제안한다.',
            },
          ],
        },
        {
          id: 's3',
          title: '모델 구조',
          blocks: [
            {
              id: 's3.p1',
              type: 'paragraph',
              text: 'Transformer는 순환 대신 스케일드 닷-프로덕트 어텐션 \\(\\mathrm{Attention}(Q,K,V)\\)을 사용한다.',
            },
            {
              id: 's3.eq1',
              type: 'formula',
              latex:
                '\\mathrm{Attention}(Q,K,V)=\\mathrm{softmax}\\left(\\frac{QK^{T}}{\\sqrt{d_{k}}}\\right)V',
              display: true,
              anchorLabel: '(1)',
            },
            {
              // Mirrors the 전문 fixture: a formula with neither LaTeX nor a joinable crop →
              // degrades to a numbered placeholder (structure parity with the original).
              id: 's3.eq2',
              type: 'formula',
              display: true,
              anchorLabel: '(2)',
            },
            {
              id: 's3.fig1',
              type: 'figure',
              assetRef: { assetId: '2401.00001:v1:figure:0', type: 'figure', ordinal: 0 },
              caption: 'Transformer — 모델 구조.',
              anchorLabel: 'Figure 1',
            },
          ],
          sections: [
            {
              id: 's3.2',
              title: '셀프 어텐션을 쓰는 이유',
              blocks: [
                {
                  id: 's3.2.tbl1',
                  type: 'table',
                  caption: '최대 경로 길이와 층별 복잡도.',
                  anchorLabel: 'Table 1',
                  rows: [
                    {
                      cells: [
                        { text: '층 종류', isHeader: true },
                        { text: '복잡도', isHeader: true },
                        { text: '경로 길이', isHeader: true },
                      ],
                    },
                    {
                      cells: [
                        { text: 'Self-Attention' },
                        { text: '\\(O(n^{2}\\cdot d)\\)' },
                        { text: '\\(O(1)\\)' },
                      ],
                    },
                    {
                      cells: [
                        { text: 'Recurrent' },
                        { text: '\\(O(n\\cdot d^{2})\\)' },
                        { text: '\\(O(n)\\)' },
                      ],
                    },
                  ],
                },
              ],
            },
          ],
        },
        ..._fillerSections('ko'),
      ],
    },
    keptTerms: ['Transformer', 'encoder', 'decoder', 'self-attention'],
    // Transformer = keep-as-is standard (English); attention→어텐션 mapping appears in the text
    standardGlossary: [{ term: 'Transformer' }, { term: 'attention', translated: '어텐션' }],
  },
};

// Personal glossary (Phase 1/2a) — an in-memory store so the dev preview behaves like the
// real round-trip: upsert remembers termFrom→termTo and bumps a version, and the list reads
// it back so the badge editor pre-fills a previously saved rendering.
const mockGlossary = new Map<string, { termTo: string; promptEnforced: boolean }>();
let mockGlossaryVer = 0;

export function mockUpsertGlossaryTerm(
  termFrom: string,
  termTo: string,
  promptEnforced = false,
): GlossaryUpsertResultDTO {
  mockGlossary.set(termFrom, { termTo, promptEnforced });
  mockGlossaryVer += 1;
  return { status: 'ok', glossaryVer: mockGlossaryVer };
}

export function mockListGlossaryTerms(): GlossaryTermDTO[] {
  return [...mockGlossary.entries()].map(([termFrom, { termTo, promptEnforced }]) => ({
    termFrom,
    termTo,
    promptEnforced,
  }));
}

/** Reset the in-memory glossary so tests start from a clean store (no cross-test bleed). */
export function resetMockGlossary(): void {
  mockGlossary.clear();
  mockGlossaryVer = 0;
}

function substituteWeak(text: string): string {
  let out = text;
  for (const [termFrom, { termTo, promptEnforced }] of mockGlossary) {
    if (promptEnforced || !termFrom) continue; // strong needs a real regenerate; weak = post-sub
    out = out.split(termFrom).join(termTo);
  }
  return out;
}

// Walk the doc-model recursively, substituting weak terms in the human-readable string fields.
function overlayNode(node: unknown): void {
  if (Array.isArray(node)) {
    node.forEach(overlayNode);
    return;
  }
  if (!node || typeof node !== 'object') return;
  const obj = node as Record<string, unknown>;
  for (const field of ['fullText', 'text', 'title', 'caption']) {
    if (typeof obj[field] === 'string') obj[field] = substituteWeak(obj[field]);
  }
  overlayNode(obj.sections);
  overlayNode(obj.blocks);
}

/** Dev-only: mirror the server's read-time weak overlay so applying a 원어 유지 term visibly changes
 * the mock translation. Strong terms would need a real re-generation the mock can't do, so they are
 * left untouched. No-op (returns the shared fixture) when the user has no weak terms. */
export function withWeakOverlay(res: TranslationOkDTO): TranslationOkDTO {
  const hasWeak = [...mockGlossary.values()].some((v) => !v.promptEnforced);
  if (!hasWeak) return res;
  const clone = structuredClone(res);
  overlayNode(clone.translation.docModel);
  return clone;
}

// Dev preview only: personalize one non-standard kept term ('encoder' → 인코더) so the "원어 유지
// 용어" section shows a saved rendering out of the box. Tests reset the store first, so they start
// empty. Non-standard terms save weak (표준 용어 are the strong / re-translated case).
mockUpsertGlossaryTerm('encoder', '인코더', false);

// FR-17 figure/table assets (dev preview). Inline SVG data URLs render without network.
const _ph = (label: string, fill: string): string =>
  `data:image/svg+xml;utf8,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="200"><rect width="100%" height="100%" fill="${fill}"/><text x="50%" y="50%" font-size="20" fill="#333" text-anchor="middle" dominant-baseline="middle">${label}</text></svg>`,
  )}`;

export const assetsResponse: AssetsOkDTO = {
  status: 'ok',
  assets: [
    {
      assetId: '2401.00001:v1:figure:0',
      type: 'figure',
      ordinal: 0,
      caption: 'Figure 1: The Transformer — model architecture.',
      sourceMode: 'page-crop',
      url: _ph('Figure 1', '#e8f0fe'),
    },
    {
      assetId: '2401.00001:v1:table:0',
      type: 'table',
      ordinal: 0,
      caption: 'Table 1: BLEU scores on WMT 2014.',
      sourceMode: 'page-crop',
      url: _ph('Table 1', '#fef7e0'),
    },
  ],
};

// Doc-model rich-view fixture (D4). Figure assetIds match `assetsResponse` so the
// DocModelViewer ↔ /assets join (by assetId) is exercised in the mock preview.
export const docModelResponse: DocModelOkDTO = {
  status: 'ok',
  cached: false,
  docModel: {
    meta: {
      paperId: '2401.00001',
      version: 1,
      title: 'Attention Is All You Need',
      abstract:
        'The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely.',
      provenance: {
        sourceTier: 'ar5iv',
        parserVersion: 'docmodel-parser@1',
        schemaVersion: '1.0.0',
        generatedAt: '2026-06-23T00:00:00Z',
      },
    },
    fullText:
      'Abstract\n\nThe dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely.\n\nModel Architecture\n\nThe Transformer uses scaled dot-product attention \\(\\mathrm{Attention}(Q,K,V)\\) in place of recurrence.\n\n\\mathrm{Attention}(Q,K,V)=\\mathrm{softmax}\\left(\\frac{QK^{T}}{\\sqrt{d_{k}}}\\right)V\n\nFigure 1 The Transformer — model architecture.\n\nWhy Self-Attention\n\nTable 1 Maximum path lengths and per-layer complexity.',
    sections: [
      {
        id: 's0',
        title: 'Abstract',
        blocks: [
          {
            id: 's0.p1',
            type: 'paragraph',
            text: 'The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely.',
          },
        ],
      },
      {
        id: 's3',
        title: 'Model Architecture',
        blocks: [
          {
            id: 's3.p1',
            type: 'paragraph',
            text: 'The Transformer uses scaled dot-product attention \\(\\mathrm{Attention}(Q,K,V)\\) in place of recurrence.',
          },
          {
            id: 's3.eq1',
            type: 'formula',
            latex:
              '\\mathrm{Attention}(Q,K,V)=\\mathrm{softmax}\\left(\\frac{QK^{T}}{\\sqrt{d_{k}}}\\right)V',
            display: true,
            anchorLabel: '(1)',
          },
          {
            // Image-fallback equation whose page-crop asset is unavailable (crops env-gated /
            // still building): neither latex nor a joinable assetRef. Must degrade to a numbered
            // placeholder, not vanish.
            id: 's3.eq2',
            type: 'formula',
            display: true,
            anchorLabel: '(2)',
          },
          {
            id: 's3.fig1',
            type: 'figure',
            assetRef: { assetId: '2401.00001:v1:figure:0', type: 'figure', ordinal: 0 },
            caption: 'The Transformer — model architecture.',
            anchorLabel: 'Figure 1',
          },
        ],
        sections: [
          {
            id: 's3.2',
            title: 'Why Self-Attention',
            blocks: [
              {
                id: 's3.2.tbl1',
                type: 'table',
                caption: 'Maximum path lengths and per-layer complexity.',
                anchorLabel: 'Table 1',
                rows: [
                  {
                    cells: [
                      { text: 'Layer Type', isHeader: true },
                      { text: 'Complexity', isHeader: true },
                      { text: 'Path Length', isHeader: true },
                    ],
                  },
                  {
                    cells: [
                      { text: 'Self-Attention' },
                      { text: '\\(O(n^{2}\\cdot d)\\)' },
                      { text: '\\(O(1)\\)' },
                    ],
                  },
                  {
                    cells: [
                      { text: 'Recurrent' },
                      { text: '\\(O(n\\cdot d^{2})\\)' },
                      { text: '\\(O(n)\\)' },
                    ],
                  },
                ],
              },
            ],
          },
        ],
      },
      ..._fillerSections('en'),
    ],
  },
};
