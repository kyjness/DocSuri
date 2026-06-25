/* Curated from shared/dtos/mypage.schema.json (SSOT). Producer: U10 My Page. Consumer: U5.
 * MOCK-ONLY contract: subscribe/cancel only flip persisted state — no real PG/billing sits
 * behind this. SEC-9: owner userId is never exposed. Run `pnpm gen:types` to refresh the raw
 * schema dump under types/.schema-raw/ for drift review. */

export type SubscriptionPlan = 'FREE' | 'PREMIUM';
export type SubscriptionStatusValue = 'NONE' | 'ACTIVE' | 'CANCELED';

/** Current subscription snapshot. startedAt/currentPeriodEnd/canceledAt are absent when never
 * subscribed (status=NONE). Cancellation retains the PREMIUM benefit through
 * currentPeriodEnd — no immediate cutoff. */
export interface SubscriptionDTO {
  plan: SubscriptionPlan;
  status: SubscriptionStatusValue;
  startedAt?: string;
  currentPeriodEnd?: string;
  canceledAt?: string;
}
