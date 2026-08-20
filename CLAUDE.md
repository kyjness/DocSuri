# CLAUDE.md

DocSuri에서 코딩 에이전트가 **작업 전에 반드시 읽어야 할 것**과, 저장소를 훑어서는 바로 안
보이는 규칙만 모았다. 설계 결정의 정본은 여기가 아니라 `aidlc-docs/`다 — 이 파일은 어디를
봐야 하는지까지만 적는다.

## 먼저 읽는다

| 문서 | 언제 |
|---|---|
| [`CONVENTIONS.md`](CONVENTIONS.md) | **브랜치를 만들기 전.** 브랜치 접두사·커밋 제목/본문 형식·태그의 정본 |
| [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md) | PR 본문을 쓰기 전. **절 이름을 그대로** 쓰고 해당 없는 절은 지운다 |
| [`AGENTS.md`](AGENTS.md) · `.aidlc-rule-details/` | 문서 생명주기(AIDLC). git은 다루지 않는다 |
| [`aidlc-docs/operations/solo-roadmap.md`](aidlc-docs/operations/solo-roadmap.md) | 지금 어느 단계인지, 각 단계의 실측 수치 |
| [`aidlc-docs/inception/requirements/`](aidlc-docs/inception/requirements/) | 설계 질문의 확정 답과 그 근거 |

커밋·PR 제목은 **한국어 명사구**다(`type(scope):` prefix만 영어). 동사 종결 금지. 본문은
갈래별 굵은 소제목 아래 관찰을 `-`로, 해법을 `→` 한 줄로, 숫자는 **실측** 블록에 따로.
**PR 본문도 같은 기준을 템플릿 절 안에서** 적용한다. 정본은 CONVENTIONS.md이고 예시도 거기
있다 — 분량 기준(작은 수정에 긴 본문은 판단력 부족으로 읽힌다)도 그쪽에 있다.

## 커밋 하나하나가 단독으로 통과해야 한다

이 저장소는 squash가 아니라 **merge commit**으로 통합한다(`git log --merges --oneline`으로
확인된다). 즉 중간 커밋이 `develop`에 영구히 남고, `git bisect`가 밟는 것은 CI가 **한 번도
본 적 없는** 커밋들이다. CI는 브랜치 tip만 검사한다.

그래서 커밋을 나눴다면 각 시점을 checkout해 로컬에서 돌려야 한다:

```bash
for c in $(git log --format=%h --reverse <base>..HEAD); do git checkout -q $c && ...; done
```

**커밋을 남발하지 않는다.** 같은 작업의 코드·테스트·도구·문서는 한 커밋에 함께 간다 — 파일
종류나 변경 성격은 분할 사유가 아니다. 특히 **"같은 종류의 자리를 전수로 확인했나"**를 커밋
전에 묻는다. 세 곳 중 둘만 고치면 나머지 하나가 다음 커밋이 되고, 로그에는 같은 제목이 두 번
남는다(실제로 그렇게 됐다).

## 검사

패키지마다 자기 lane이 있다. CI(`.github/workflows/ci.yml`)와 같은 명령을 그대로 돌린다.

```bash
cd shared/python              && uv run ruff check . && uv run pytest -rs
cd ingestion                  && uv run ruff check . && uv run pytest -rs
cd backend                    && uv run ruff check . && uv run --extra api --extra real pytest -rs
cd backend/modules/discovery  && uv run ruff check . && uv run pytest -rs
cd backend/modules/summarization && uv run ruff check . && uv run pytest -rs
```

세 가지가 조용히 어긋난다:

- **`backend`에서 `ruff check .`는 `modules/`를 안 본다** (`extend-exclude = ["modules"]`).
  모듈은 자기 lane에서 따로 린트된다. 셸에서 한 번 돌리고 "전부 통과"로 읽으면 안 된다.
- **backend 테스트에 `.env`를 소스하면 안 된다.** 인증 설정이 덮여 수십 건이 실패한다.
  Postgres가 필요한 테스트에는 DSN 하나만 준다(`DOCSURI_TEST_PG_DSN=...`).
- **ingestion의 Postgres 테스트는 ingestion 테이블이 있는 DB를 요구한다.** 없는 DB를 주면
  `UndefinedTable`로 죽거나 조용히 skip된다 — 두 스토어가 갈리는 것을 잡는 유일한 검증이라,
  안 돌면 초록으로 보인다.

## 로컬 스택

```bash
set -a && . ./.env && set +a          # 반드시 먼저
docker compose -f backend/docker-compose.yml up -d postgres opensearch s3proxy redis elasticmq
docker compose -f backend/docker-compose.yml --profile ingest up -d grobid   # 파싱할 때만
```

**`.env` 소스가 빠지면 s3proxy가 아예 안 뜬다.** 일부러 그렇게 해뒀다 — 예전에는 기본값으로
개발 코퍼스가 조용히 마운트됐고, 컨테이너는 healthy로 뜨고 S3 API도 정상 응답해서 어디에도
오류가 안 보였다. 배치는 대상 논문의 대부분을 "없음"으로 건너뛰고 exit 0을 냈다.

GROBID는 opt-in 프로필이다. 메모리를 많이 쓰고 Docling과 동시에 뜨기 어려우니, 필요할 때만
올리고 쓰고 나면 내린다.

## 이 저장소에서 반복된 실패 모양

버그보다 **조용한 열화**가 많았다. 실패가 예외로 드러나지 않고 "결과가 적을 뿐"으로 보여서,
로그만 봐서는 멈출 이유가 없어 보이는 종류다. 판단이 갈리면 **카운터나 로그가 아니라 저장된
산출물을 직접 센다.**

- 묶음 조회가 막히자 개별 조회로 내려가 벌칙을 키웠다 — 로그는 정상처럼 흘렀다
- `skipped=N`과 `exit 0`이 "할 일이 없었다"와 "대상을 못 찾았다"를 구분하지 못했다
- 자산 API의 `{"assets": []}`가 "그림 없음"과 "그림을 못 만들었음" 양쪽이었다
