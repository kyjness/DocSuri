# 데모 배포 런북 — Lightsail 단일 인스턴스

로드맵 ⑪. 토폴로지의 정본은 `aidlc-docs/construction/infrastructure-design/infrastructure-design.md`
§12이고, 사양의 정본은 코퍼스·배포 질문지 Q1이다(§12보다 **질문지가 최신**이다 — 2026-08-15에
4 GB → 8 GB로 개정됐고 §12는 취소선으로 표시돼 있다).

`ops/cdk/`(실서비스 토폴로지 ECS/ALB/RDS/OpenSearch Domain)는 **이 배포에 쓰지 않는다.**
설계 기록으로 보존만 한다(§12.5). 배포와 관련된 작업은 전부 이 디렉터리에서 한다.

| | |
|---|---|
| 박스 | Lightsail `large_3_0` — 8 GB · 2 vCPU · SSD 160 GB, $44/월 (3개월 $144) |
| 리전 | `ap-northeast-2` |
| 도메인 | `docsuri.shop` (가비아에서 구매 — DNS도 가비아에 둔다) |
| 코퍼스 | 3,248편 = 편수 천장(약 3,500편)의 **93%** |
| 배포 | 수동 — `deploy.sh` (rsync + ssh, 박스에서 빌드) |

## 배포본이 로컬과 다르게 도는 것

배포 후에 만나면 셋 다 결함으로 오인된다. **의도된 차이**다.

- **본문 승격이 안 된다.** 승격은 `BUILD_DOC_MODEL` 잡을 큐에 넣고 워커가 받아야 하는데,
  여기엔 SQS도 그 워커도 없다. **코퍼스 밖 논문은 초록까지만** 답에 쓰인다.
- **백그라운드 색인이 꺼진다.** `DOCSURI_SQS_QUEUE_URL`이 없으면 조용히 꺼지도록 만들어 뒀다.
  "쓸수록 코퍼스가 자란다"는 여기서 성립하지 않는다 — 파싱 스택을 안 올렸고(Q7=B) 색인이
  이미 천장의 93%라 자랄 자리도 없다.
- **Novelty 모드가 안 보인다.** ⑩-2를 하지 않기로 했으므로 진입점을 안 낸다. 코드는 살아
  있고 `compose.prod.yml`의 **빌드 인자**로 막는다 — 런타임 env가 아니다.
- **실시간 조회는 켜야 한다.** 기본이 off인데 배포 코퍼스가 얇으므로 여기서는 켜는 쪽이
  맞다(`.env.prod`에 `DOCSURI_EVIDENCE_LIVE_LOOKUP_ENABLED=true`).

## 1. 인프라

```bash
cd ops/deploy/terraform
cp terraform.tfvars.example terraform.tfvars     # ssh_public_key를 채운다
ssh-keygen -t ed25519 -C docsuri-deploy -f ~/.ssh/docsuri_deploy   # 새로 만든다
terraform init && terraform apply
```

puppytalk 배포키를 재사용하지 않는다 — 한 키가 새면 두 서비스가 함께 열린다.

출력에서 다음을 받는다:

| 출력 | 쓰는 곳 |
|---|---|
| `static_ip` | 가비아 DNS의 A 레코드 |
| `s3_bucket` | `.env.prod`의 `DOCSURI_DOCMODEL_BUCKET`·`DOCSURI_SUMMARY_BUCKET` |
| `app_access_key_id` / `app_secret_access_key` | `.env.prod`의 AWS 자격증명 |

시크릿은 `terraform output -raw app_secret_access_key`로 꺼낸다. **`terraform.tfstate`를
커밋하지 않는다** — 액세스 키가 평문으로 들어 있다(`.gitignore`에 있다).

## 2. DNS (가비아)

가비아 DNS 관리에서 A 레코드 둘을 만든다. Route 53으로 위임하지 않는다 — 호스팅 영역이
월 $0.50인데 데모 배포에서 그 값을 하는 일이 A 레코드 하나뿐이다.

| 호스트 | 타입 | 값 |
|---|---|---|
| `@` | A | `<static_ip>` |
| `www` | A | `<static_ip>` |

**전파를 기다린 뒤** 다음으로 간다. Caddy가 Let's Encrypt HTTP-01 챌린지를 도는데, DNS가
아직 안 퍼졌으면 발급에 실패하고 **실패 한도(주당 5회)에 걸린다.** 확인:

