#!/usr/bin/env python3
"""Generate the human-facing GitHub configuration docs from the manifest, so the docs can
never drift from the source of truth:

  * docs/GITHUB_CONFIGURATION_REFERENCE.md — the full reference table (Name, GitHub type,
    Required, Scope, Default, Example, Used by, Validation, Production notes).
  * docs/GITHUB_MANUAL_SETUP_CHECKLIST.md — a copy-paste checklist the user works through
    to create every Variable and Secret in GitHub, with where each value comes from, how
    to validate it, and whether a restart is needed. No real secret values ever appear.

Run:
    python scripts/generate_config_docs.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import yaml
except ImportError:  # pragma: no cover
    print("::error::PyYAML is required (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)

from check_configuration_drift import scan_code_vars  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "config", "github_configuration_manifest.yaml")
REF_OUT = os.path.join(ROOT, "docs", "GITHUB_CONFIGURATION_REFERENCE.md")
CHECKLIST_OUT = os.path.join(ROOT, "docs", "GITHUB_MANUAL_SETUP_CHECKLIST.md")

# Where each value comes from / how to obtain it. Keyed by exact name; a couple of prefix
# fallbacks handle families. NEVER put a real secret here — only instructions.
SOURCE_HINTS = {
    "SECRET_KEY": "Generate once: `openssl rand -hex 32`. Rotating it logs everyone out.",
    "SERVER_PRIVATE_KEY": "Generate a Fernet key: "
        "`python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())'`. "
        "Rotating it makes existing encrypted API keys undecryptable — migrate the current value.",
    "DATABASE_URL": "postgresql+psycopg2://USER:PASS@HOST:5432/DB. One-time migration: read the "
        "current value from /etc/lumaris/lumaris.env on the server so sessions/data survive.",
    "PAYMENT_WEBHOOK_SECRET": "Stripe deposits webhook signing secret (whsec_…).",
    "STRIPE_SECRET_KEY": "Stripe Dashboard → Developers → API keys. Use sk_test_… (test); only "
        "sk_live_… when deliberately going live.",
    "STRIPE_PUBLISHABLE_KEY": "Stripe Dashboard → API keys (pk_test_… / pk_live_…).",
    "STRIPE_WEBHOOK_SECRET": "Stripe Dashboard → Developers → Webhooks → signing secret (whsec_…), "
        "or `stripe listen`.",
    "STRIPE_API_KEY": "Legacy deposits key — same source as STRIPE_SECRET_KEY.",
    "GOOGLE_CLIENT_ID": "Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 client.",
    "GOOGLE_CLIENT_SECRET": "Google Cloud Console → the same OAuth client's secret.",
    "MAILGUN_API_KEY": "Mailgun → Settings → API Keys (a Sending API key). Also powers the newsletter.",
    "CAL_WEBHOOK_SECRET": "Cal.com → the demo booking webhook's signing secret.",
    "GATEWAY_TOKEN": "Generate: `openssl rand -hex 16` (VM gateway route resolution).",
    "SENTRY_DSN": "Sentry → project → Settings → Client Keys (DSN).",
    "AWS_ACCESS_KEY_ID": "AWS IAM user with S3 backup access.",
    "AWS_SECRET_ACCESS_KEY": "AWS IAM user with S3 backup access (the matching secret).",
    "CIRCLE_API_KEY": "Circle dashboard (only if using USDC payouts).",
    "CIRCLE_WALLET_ID": "Circle dashboard (only if using USDC payouts).",
    "TREMENDOUS_API_KEY": "Tremendous dashboard (only if using Tremendous payouts).",
    "TREMENDOUS_FUNDING_ID": "Tremendous dashboard (funding source id).",
    "TREMENDOUS_PRODUCT_ID": "Tremendous dashboard (product id).",
    "NICEHASH_API_KEY": "NiceHash → API keys (only if using idle-mining fallback pricing).",
    "NICEHASH_API_SECRET": "NiceHash → API keys (the matching secret).",
    "NICEHASH_ORG_ID": "NiceHash → organization id.",
    "SENDGRID_API_KEY": "SendGrid (only if EMAIL_PROVIDER=sendgrid).",
    "POSTMARK_TOKEN": "Postmark (only if EMAIL_PROVIDER=postmark).",
    "MAILCHIMP_API_KEY": "Mailchimp → Account → Extras → API keys (only if NEWSLETTER_PROVIDER=mailchimp).",
    "TEE_TRUSTED_ROOT": "Base64 vendor attestation root public key (confidential computing only).",
    "DEPLOY_SSH_KEY": "The PRIVATE SSH key authorized on the server (e.g. id_ed25519). Never commit it.",
    "DROPLET_HOST": "The API server's public IP or DNS name.",
    "DROPLET_USER": "The deploy SSH user on the server (e.g. root or a deploy user).",
    "PETABYTE_API_KEY": "Minted per GPU node: POST /create_api_key (set on the node, not the platform).",
    "PETABYTE_API_JWT": "The seller's login JWT (spec owner) — used once during node attestation.",
}


def _used_by(name: str, meta: dict, code_map: dict) -> str:
    files = code_map.get(name)
    if not files and meta.get("aka"):
        files = code_map.get(meta["aka"])
    if files:
        return ", ".join(sorted(f.replace("lumaris_", "") for f in files))
    scope = meta.get("scope", [])
    if "deployment" in scope:
        return "GitHub Actions deploy"
    if "gpu" in scope:
        return "GPU node agent"
    return "—"


def _validation(meta: dict) -> str:
    bits = []
    if meta.get("format"):
        bits.append(f"format: {meta['format']}")
    if meta.get("allowed"):
        bits.append("one of: " + " / ".join(meta["allowed"]))
    return "; ".join(bits) or "—"


def _default_cell(meta: dict, is_secret: bool) -> str:
    if is_secret:
        return "**NO DEFAULT** (secret)"
    d = meta.get("default")
    if d is None or d == "":
        return "*(empty)*"
    return f"`{d}`"


def _example(name: str, meta: dict, is_secret: bool) -> str:
    if is_secret:
        return "`<set in GitHub Secrets>`"
    d = meta.get("default")
    if d not in (None, ""):
        return f"`{d}`"
    if meta.get("allowed"):
        return f"`{meta['allowed'][0]}`"
    fmt = meta.get("format", "")
    return {"url": "`https://…`", "hostname": "`petabyte.market`", "int": "`60`",
            "float": "`0.10`", "bool": "`false`", "email": "`info@petabyte.market`"}.get(
                fmt.replace("_or_empty", ""), "`…`")


def _md_escape(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ")


def build_reference(manifest: dict, code_map: dict) -> str:
    lines = [
        "# GitHub configuration reference",
        "",
        "> **Generated** by `scripts/generate_config_docs.py` from "
        "`config/github_configuration_manifest.yaml`. Do not hand-edit — re-run the "
        "generator. The manifest is the single source of truth.",
        "",
        "GitHub is the source of truth for deployment configuration. Non-sensitive values "
        "are **GitHub Variables**; credentials/keys/tokens/passwords are **GitHub Secrets**. "
        "At deploy time GitHub Actions resolves these and generates the server env file — "
        "nothing long-lived is hand-maintained on the server.",
        "",
        "Set them under **Settings → Secrets and variables → Actions** (repository level), "
        "or per **Environment** (test / staging / production) for environment-specific "
        "values and protection rules.",
        "",
        "Scope legend: **platform** = API server · **gpu** = seller GPU node agent · "
        "**deployment** = GitHub Actions → server (never written into the server runtime env).",
        "",
    ]

    def section(title, items, is_secret):
        lines.append(f"## {title} ({len(items)})")
        lines.append("")
        lines.append("| Name | Required | Scope | Default | Example | Used by | Validation | Production notes |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for name in sorted(items):
            meta = items[name]
            aka = f"<br>`aka {meta['aka']}`" if meta.get("aka") else ""
            req = "**yes**" if meta.get("required") else "no"
            scope = "/".join(meta.get("scope", []))
            lines.append(
                f"| `{name}`{aka} | {req} | {scope} | {_default_cell(meta, is_secret)} "
                f"| {_example(name, meta, is_secret)} | {_md_escape(_used_by(name, meta, code_map))} "
                f"| {_md_escape(_validation(meta))} "
                f"| {_md_escape(meta.get('production_notes') or meta.get('description') or '—')} |")
        lines.append("")

    section("Variables (non-sensitive)", manifest.get("variables", {}), False)
    section("Secrets (credentials — never printed, no defaults)", manifest.get("secrets", {}), True)
    lines.append("---")
    lines.append("")
    lines.append("**Safety defaults (never permissive):** live payments, auth-bypass stubs, "
                 "disabled webhook verification, public DB/Redis, wildcard CORS, debug in prod, "
                 "the fake payment gateway, unsigned seller comms, disabled TLS, unbounded job "
                 "runtime, and unbounded upload size all default to the SAFE value. Production "
                 "validation (`scripts/validate_github_configuration.py --env-name production`) "
                 "refuses to deploy if any of them is left permissive.")
    lines.append("")
    lines.append("## Environments")
    lines.append("")
    lines.append("Use GitHub **Environments** to hold environment-specific config and protection "
                 "rules. The deploy validates against `${{ vars.ENVIRONMENT || 'development' }}`:")
    lines.append("")
    lines.append("- **test / staging** — production-grade infra on TEST money: `STRIPE_MODE=test`, "
                 "`PAYMENTS_LIVE_ENABLED=false`, test keys only. A live key here is rejected.")
    lines.append("- **production** — live money: `ENVIRONMENT=production`, `STRIPE_MODE=live`, "
                 "`PAYMENTS_LIVE_ENABLED=true`, `STRIPE_ALLOW_LIVE=true`, `STRIPE_GATEWAY=real`, "
                 "live keys + webhook secret, all stubs off, https URLs. Add environment "
                 "protection (required reviewers) so a live deploy is a deliberate act.")
    lines.append("")
    lines.append("## Rollout & emergency overrides")
    lines.append("")
    lines.append("- **Rollout gate.** The deploy writes the server env from GitHub config only "
                 "when the repository Variable `DEPLOY_CONFIG_FROM_GITHUB=true`. Until then the "
                 "preflight is advisory and deploys stay code-only (the server env is untouched), "
                 "so you can enter all Secrets first. Before flipping the gate, do the one-time "
                 "migration of `SECRET_KEY`, `SERVER_PRIVATE_KEY`, and `DATABASE_URL` — copy the "
                 "CURRENT values from `/etc/lumaris/lumaris.env` into GitHub Secrets so live "
                 "sessions, encrypted API keys, and the database keep working.")
    lines.append("- **Emergency change, right now.** You may edit `/etc/lumaris/lumaris.env` on "
                 "the server and `sudo systemctl restart lumaris-api lumaris-reaper`. This is "
                 "**temporary**: with the gate on, the next deploy regenerates the file from "
                 "GitHub and your hand-edit is lost. Make it permanent by setting the value in "
                 "GitHub, then deploy.")
    lines.append("- **Pause GitHub-managed env.** Set `DEPLOY_CONFIG_FROM_GITHUB=false` (or unset "
                 "it) to revert to code-only deploys that never touch the server env.")
    lines.append("")
    return "\n".join(lines)


def build_checklist(manifest: dict) -> str:
    variables = manifest.get("variables", {})
    secrets = manifest.get("secrets", {})

    def scoped(items, scope):
        return {k: v for k, v in items.items() if scope in v.get("scope", [])}

    lines = [
        "# GitHub manual setup checklist",
        "",
        "> **Generated** by `scripts/generate_config_docs.py`. Work top to bottom. Create "
        "each **Variable** and **Secret** in GitHub under **Settings → Secrets and variables "
        "→ Actions** (or per **Environment**). This list is complete — you should not need to "
        "search the repository.",
        "",
        "Format below: Variables are shown as `NAME=default` (the value the app uses if you "
        "don't override it). Secrets are shown as `NAME=<what to put>` — **never** commit or "
        "paste a real secret into a file; only enter it in the GitHub Secrets UI.",
        "",
        "After entering everything, the `configuration-preflight` CI job validates it and "
        "**fails the deploy** if anything required is missing or unsafe. A deploy applies the "
        "config by regenerating the server env and restarting the services (so every change "
        "takes effect on the next deploy).",
        "",
        "Legend: 🔴 required · ⚪ optional (default is safe).",
        "",
    ]

    def var_block(title, items, blurb=""):
        lines.append(f"### {title}")
        if blurb:
            lines.append("")
            lines.append(blurb)
        lines.append("")
        lines.append("```ini")
        for name in sorted(items):
            meta = items[name]
            mark = "REQUIRED" if meta.get("required") else "optional"
            d = meta.get("default")
            d = "" if d in (None,) else d
            lines.append(f"{name}={d}   # {mark}: {_md_escape(meta.get('description') or '')}")
        lines.append("```")
        lines.append("")

    def secret_block(title, items, blurb=""):
        lines.append(f"### {title}")
        if blurb:
            lines.append("")
            lines.append(blurb)
        lines.append("")
        for name in sorted(items):
            meta = items[name]
            mark = "🔴 required" if meta.get("required") else "⚪ optional"
            hint = SOURCE_HINTS.get(name, meta.get("description") or "See the reference doc.")
            lines.append(f"- **`{name}`** — {mark}. {_md_escape(hint)}")
        lines.append("")

    # --- Platform server ---
    lines.append("## 1. Platform (API server)")
    lines.append("")
    var_block("Variables — platform",
              scoped(variables, "platform"),
              "Non-sensitive server config. Override any line in GitHub Variables; leave the "
              "rest and the shown default is used.")
    secret_block("Secrets — platform",
                 scoped(secrets, "platform"),
                 "Enter each in GitHub Secrets. Required ones (🔴) must be set before the first "
                 "deploy — the preflight fails closed if they are missing.")

    # --- Deployment ---
    lines.append("## 2. Deployment (GitHub Actions → server)")
    lines.append("")
    lines.append("These let the deploy workflow reach the server. They are **never** written "
                 "into the server's runtime env.")
    lines.append("")
    secret_block("Secrets — deployment", scoped(secrets, "deployment"))

    # --- GPU node ---
    lines.append("## 3. GPU node (seller agent)")
    lines.append("")
    lines.append("Config for a seller's GPU machine running the agent. The GPU node **never** "
                 "receives any platform secret (Stripe, DB, admin, signing key).")
    lines.append("")
    var_block("Variables — GPU node", scoped(variables, "gpu"))
    secret_block("Secrets — GPU node", scoped(secrets, "gpu"))

    # --- Newsletter callout ---
    lines.append("## 4. Newsletter (Mailgun) — one-time Mailgun setup")
    lines.append("")
    lines.append("The newsletter runs on the Mailgun sending subdomain **news.petabyte.market**, "
                 "sends **From `updates@petabyte.market`**, and forwards replies to "
                 "**`info@petabyte.market`**. The signup form adds subscribers to a Mailgun "
                 "mailing list. Configure in this order:")
    lines.append("")
    lines.append("1. In Mailgun, add + verify the sending domain `news.petabyte.market` "
                 "(DNS: SPF, DKIM, and a tracking CNAME).")
    lines.append("2. Create a **mailing list** on that domain (e.g. `newsletter@news.petabyte.market`) "
                 "and set its From name/address to `updates@petabyte.market`.")
    lines.append("3. Add a Mailgun **Route** that forwards replies to that list/address on to "
                 "`info@petabyte.market`.")
    lines.append("4. Set the GitHub Variables `NEWSLETTER_PROVIDER=mailgun`, "
                 "`MAILGUN_NEWSLETTER_DOMAIN=news.petabyte.market`, "
                 "`NEWSLETTER_LIST_ADDRESS=newsletter@news.petabyte.market`, "
                 "`NEWSLETTER_FROM=updates@petabyte.market`, "
                 "`NEWSLETTER_REPLY_TO=info@petabyte.market` (defaults already match). The "
                 "newsletter reuses the `MAILGUN_API_KEY` secret — no extra key needed.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("### Validate after entering everything")
    lines.append("")
    lines.append("```bash")
    lines.append("# locally, with the same values exported, or let CI's configuration-preflight run it:")
    lines.append("python scripts/validate_github_configuration.py --env-name test        # test/staging")
    lines.append("python scripts/validate_github_configuration.py --env-name production   # production")
    lines.append("```")
    lines.append("")
    lines.append("Secrets are reported only as `NAME=SET` / `MISSING` — values are never printed.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    with open(MANIFEST) as f:
        manifest = yaml.safe_load(f)
    code_map = scan_code_vars()

    os.makedirs(os.path.dirname(REF_OUT), exist_ok=True)
    with open(REF_OUT, "w") as f:
        f.write(build_reference(manifest, code_map))
    with open(CHECKLIST_OUT, "w") as f:
        f.write(build_checklist(manifest))
    print(f"wrote {REF_OUT}")
    print(f"wrote {CHECKLIST_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
