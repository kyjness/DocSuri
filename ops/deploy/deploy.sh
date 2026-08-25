#!/usr/bin/env bash
# 배포 — 소스를 박스로 밀고 거기서 빌드해 올린다(로드맵 ⑪).
#
#   ./ops/deploy/deploy.sh <고정IP> [개인키]
#
# **박스에서 빌드한다.** 이미지 레지스트리를 두지 않기 위해서다 — 데모 배포에 ECR/Docker Hub
# 계정과 그 자격증명을 하나 더 만드는 값이 없다. 대가는 첫 배포가 느린 것(프론트 빌드가
# 2 vCPU에서 몇 분)이고, 그 뒤로는 레이어 캐시가 받는다.
#
# **시크릿은 `.env.prod` 하나로만 간다.** 이 스크립트는 그것을 만들지 않는다 —
# `README.md`를 보고 손으로 채운 뒤 여기로 넘긴다. 인자나 환경변수로 받으면 셸 히스토리와
# 프로세스 목록에 남는다.
set -euo pipefail

HOST="${1:?사용법: deploy.sh <고정IP> [개인키]}"
KEY="${2:-$HOME/.ssh/docsuri_deploy}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
REMOTE="/opt/docsuri"
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "ec2-user@$HOST")

[ -f "$REPO/ops/deploy/.env.prod" ] || {
  echo "ops/deploy/.env.prod 가 없다 — README의 '시크릿' 절을 보고 만든다." >&2
  exit 1
}

echo "==> 소스 전송"
# `--delete`는 쓰지 않는다: 박스의 `.env.prod`와 볼륨 데이터를 지울 수 있다.
# 제외 목록은 **박스에서 쓸 일이 없는 것**이다 — 로컬 코퍼스(24 GB)가 딸려 가면 디스크가 찬다.
rsync -az --info=stats1 \
  --exclude '.git' --exclude 'node_modules' --exclude '.next' \
  --exclude '__pycache__' --exclude '.venv' --exclude 'reports' \
  --exclude 'aidlc-docs' --exclude '.cache' \
  -e "ssh -i $KEY -o StrictHostKeyChecking=accept-new" \
  "$REPO/" "ec2-user@$HOST:$REMOTE/"

echo "==> 빌드·기동"
"${SSH[@]}" "cd $REMOTE/ops/deploy && docker compose -f compose.prod.yml --env-file .env.prod up -d --build"

echo "==> 마이그레이션 확인"
# 백엔드가 **부팅 때 스스로 적용한다**(`backend/app.py:STARTUP_MIGRATION_DIRS`). 여기서는
# 적용이 아니라 **남은 것이 없는지 확인만** 한다 — 적용을 두 번 시도하면 같은 디렉터리를
# 두 경로가 밟게 되고, 앞의 `up -d`가 성공했다는 사실이 마이그레이션까지 끝났다는 뜻은
# 아니라는 것을 여기서 확인해야 한다. `--check`는 남은 것이 있으면 비-0으로 끝난다.
"${SSH[@]}" "cd $REMOTE/ops/deploy && docker compose -f compose.prod.yml --env-file .env.prod exec -T backend python -m backend.migrations --check"

echo "==> 상태"
"${SSH[@]}" "cd $REMOTE/ops/deploy && docker compose -f compose.prod.yml ps"

cat <<'DONE'

배포가 끝났다고 초록을 믿지 않는다. ⑪의 선행 점검을 돈다:
  1) 색인 편수      curl -s localhost:9200/_cat/indices?v   (박스에서)
  2) 전문이 뜨는가   논문 하나를 열어 본문이 보이는지 — 백지면 S3 배선이다
  3) 에이전트 한 턴  질문 하나를 던져 근거표까지 나오는지
  4) Novelty가 안 보이는가 (빌드 인자로 막았다 — 보이면 재빌드가 필요하다)
DONE
