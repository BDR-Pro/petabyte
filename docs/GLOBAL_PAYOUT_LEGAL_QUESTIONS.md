# Global Payout — Open Legal, Regulatory & Tax Questions

**Status:** OPEN. None of these are resolved. **Verified/compiled:** 2026-08-05.

This document exists because the engineering for global payouts is *ahead* of the legal
and compliance groundwork, and pretending otherwise would be dishonest and dangerous.
The code fails closed (no compliance decision → no payout; sanctioned country →
blocked; stablecoin → requires consent + screening) specifically so that these
unresolved questions cannot be silently bypassed by shipping code.

**These are questions for qualified counsel and a compliance officer, not something an
engineer should answer by writing a config file.** Nothing here is legal advice. Do not
treat a green test suite as clearance to move real money internationally.

Each item lists: the question, why it blocks a real launch, and what the code does *in
the meantime* so we stay safe rather than guessing.

---

## 1. Money transmission / payment institution licensing

- **Q:** By aggregating buyer funds and disbursing to sellers, is Petabyte acting as a
  money transmitter (US, state-by-state MTLs), an Electronic Money Institution / Payment
  Institution (EU/UK), or is that liability fully borne by Stripe as the regulated
  entity of record? Does the answer change once we add a *second* rail (Global Payouts,
  stablecoin) that isn't Stripe Connect?
- **Why it blocks launch:** Operating unlicensed money transmission is a criminal
  exposure, not a fine. The whole "marketplace on top of Stripe Connect" model exists to
  keep this liability with Stripe; adding non-Stripe rails may break that shield.
- **Interim posture in code:** Only `STRIPE_CONNECT` is implemented, where Stripe is the
  regulated payout entity. Every other rail returns `NOT_IMPLEMENTED` and refuses to
  send. We do not custody or transmit outside Stripe today.

## 2. Sanctions / OFAC / EU / UK / UN screening

- **Q:** Which screening provider and what matching thresholds satisfy OFAC (and EU/UK/UN
  equivalents) for *both* buyers and sellers? How often must sellers be re-screened? What
  is the recordkeeping and blocked-transaction reporting obligation?
- **Why it blocks launch:** A single payout to a sanctioned party is a serious violation.
  Our hardcoded country block list is a floor, not compliance.
- **Interim posture in code:** Six countries are hard-blocked
  (`CU, IR, KP, SY, RU, BY`). Routing **fails closed**: without an `APPROVED`, unexpired
  sanctions `ComplianceDecision`, no payout is selected. `SANCTIONS_SCREEN_PROVIDER` must
  be set before live payouts, and with none set the legacy payout path also fails closed.
  **Open:** the block list must be continuously maintained against real designations, and
  a real screening integration must replace the manual list.

## 3. KYC / KYB and Customer Due Diligence

- **Q:** What identity (KYC) and business (KYB) verification is required per seller
  country and per recipient type (individual vs. company) before first payout? What
  enhanced due diligence applies above certain volumes? Who is the responsible party —
  Stripe's Connect onboarding, or must Petabyte collect and retain more?
- **Why it blocks launch:** Under-verifying enables fraud/laundering; over-collecting
  creates data-protection liability (see §7).
- **Interim posture in code:** Connect Express carries Stripe's onboarding/KYC.
  `kyc_required` is flagged per dataset row; `payout_ready` gates transfers on a
  completed connected account. No payout runs to an unverified account.

## 4. Tax reporting & information returns (payer-side)

- **Q:** What are Petabyte's information-reporting duties as the payer? US: 1099-K /
  1099-NEC thresholds, and 1042-S / 1042 for payments to non-US persons. EU: DAC7
  reporting for digital-platform sellers. Which apply, at what thresholds, and by when?
- **Why it blocks launch:** Missed information returns carry per-payee penalties that
  scale with seller count. DAC7 in particular targets exactly our model (a platform
  paying sellers).
- **Interim posture in code:** `tax_form_required` is flagged per country row; the
  `PayoutObligation` model carries a `withholding_minor` field and a `pricing_snapshot`
  so the reporting basis is captured at settlement time. **Open:** no actual form
  generation, threshold tracking, or filing exists yet.

## 5. Withholding tax on cross-border payments

- **Q:** For payments to non-US sellers, when is US withholding (typically 30%, reduced
  by treaty) required? Do we need W-8BEN/W-8BEN-E collection and treaty-rate logic? What
  are the equivalent obligations in other platform jurisdictions?
- **Why it blocks launch:** Failure to withhold when required makes the *platform* liable
  for the tax that should have been withheld.
- **Interim posture in code:** `withholding_minor` exists on the obligation so a computed
  withholding can be recorded and *reduces the net paid* without corrupting the gross
  or the ledger. It is currently always 0 because the treaty/withholding logic is not
  built. No payout claims to have withheld anything it hasn't.

## 6. Stablecoin / crypto-specific regulation

- **Q:** In which seller jurisdictions is receiving USDC legal, and what licensing (VASP
  registration, MiCA in the EU, state-level in the US) does *Petabyte* need to offer a
  stablecoin payout? What travel-rule (FATF) obligations attach? How is on-chain
  sanctions screening of destination wallets performed and recorded? What is the tax
  characterization of a stablecoin payout to the seller?