```bash
dig +short docsuri.shop      # static_ip가 나와야 한다
```

## 3. 시크릿

`ops/deploy/.env.prod`를 만든다(커밋 금지 — `.gitignore`에 있다). 키 설명은 저장소 루트의
`.env.example`에 있고, 배포에서만 다른 것은 아래다.

```bash
DOCSURI_DOMAIN=docsuri.shop
POSTGRES_PASSWORD=<생성한다>
DATABASE_URL=postgresql://docsuri:<위와 같은 값>@postgres:5432/docsuri_deploy
REDIS_HOST=redis
DOCSURI_OPENSEARCH_ENDPOINT=http://opensearch:9200
DOCSURI_OPENSEARCH_USE_SSL=false
DOCSURI_OPENSEARCH_VERIFY_CERTS=false
PUBLIC_APP_URL=https://docsuri.shop

AWS_DEFAULT_REGION=ap-northeast-2
AWS_ACCESS_KEY_ID=<terraform output>
AWS_SECRET_ACCESS_KEY=<terraform output>
DOCSURI_DOCMODEL_BUCKET=<terraform output s3_bucket>
DOCSURI_SUMMARY_BUCKET=<terraform output s3_bucket>

# --- 아래가 없으면 기능이 통째로 **조용히** 꺼진다 (2026-08-25 실배포에서 전부 걸렸다) ---
# `DOCSURI_BEDROCK_MODEL_ID` 하나가 없으면 discovery의 `search_enabled`가 거짓이 되고
# "discovery real read path not configured — skipping mount"만 남긴 채 **검색이 안 붙는다.**
# 같은 값이 없어 evidence 마운트도 실패한다. 예외가 아니라 INFO 로그 한 줄이라, 화면에는
# "결과 없음"으로만 보인다. **기동 로그의 `mounted=[...] skipped=[...]`를 반드시 읽는다.**
DOCSURI_LLM_PROVIDER=bedrock
DOCSURI_EMBEDDING_PROVIDER=bedrock
DOCSURI_NOVELTY_LLM_PROVIDER=bedrock
DOCSURI_BEDROCK_MODEL_ID=global.cohere.embed-v4:0
DOCSURI_BEDROCK_REGION=us-east-1
DOCSURI_EMBED_REGION=us-east-1
DOCSURI_AWS_REGION=ap-northeast-2
DOCSURI_RERANK_MODEL_ARN=arn:aws:bedrock:ap-northeast-1::foundation-model/cohere.rerank-v3-5:0

# 이관한 색인 이름. 기본값을 쓰면 **없는 색인**을 본다(검색 0건, 오류 없음).
DOCSURI_OPENSEARCH_INDEX=docsuri-deploy-v1

# 없으면 summarization이 `assets=False`로 붙어 상세보기가 [그림] 자리표시자로만 뜬다.
DOCSURI_MULTIMODAL_ASSETS_ENABLED=1

CITATION_GRAPH_ENABLED=1
DOCSURI_LOCAL_SUMMARY_WORKER=1
DOCSURI_CORPUS_SOURCES=ARXIV,SEMANTIC_SCHOLAR,OPENALEX
DOCSURI_OPENALEX_MAILTO=you@example.com
DOCSURI_CONTACT_EMAIL=you@example.com

# 코퍼스가 얇으므로 켠다. 조회는 외부 API 호출뿐이라 파싱 스택이 없어도 돈다.
DOCSURI_EVIDENCE_LIVE_LOOKUP_ENABLED=true
```

**`DOCSURI_GATEWAY_URL`은 여기 없다** — 프론트 컨테이너의 런타임 env이고 `compose.prod.yml`이
직접 준다. 브라우저는 백엔드를 직접 안 부르고 같은 출처의 `/bff/*`(Next 서버 라우트)를 치며,
게이트웨이 주소를 아는 곳은 거기 하나다(SEC-3/12 — 세션 쿠키가 클라이언트 JS로 안 들어간다).
비어 있으면 BFF는 프로덕션에서 **fail-closed**로 끊는다(mock으로 안 떨어진다).

호스트 이름(`postgres`·`redis`·`opensearch`)은 compose 서비스 이름이다. `localhost`를 쓰면
컨테이너 자기 자신을 가리켜 전부 연결 거부가 된다.

