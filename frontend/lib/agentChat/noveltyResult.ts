// novelty result(JSON-in-content) 타입과 가드 — evidence 결과와 동일한 seam으로
// 구조화 아티팩트를 메시지 content에 실어 세션 영속/재열람에서도 구조를 유지한다.

export interface NoveltySourceRef {
  type?: string | null;
  identifier?: string | null;
  title?: string | null;
  url?: string | null;
}

export interface NoveltyPayloadItem {
  title?: string;
  summary?: string;
  rationale?: string;
  riskType?: string;
  evidenceStatus?: string;
  evidenceNote?: string;
  confidence?: number;
  queryUsed?: string;
  sourceRefs?: NoveltySourceRef[];
  // US-NV3(#253) 유사 연구 표 상세 칼럼 — 백엔드가 근거 없는 칸을 null(기권)로 보낸다.
  problem?: string | null;
  method?: string | null;
  dataset?: string | null;
  results?: string | null;
  limitations?: string | null;
  overlap?: string | null;
}

export const SIMILAR_WORK_COLUMNS: ReadonlyArray<{ key: string; label: string }> = [
  { key: 'problem', label: '문제정의' },
  { key: 'method', label: '방법' },
  { key: 'dataset', label: '데이터셋' },
  { key: 'results', label: '결과' },
  { key: 'limitations', label: '한계' },
  { key: 'overlap', label: '겹치는 점' },
];

// 칸 값은 비어있지 않은 문자열만 유효 — null/누락은 기권이라 '근거 부족' 표시 대상.
export function detailCell(item: NoveltyPayloadItem, key: string): string | null {
  const value = (item as Record<string, unknown>)[key];
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

export interface NoveltyArtifact {
  artifactId: string;
  kind: string;
  title: string;
  payload: Record<string, unknown>;
  createdAt?: string;
}

export interface NoveltyResultPayload {
  kind: 'novelty';
  artifacts: NoveltyArtifact[];
}

export function isNoveltyResultPayload(value: unknown): value is NoveltyResultPayload {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return candidate.kind === 'novelty' && Array.isArray(candidate.artifacts);
}

// payload.items — 백엔드 LLM/similarity 어댑터의 공통 컨벤션({ items: [...] }).
export function itemsOf(payload: Record<string, unknown>): NoveltyPayloadItem[] {
  const items = payload.items;
  return Array.isArray(items) ? (items as NoveltyPayloadItem[]) : [];
}

export function sourceRefsOf(value: unknown): NoveltySourceRef[] {
  return Array.isArray(value) ? (value as NoveltySourceRef[]) : [];
}

export function textField(payload: Record<string, unknown>, key: string): string {
  const value = payload[key];
  return typeof value === 'string' ? value : '';
}

export function listField(payload: Record<string, unknown>, key: string): string[] {
  const value = payload[key];
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === 'string');
}

/**
 * 첫 번째로 값이 있는 키를 고른다. v2 산출물은 snake_case(백엔드 도메인 모델 그대로)이고
 * v1 시절 저장분은 camelCase라, 같은 뷰가 둘을 함께 읽어야 한다.
 */
export function pickText(payload: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const value = textField(payload, key);
    if (value) return value;
  }
  return '';
}

export function pickList(payload: Record<string, unknown>, ...keys: string[]): string[] {
  for (const key of keys) {
    const values = listField(payload, key);
    if (values.length > 0) return values;
  }
  return [];
}

export function pickRefs(
  payload: Record<string, unknown>,
  ...keys: string[]
): NoveltySourceRef[] {
  for (const key of keys) {
    const refs = sourceRefsOf(payload[key]);
    if (refs.length > 0) return refs;
  }
  return [];
}

export function confidenceLabel(value: unknown): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}
