/**
 * 본문(doc-model) 화면으로 가는 링크 — **조립은 여기 하나뿐이다.**
 *
 * 종전에는 세 곳이 각자 만들었다(논문 상세의 본문 버튼·앵커 이동, 근거 목록의 인용 위치).
 * 그 대가가 실제로 나왔다: 근거 쪽만 `anchorLabel`을 안 실어, 블록 id가 그 문서에 없을 때
 * 뷰어가 라벨로 떨어질 수 없어 **스크롤이 조용히 안 됐다**(`DocModelViewer.resolveAnchorId`가
 * blockId → label 순으로 찾는다). 근거의 앵커는 `표 3`·`4.2절` 같은 라벨꼴이 흔해서 그
 * 폴백이 가장 필요한 쪽이었다.
 */
import { arxivVersion } from './arxivVersion';

/**
 * 초록 섹션의 id. U1이 초록을 전용 섹션으로 내고 본문 뷰어는 그것을 **목록에서 뺀다**
 * (초록은 별도 화면이다). 그래서 이 섹션의 블록을 anchorId로 넘기면 뷰어가 id는 찾아내지만
 * 그릴 요소가 없어 아무 일도 안 한다 — 그런 앵커는 본문이 아니라 상세로 보내야 한다.
 * **뷰어의 필터와 이 상수가 같은 값을 읽어야 한다.**
 */
export const ABSTRACT_SECTION_ID = 's0';

/** 이 앵커가 본문 뷰어에서 실제로 보이는 자리인가. */
export function isAbstractAnchor(anchor: string): boolean {
  return anchor === ABSTRACT_SECTION_ID || anchor.startsWith(`${ABSTRACT_SECTION_ID}.`);
}

export interface DocModelAnchor {
  /** doc-model 블록 id. 뷰어가 먼저 이것으로 찾는다. */
  blockId?: string | null;
  /** 블록 id가 그 문서에 없을 때 뷰어가 떨어질 자리 — **빠뜨리면 폴백이 죽는다**. */
  label?: string | null;
  span?: string | null;
}

/** `/paper/{id}/doc-model?version=…[&anchorId=…][&anchorLabel=…][&anchorSpan=…]` */
export function docModelHref(
  paperId: string,
  anchor?: DocModelAnchor | null,
  /** 호출자가 판을 알면 그것을 쓴다. 모르면 id에서 유도한다(라우트도 같은 규칙이다). */
  version?: number,
): string {
  const params = new URLSearchParams({ version: String(version ?? arxivVersion(paperId)) });
  if (anchor?.blockId) params.set('anchorId', anchor.blockId);
  if (anchor?.label) {
    params.set('anchorLabel', anchor.label);
    if (anchor.span) params.set('anchorSpan', anchor.span);
  }
  return `/paper/${encodeURIComponent(paperId)}/doc-model?${params.toString()}`;
}
