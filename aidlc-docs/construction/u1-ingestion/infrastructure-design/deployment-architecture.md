# deployment-architecture.md — U1 Ingestion 배포 아키텍처 (멀티모달 자산 범위)

**단계**: CONSTRUCTION → Infrastructure Design · **유닛**: U1 Ingestion · **일자**: 2026-06-22 · **브랜치**: `feature/multimodal-display`
**근거**: `infrastructure-design.md`(동일 디렉터리) · U1 NFR Design §5 · 계획 Q1~Q5=A
**스코프**: FR-17 자산 추출의 컴퓨트 co-location·전달 경로·기존 토폴로지 관계. **선결 상속**: 워커 런타임 타깃(ECS/Fargate vs Lambda)·리전·CD = 미결(TD-9), 본 기능 비결정.

---

## 1. 컴퓨트 co-location (Q4=A)
- 자산 추출(AssetExtractor·Image Normalizer)은 **기존 Ingestion Worker 태스크에 co-locate** — 별도 컴퓨트·큐 0(NFR Q4=A). 모듈형 모놀리스 워커 내 도메인 컴포넌트(NFR Design §2 매핑과 동형).
- **사이징**: PDF 페이지 렌더(PyMuPDF)·이미지 디코드/리사이즈는 **메모리 집약** → 워커 태스크에 이미지 처리 **메모리 헤드룸** 확보(픽셀 상한 ~30MP 가드와 정합, patterns §7.2). CPU만(ML/GPU 없음).
- **런타임 타깃**: ECS/Fargate vs Lambda는 **선결 상속**(미결). co-location은 타깃 무관(둘 다 워커 프로세스 내 컴포넌트).

## 2. 배포 토폴로지 (자산 분기)

```mermaid
graph LR
    subgraph Ingestion[Ingestion Worker (기존 태스크)]
      AX[AssetExtractor] --> NM[Image Normalizer]
    end
    NM -->|PutObject webp| S3[(S3 assets/ prefix<br/>private·SSE-KMS)]
    NM -->|upsert 매니페스트| RDS[(공유 RDS<br/>paper_asset)]
    AX -.->|index 경로(불변)| OS[(OpenSearch)]

    subgraph Read[U7 읽기 측]
      API[full-text/paper API]
    end
    API -->|SELECT paper_asset| RDS
    API -->|presign GET ~10m| S3
    API -->|서명 URL| Client[U5 상세/뷰어]
```

- 쓰기(인제스천 워커)와 읽기(U7)가 **공유 S3 prefix + 공유 RDS 테이블**을 매개. 인덱스 경로(OpenSearch)와 독립.

## 3. 자산 전달 경로 (Q2=A)
- **v1**: U7이 presigned S3 URL(만료 ~10분) 발급 → U5가 S3에서 직접 로드. 최소 인프라.
- **CloudFront CDN**: 후속(성능 트랙). 도입 시 OAC + 서명 URL/쿠키, 캐시 무효화 정책 추가.

## 4. 배포·마이그레이션
- **`paper_asset` 마이그레이션**: 공유 RDS 마이그레이션 파이프라인으로 적용(기존 패턴). 워커 배포 전 스키마 선적용.
- **워커 이미지**: 기존 인제스천 컨테이너에 추출 의존성(PyMuPDF·이미지 라이브러리) 추가, 다이제스트 핀(SEC-10, TD-9/10). SBOM/SCA에 신규 의존성 포함.
- **CD/롤백**: 기존 U1 CD(미결 상속). 자산 기능은 추출 실패 best-effort라 점진 롤아웃 안전(자산 없어도 텍스트 상세 정상).

## 5. 기존 U1 토폴로지와의 관계
- §1~5 기존 토폴로지(EventBridge·SQS·Worker·OpenSearch·Bedrock·전문 S3)·verify-all-then-commit **불변**.
- 추가분: 워커 내 자산 컴포넌트 + S3 `assets/` prefix + `paper_asset` RDS + (읽기) presign. 모두 인덱스 경로와 분리(best-effort).

---

> 비용·IAM·KMS·스키마 상세는 `infrastructure-design.md`. 다음 단계 = U1 Code Generation(추출·정규화·AssetStore 구현, `paper_asset` 마이그레이션).