**`AWS_PROFILE`을 넣지 않는다.** 넣으면 boto3가 없는 프로필을 찾다 죽는다 — 박스에는
`~/.aws`가 없다.

## 4. 코퍼스 이관

파싱 스택을 안 올리므로 로컬에서 만든 것을 옮긴다. **아래 순서는 2026-08-25에 실제로 돈 것이다.**

### 4.0. 먼저 소유자를 확인한다 — 안 하면 조용히 빈다

```bash
find ~/data/docsuri-deploy/s3 ! -readable | wc -l     # 0이어야 한다
```

파싱 배치를 root로 돌렸으면 **파일 전부가 root 소유**가 된다(실측: 52,906개 전부). 그 상태로
`aws s3 sync`를 돌리면 **전부 건너뛰고 exit 0**으로 끝나고, 배포본은 뜨는데 전문이 백지·그림이
자리표시자로 나오며 로그에는 아무 오류가 없다. 걸리면 고친다:

```bash
sudo chown -R "$USER:$USER" ~/data/docsuri-deploy/s3
```

### 4.1. 자산 → S3

```bash
aws s3 sync ~/data/docsuri-deploy/s3/ s3://<s3_bucket>/ --only-show-errors
# **양쪽을 세어 대조한다** — sync의 exit 0은 "옮겼다"가 아니라 "시도가 끝났다"이다.
find ~/data/docsuri-deploy/s3 -type f | wc -l
aws s3 ls s3://<s3_bucket>/ --recursive | wc -l
```

### 4.2. Postgres → 덤프·복원

```bash
pg_dump -h localhost -U docsuri -d docsuri_deploy -Fc -f deploy.dump
scp -i ~/.ssh/docsuri_deploy deploy.dump ec2-user@<static_ip>:/opt/docsuri/
# 박스에서 — 백엔드를 먼저 세운다. 커넥션이 남아 있으면 --clean의 DROP이 막힌다.
docker compose -f compose.prod.yml --env-file .env.prod stop backend
docker compose ... exec -T postgres pg_restore -U docsuri -d docsuri_deploy \
  --clean --if-exists --no-owner /tmp/d.dump
docker compose -f compose.prod.yml --env-file .env.prod start backend
```

**복원 뒤 반드시 자산 참조의 버킷을 고친다.** `paper_asset.object_ref`에 로컬 버킷 이름이
`s3://docsuri/...`로 **박혀 있다** — 그대로 두면 프리사인 URL이 없는 버킷을 가리켜 그림이
403이 된다. 그런데 **자산 API는 정상으로 15건을 돌려주므로** 화면에서만 그림이 안 뜨고
로그에는 아무것도 안 남는다(2026-08-25 실측).

```sql
update paper_asset
   set object_ref = replace(object_ref, 's3://docsuri/', 's3://<s3_bucket>/')
 where object_ref like 's3://docsuri/%';
```

### 4.3. OpenSearch 색인 → 스냅샷

`repository-s3` 플러그인이 없으므로 **파일시스템 스냅샷**으로 옮긴다. 로컬 OpenSearch에는
`path.repo`가 없으니, 같은 볼륨을 물린 임시 컨테이너로 뜬다(원래 컨테이너는 잠깐 세운다).

```bash
mkdir -p ~/data/os-snapshot && chmod 777 ~/data/os-snapshot
docker stop docsuri-opensearch
docker run -d --name os-snap -p 9201:9200 \
  -v docsuri_docsuri-osdata:/usr/share/opensearch/data -v ~/data/os-snapshot:/snapshots \
  -e discovery.type=single-node -e DISABLE_SECURITY_PLUGIN=true -e path.repo=/snapshots \
  opensearchproject/opensearch:2.19.0
curl -XPUT localhost:9201/_snapshot/deploy -H 'Content-Type: application/json' \
  -d '{"type":"fs","settings":{"location":"/snapshots","compress":true}}'
curl -XPUT 'localhost:9201/_snapshot/deploy/v1?wait_for_completion=true' \
  -H 'Content-Type: application/json' \
  -d '{"indices":"docsuri-deploy-v1","include_global_state":false}'
docker rm -f os-snap && docker start docsuri-opensearch
```

