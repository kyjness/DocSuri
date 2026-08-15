<!-- 출처: solo-local-migration.md §7 (2026-07). 그 문서가 폐기되면서 분리 — 이 내용은
     AWS/로컬 이관과 무관하게 파서에 계속 유효하다. -->

# GROBID 표 셀 복원의 한계와 업그레이드 경로

GROBID 0.8.0은 다중행 헤더가 있는 표에서 셀을 병합·절단해 내보낸다. 픽스처 논문 `2210.12090`의
Table 2에서 `Dimensionality Reduction`이 `'Dimensionality Fast ICA '`로 합쳐지고 `PCA (1)`이
이웃 셀에 먹힌다. **TEI 원본이 이미 그 상태**이므로 파서에서 고칠 수 있는 문제가 아니다.
셀을 재분할하는 휴리스틱은 원본에 없는 정보를 추정하는 것이고, 그렇게 만든 숫자를 U7 grounding의
numeric-match가 그대로 신뢰하므로 **틀린 숫자가 빈칸보다 나쁘다**. 넣지 않는다.

노출 범위는 제한적이다 — `application.py`가 arXiv 논문에 ar5iv HTML을 먼저 쓰고 PDF/GROBID는
`status="pdf_fallback"`이다. 같은 논문의 ar5iv 경로는 표 6개를 셀 손상 없이 만든다. 즉 이 손상은
ar5iv가 없는 비-arXiv 소스(S2/OpenAlex)에서 주로 드러난다.

품질을 올려야 할 때의 선택지와 **라이선스 함정**(이 저장소는 TD-11/13에서 이미 AGPL 때문에
PyMuPDF를 회피했다):

| 후보 | 라이선스 | 비고 |
|---|---|---|
| Docling / TableFormer (IBM) | MIT | 로컬 CPU 구동 가능. 현재 오픈 기본값으로 가장 무난 |
| Table Transformer (MS) | MIT | PubTables-1M 학습, 검출+구조 인식 분리 |
| PP-StructureV2 (PaddleOCR) | Apache-2.0 | 표 구조를 HTML로 |
| Nougat (Meta) | **CC BY-NC** | 상업 이용 불가 — 채택 불가 |
| Marker | **상용 제한** | 채택 불가 |

가장 싼 경로는 새 엔진 도입이 아니라 **이미 저장돼 있는 표 크롭 이미지를 필요한 시점에 vision
모델로 재판독**하는 것이다. 설계가 애초에 그 용도로 크롭을 남겨두고 있다(D8 / TD-11,
`docmodel/tei.py`의 table 크롭 주석).
