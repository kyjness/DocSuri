# U5 Frontend — Next.js standalone SSR image (deploy unit ④, P-SC1).
# Stateless server (session lives in the httpOnly cookie). Concrete hosting
# topology / runtime config is Infrastructure Design.
FROM node:22-alpine AS base
RUN corepack enable

FROM base AS deps
WORKDIR /app
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile || pnpm install

FROM base AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Real-API mode: NEXT_PUBLIC_* is inlined into the client bundle at build time, so the
# production image must bake it here (runtime env can't switch it). Default on; the client
# then routes through the same-origin BFF instead of MockTransport. Override to "" for a
# mock-only preview image.
ARG NEXT_PUBLIC_DOCSURI_REAL_API=1
ENV NEXT_PUBLIC_DOCSURI_REAL_API=$NEXT_PUBLIC_DOCSURI_REAL_API
# Research(U11 evidence) 백엔드는 배포에서 항상 켜져 있는데(EVIDENCE_AGENT_ENABLED=true),
# 이 클라이언트 번들 가드가 비어 있으면 real API 모드에서 Research 전송 자체가 막히고
# 모드 선택 버튼도 비활성으로 뜬다(PR #338 리뷰 Blocking #4).
#
# **이름이 코드와 갈려 있었다** — 여기는 `..._RESEARCH_AGENT_ENABLED`를 세웠는데 읽는 쪽
# (`apiClient.ts`·`AgentChatScreen.tsx`)은 `..._EVIDENCE_AGENT_ENABLED`다. 즉 이 줄은
# 아무 일도 안 했고, real API 이미지는 **Research가 비활성인 채로** 빌드됐다. 빌드는
# 성공하고 테스트는 목 전송이라 초록이며, 화면을 열기 전까지 아무 데도 안 보인다.
ARG NEXT_PUBLIC_DOCSURI_EVIDENCE_AGENT_ENABLED=1
ENV NEXT_PUBLIC_DOCSURI_EVIDENCE_AGENT_ENABLED=$NEXT_PUBLIC_DOCSURI_EVIDENCE_AGENT_ENABLED
# Novelty 모드는 한시 배포에서 안 내보낸다(로드맵 ⑪). 기본을 빈 값으로 둔다 — `NEXT_PUBLIC_*`는
# 빌드 시점에 박히므로 **런타임 env로는 못 고친다.** 켜려면 이 인자를 1로 주고 다시 빌드한다.
ARG NEXT_PUBLIC_DOCSURI_NOVELTY_ENABLED=
ENV NEXT_PUBLIC_DOCSURI_NOVELTY_ENABLED=$NEXT_PUBLIC_DOCSURI_NOVELTY_ENABLED
# ORCID OIDC login is live in prod (backend enabled 2026-07-06). Default the client-bundle flag ON
# so the "ORCID로 계속하기" button ships on every build; override to "" only for a mock preview.
ARG NEXT_PUBLIC_ORCID_LOGIN_ENABLED=1
ENV NEXT_PUBLIC_ORCID_LOGIN_ENABLED=$NEXT_PUBLIC_ORCID_LOGIN_ENABLED
# reCAPTCHA 사이트 키 — 배포마다 다른 값이라 인자로 받는다. **빈 값이 기본이고 그것이
# 곧 off다**(`LoginForm.tsx`가 빈 값을 undefined로 접어 스크립트를 안 부른다). 백엔드도
# `RECAPTCHA_SECRET_KEY`가 없으면 검증을 건너뛰므로 둘이 함께 꺼지고 함께 켜진다.
# 여기 없던 동안에는 **어떤 이미지에서도 켤 수 없었다** — 값을 넣을 자리가 없었다.
# 가입 없이 둘러보기. **기본은 빈 값(off)** — 가입 장벽을 없애는 공개 표면이라 실서비스
# 이미지에 켜진 채 나가면 안 된다. 백엔드에도 같은 이름의 스위치가 따로 있고 꺼져 있으면
# 404다: 버튼만 숨기고 엔드포인트가 열려 있으면 숨긴 것이 아니다.
ARG NEXT_PUBLIC_DOCSURI_DEMO_LOGIN_ENABLED=
ENV NEXT_PUBLIC_DOCSURI_DEMO_LOGIN_ENABLED=$NEXT_PUBLIC_DOCSURI_DEMO_LOGIN_ENABLED
ARG NEXT_PUBLIC_RECAPTCHA_SITE_KEY=
ENV NEXT_PUBLIC_RECAPTCHA_SITE_KEY=$NEXT_PUBLIC_RECAPTCHA_SITE_KEY
RUN pnpm build

FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
