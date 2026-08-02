# Referral system

Double-sided referrals paying **platform credit** (not cash) to both the referrer and the
new user. Marketed as real money because it is real spendable value — but it is credit,
not a cash-out path.

## How it works
1. Every user has a share code + link (`/?ref=CODE`), shown in the dashboard "Refer & earn"
   card with a copy button and a live earned/pending tracker (`GET /referral`).
2. A visitor arriving with `?ref=CODE` on ANY page has it stored in a **90-day cookie**
   (set server-side in middleware, so it works no matter which page the link points at, and
   survives leaving and coming back — people rarely sign up on the first click). First-touch
   wins: an existing cookie is never overwritten, so the original referrer keeps the credit.
   On signup, `/register_user` reads the code from the body or falls back to the cookie, links
   the new user, then clears the cookie (so a later signup on a shared machine isn't mis-credited).
   No reward yet.
3. **Qualifying event:** when the referred user completes their FIRST paid rental, settlement
   calls `maybe_reward_referral()` (post-commit, isolated) which grants `REFERRAL_REWARD_USD`
   of credit to BOTH sides.

## Why it's safe for a solo founder
- **Credit, not cash.** Rewards land in `balance` (spend-only). Only `earnings` can be
  withdrawn, so referral credit can never be cashed out — structurally, not by a flag.
- **Trigger is a paid rental, not a signup** — you don't pay for accounts, you pay for proven
  economic activity (the Mercury principle).
- **Self-referral guard:** same signup fingerprint (IP) on both accounts => no reward.
- **Monthly cap** (`REFERRAL_MONTHLY_CAP`) per referrer — anti-farming.
- **Ledger-clean:** credit is funded from `external:promo` (a real marketing expense), so the
  double-entry books stay balanced — no minted money.
- **Never touches escrow/settlement:** the reward is a separate post-commit step; a referral
  error can't affect the rental that completed.

## Env
- `REFERRAL_REWARD_USD` (default 20) — credit per side.
- `REFERRAL_MONTHLY_CAP` (default 25) — max rewarded referrals/referrer/month.
- `PUBLIC_BASE_URL` — for building share links.

## Deferred / worth adding later
- Device fingerprint (not just IP) for stronger self-referral detection.
- Credit expiry (e.g. 90 days) to cap outstanding liability.
- Manual-review flag above a monthly $ threshold per referrer.
- Admin panel controls for the amount + a referrals leaderboard.
