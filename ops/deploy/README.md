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
PUBLIC_APP_URL=https://docsuri.shop

AWS_DEFAULT_REGION=ap-northeast-2
AWS_ACCESS_KEY_ID=<terraform output>
AWS_SECRET_ACCESS_KEY=<terraform output>
DOCSURI_DOCMODEL_BUCKET=<terraform output s3_bucket>
DOCSURI_SUMMARY_BUCKET=<terraform output s3_bucket>

# 코퍼스가 얇으므로 켠다. 조회는 외부 API 호출뿐이라 파싱 스택이 없어도 돈다.
DOCSURI_EVIDENCE_LIVE_LOOKUP_ENABLED=true
```

호스트 이름(`postgres`·`redis`·`opensearch`)은 compose 서비스 이름이다. `localhost`를 쓰면
컨테이너 자기 자신을 가리켜 전부 연결 거부가 된다.

**`AWS_PROFILE`을 넣지 않는다.** 넣으면 boto3가 없는 프로필을 찾다 죽는다 — 박스에는
`~/.aws`가 없다.

## 4. 코퍼스 이관

파싱 스택을 안 올리므로 로컬에서 만든 것을 옮긴다.

1. **자산·doc-model** → S3 버킷. 로컬은 `~/data/docsuri-deploy/s3`를 s3proxy가 서빙하고
   있으므로, 그 트리를 그대로 올린다.
   ```bash
   aws s3 sync ~/data/docsuri-deploy/s3/ s3://<s3_bucket>/ --size-only
   ```
2. **Postgres** → 덤프·복원.
3. **OpenSearch 색인** → 스냅샷 또는 재색인. 재색인은 임베딩 토큰을 다시 쓰므로
   **Bedrock 일일 한도(약 800만/일)를 먼저 확인한다** — 3,248편이면 하루에 안 들어간다.

## 5. 배포

```bash
./ops/deploy/deploy.sh <static_ip>
```

첫 배포는 프론트 빌드 때문에 2 vCPU에서 몇 분 걸린다. 그 뒤로는 레이어 캐시가 받는다.

## 6. 선행 점검 — 초록을 믿지 않는다

⑧-2 1차 실행에서 **의존성 둘이 죽은 채로 5시간이 지나갔다.** 셋 다 실패가 산출물이 아니라
카운터로만 드러난다. 배포 직후에 손으로 확인한다.

| # | 점검 | 안 하면 |
|---|---|---|
| 1 | `curl -s localhost:9200/_cat/indices?v` 편수가 맞는가 | 검색이 조용히 적게 나오고 "논문이 드물다"로 읽힌다 |
| 2 | 논문 하나를 열어 **전문이 뜨는가** | 백지면 S3 배선이다 — 파서 문제로 오인하기 쉽다 |
| 3 | 질문 하나를 던져 **근거표까지** 나오는가 | 기권만 나오면 Bedrock 자격증명·리전·토큰 한도다 |
| 4 | 모드 선택에 **Novelty가 없는가** | 빌드 인자로 막았다 — 보이면 재빌드가 필요하다(런타임 env로는 안 고쳐진다) |

## 되돌리기·정리

```bash
cd ops/deploy/terraform && terraform destroy
```

인스턴스·고정 IP·S3 버킷·IAM 사용자가 함께 지워진다. **버킷에 객체가 남아 있으면 destroy가
실패한다** — 먼저 비운다(`aws s3 rm s3://<bucket> --recursive`). 크레딧이 소진되면 이것이
"다 쓰면 종료"의 실행 절차다.