- **Why it blocks launch:** Crypto payout is a separate, heavier regulatory regime than
  bank payout; getting it wrong is a licensing violation *and* a sanctions risk (mixers,
  screened wallets).
- **Interim posture in code:** Stablecoin rails are `not_implemented` and refuse to send.
  Routing will **never auto-select** a stablecoin rail: it requires (a) explicit,
  timestamped seller consent (`PayoutMethodRail.consented_at`), (b) a `verified` method,
  and (c) an implemented rail — none of which exist today. So the answer to "can a seller
  accidentally be paid in crypto?" is structurally *no*.

## 7. Data protection & cross-border data transfer

- **Q:** What GDPR/UK-GDPR/CCPA obligations attach to collecting sellers' identity,
  banking, and wallet data across 100+ countries? What are the lawful bases, retention
  limits, and cross-border transfer mechanisms (SCCs, adequacy) for sending that data to
  Stripe/Circle/screening providers?
- **Why it blocks launch:** Fines scale with revenue; the data we need for payouts is
  exactly the sensitive category regulators scrutinize.
- **Interim posture in code:** We minimize what we store — destinations are masked
  (`masked_destination`), and KYC/banking detail lives with Stripe rather than in our DB.
  **Open:** a formal data-processing inventory, DPA coverage per provider, and retention
  policy are not documented.

## 8. FX, currency conversion & settlement disclosure

- **Q:** When a buyer pays in currency A and a seller settles in currency B, who bears
  FX risk, what rate and markup apply, and what must be *disclosed* to each party (and
  when)? Are there jurisdictions requiring specific FX disclosure to the seller?
- **Why it blocks launch:** Undisclosed FX markups are a consumer-protection and
  transparency issue; unmanaged FX exposure is a financial risk.
- **Interim posture in code:** `PayoutBatch` carries `source_currency`,
  `destination_currency`, `fx_rate`, and `provider_fee_minor` so a conversion is recorded
  explicitly and reconcilable. Today source == destination (no conversion performed), and
  `fx_rate` is null. No hidden conversion happens.

## 9. Consumer protection, chargebacks & refund liability

- **Q:** Across buyer jurisdictions, what refund/chargeback rights apply, and who eats a
  chargeback that lands *after* a seller has been paid out? Do we need a rolling reserve
  or clawback right against sellers, and is that enforceable per country?
- **Why it blocks launch:** "Pay the seller, then the buyer charges back" is the classic
  marketplace loss. Without a defined liability waterfall it lands on the platform.
- **Interim posture in code:** Payouts are separate charges & transfers with a
  **manual-capture** flow and a risk-hold window (`risk_hold_until`,
  `PAYOUT_COOLING_OFF_H`); obligations start `accrued` and only become `available` after
  the hold. Reversals are compensating ledger entries, never mutations. **Open:** no
  seller clawback / rolling-reserve mechanism is implemented.

## 10. Contractual — terms of service & seller agreement

- **Q:** Do our seller terms actually grant the rights the payout system assumes: consent
  to screening and re-screening, the right to withhold/delay/reverse a payout, the right
  to choose or restrict a rail per country, and the right to require consent before
  stablecoin? Are those terms enforceable in each seller jurisdiction?
- **Why it blocks launch:** The code enforces these behaviors; the *legal right* to
  enforce them must exist in the agreement, per jurisdiction.
- **Interim posture in code:** The engine assumes these rights (consent gate, compliance
  hold, rail choice with stored explanation). **Open:** the seller agreement must be
  drafted/reviewed to actually confer them.

## 11. Unclaimed property / escheatment

- **Q:** If a seller never onboards a payout method or can't be paid (e.g. a
  `MANUAL_REVIEW` obligation that's never resolved), what are our escheatment /
  unclaimed-property obligations, and after what dormancy period?
- **Why it blocks launch:** Held-but-unpaid balances are regulated unclaimed property in
  many jurisdictions; ignoring them is a compliance gap that compounds over time.
- **Interim posture in code:** Obligations are durable and provider-neutral — an unpaid
  balance is never silently dropped; it stays as an `available`/`accrued`/`failed`
  obligation with a full audit trail. **Open:** no dormancy tracking or escheatment
  workflow exists.

---

## How the code protects us until these are answered

| Guarantee | Mechanism |
|---|---|
| No payout without compliance sign-off | `compliance_ok()` requires an `APPROVED`, unexpired sanctions `ComplianceDecision`; **fail-closed** |
| No payout to a sanctioned country | `is_sanctioned()` hard block in `select_rail`, before any rail is considered |
| No accidental crypto payout | Stablecoin rails `not_implemented` **and** consent-gated **and** require a verified method |
| No fake success from a missing rail | Unimplemented adapters return `NOT_IMPLEMENTED` and raise on `send_payout` |
| No double payment | One obligation → at most one batch (claim guard + FK); direct transfer marks the obligation `paid` |
| Honest coverage number | Strict ACTIVE definition; CI coverage check exits non-zero until real reach exists |
| Reporting basis captured | `withholding_minor`, `pricing_snapshot`, batch FX/fee fields recorded at settlement |

**Bottom line:** the platform is engineered to *not move money it isn't cleared to
move*. Turning any of the above from "interim posture" into "supported" is a
legal/compliance decision first and a code change second — in that order.