스냅샷(약 5.3 GB)은 S3를 경유해 박스로 옮긴다 — scp보다 재개가 쉽고 박스 쪽 내려받기가
같은 리전이라 빠르다. 박스의 `/opt/docsuri/os-snapshot`이 compose의 `/snapshots`에 물려 있다.

```bash
aws s3 sync ~/data/os-snapshot/ s3://<s3_bucket>/_ostransfer/ --only-show-errors
# 박스에서
aws s3 sync s3://<s3_bucket>/_ostransfer/ /opt/docsuri/os-snapshot/ --only-show-errors
docker compose ... exec -T opensearch curl -s -XPUT localhost:9200/_snapshot/deploy \
  -H 'Content-Type: application/json' -d '{"type":"fs","settings":{"location":"/snapshots"}}'
docker compose ... exec -T opensearch curl -s -XPOST \
  'localhost:9200/_snapshot/deploy/v1/_restore?wait_for_completion=true' \
  -H 'Content-Type: application/json' \
  -d '{"indices":"docsuri-deploy-v1","index_settings":{"index.number_of_replicas":0}}'
```

복제본을 0으로 두는 이유: 단일 노드라 복제본이 영원히 미할당으로 남아 색인이 **yellow**에
머문다. 복원이 끝나면 **green**이어야 한다.

**재색인은 대안이 아니다.** 임베딩 토큰을 다시 쓰는데 Bedrock 일일 한도(약 800만/일)를
3,248편이 하루에 못 넘긴다.

## 5. 배포

```bash
./ops/deploy/deploy.sh <static_ip>
```

첫 배포는 프론트 빌드 때문에 2 vCPU에서 몇 분 걸린다. 그 뒤로는 레이어 캐시가 받는다.

## 6. 선행 점검 — 초록을 믿지 않는다

⑧-2 1차 실행에서 **의존성 둘이 죽은 채로 5시간이 지나갔다.** 실패가 산출물이 아니라 카운터로만
드러나는 종류다. 배포 직후 손으로 확인한다. **아래는 2026-08-25에 실제로 걸린 것들이다.**

| # | 점검 | 안 하면 |
|---|---|---|
| 0 | **기동 로그의 `mounted=[...] skipped=[...]`** | env 하나가 없으면 검색·에이전트가 통째로 안 붙는데 INFO 한 줄만 남는다 |
| 1 | 색인 편수(`_cat/indices`)와 `health=green` | 검색이 조용히 적게 나오고 "논문이 드물다"로 읽힌다 |
| 2 | 논문 하나의 **전문**과 **그림**을 실제로 연다 | 전문은 `docModel.fullText`, 그림은 프리사인 URL을 **직접 쳐서 200인지** 본다 |
| 3 | 질문 하나로 **근거표까지** | 기권만 나오면 Bedrock 자격증명·리전·토큰 한도다 |
| 4 | 모드 선택에 **Novelty가 없는가** | 빌드 인자로 막았다 — 보이면 재빌드가 필요하다 |
| 5 | **테스트 계정이 남아 있지 않은가** | 덤프에 로컬 스모크 계정이 딸려 온다(실측 4건) |

0번이 가장 값싸고 가장 크다. 한 줄로 다 보인다:

```bash
docker compose -f compose.prod.yml --env-file .env.prod logs backend \
  | grep -E "mounted|skipped|failed"
# app-shell up — mounted=[... 10개 ...] skipped=[]      ← skipped가 비어야 한다
# discovery mounted (read path = real(opensearch + bedrock ...))
# summarization mounted (assets=True, docmodel=True)
# evidence mounted (real_agent=True, executor=local, checkpoints=True)
```

2번은 **API가 200이라는 것으로 끝내지 않는다.** 자산 API는 URL이 죽어 있어도 목록을 정상으로
돌려준다 — 그 URL을 실제로 쳐 봐야 안다.

## 되돌리기·정리

```bash
cd ops/deploy/terraform && terraform destroy
```

인스턴스·고정 IP·S3 버킷·IAM 사용자가 함께 지워진다. **버킷에 객체가 남아 있으면 destroy가
실패한다** — 먼저 비운다(`aws s3 rm s3://<bucket> --recursive`). 크레딧이 소진되면 이것이
"다 쓰면 종료"의 실행 절차다.
