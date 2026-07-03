/**
 * Next.js config — U5 Frontend (SSR phone-first, deploy unit ④).
 * Security headers / CSP are applied in middleware.ts (LC-8, SEC-4).
 * @type {import('next').NextConfig}
 */
const nextConfig = {
  reactStrictMode: true,
  // Standalone output keeps the SSR server stateless and deployable as an
  // independent unit (P-SC1). Concrete hosting topology is Infra-stage.
  output: 'standalone',
  // Hide the dev route/build indicator (the bottom-left overlay badge). On the pinned Next (15.5.x)
  // the granular `appIsrStatus`/`buildActivity` keys are deprecated; the supported way to disable it
  // is the boolean shorthand. Dev-only overlay, no prod effect.
  devIndicators: false,
};

export default nextConfig;
