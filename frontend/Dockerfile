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
ARG NEXT_PUBLIC_DOCSURI_RESEARCH_AGENT_ENABLED=
ENV NEXT_PUBLIC_DOCSURI_RESEARCH_AGENT_ENABLED=$NEXT_PUBLIC_DOCSURI_RESEARCH_AGENT_ENABLED
ARG NEXT_PUBLIC_ORCID_LOGIN_ENABLED=
ENV NEXT_PUBLIC_ORCID_LOGIN_ENABLED=$NEXT_PUBLIC_ORCID_LOGIN_ENABLED
RUN pnpm build

FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
