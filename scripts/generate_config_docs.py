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
        "GitHub is the source of truth for deployment configuration. **All non-sensitive "
        "values live in ONE Repository Variable, `ENV_VARS`** (as `KEY=value;` pairs); "
        "credentials/keys/tokens/passwords are **individual GitHub Secrets**. At deploy time "
        "the workflow parses `ENV_VARS`, injects the Secrets, and generates the server env "
        "file atomically — nothing long-lived is hand-maintained on the server. The table "
        "below documents every key that `ENV_VARS` may contain (and every Secret); generate a "
        "ready-to-paste bundle with `python scripts/env_bundle.py generate`.",
        "",
        "Precedence: **GitHub Secrets > ENV_VARS > manifest defaults** (secret keys are "
        "refused inside `ENV_VARS`, so the two never conflict). The only standalone Variables "
        "are `ENV_VARS` and `DEPLOY_CONFIG_FROM_GITHUB`; do not create individual Variables for "
        "anything else — the preflight reports leftover legacy Variables as a conflict.",
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
    lines.append("The deploy derives the environment from the `ENVIRONMENT` key inside `ENV_VARS` "
                 "(validated with `--env-name auto`). Use GitHub **Environments** for "
                 "environment-specific `ENV_VARS`/Secrets and protection rules:")
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
    import env_vars as ev
    variables = manifest.get("variables", {})
    secrets = manifest.get("secrets", {})

    def scoped(items, scope):
        return {k: v for k, v in items.items() if scope in v.get("scope", [])}

    def bundle_lines(scopes):
        out = []
        for name in sorted(variables):
            meta = variables[name]
            if name in ev.BOOTSTRAP_VARS or ev.is_secret_name(name, manifest):
                continue
            if not (set(meta.get("scope", [])) & scopes):
                continue
            d = meta.get("default")
            d = "" if d in (None,) else d
            out.append(f"{name}={d};")
        return out

    lines = [
        "# GitHub manual setup checklist",
        "",
        "> **Generated** by `scripts/generate_config_docs.py`. The setup is now tiny: create "
        "**one** Variable (`ENV_VARS`) holding all non-secret config, set the small set of "
        "**Secrets** individually, and flip one gate. You should not need to search the repo.",
        "",
        "**GitHub → Settings → Secrets and variables → Actions.**",
        "",
        "Legend: 🔴 required · ⚪ optional (default is safe).",
        "",
        "## 1. Create the `ENV_VARS` Variable",
        "",
        "Under **Variables**, create **`ENV_VARS`** and paste the bundle below (all non-secret "
        "config as `KEY=value;` pairs — newlines are fine). Regenerate any time with "
        "`python scripts/env_bundle.py generate`. **Never put a secret in here** — the deploy "
        "rejects any secret-classified key found in `ENV_VARS`.",
        "",
        "```ini",
    ]
    lines += bundle_lines({"platform", "observability"})
    lines.append("```")
    lines.append("")
    lines.append("Edit values in place before pasting (e.g. `ENVIRONMENT=production;`, "
                 "`STRIPE_MODE=live;` when going live). Anything you omit falls back to the "
                 "safe manifest default. Validate a bundle locally with "
                 "`python scripts/env_bundle.py validate` (reads `$ENV_VARS`, a `--file`, or stdin).")
    lines.append("")

    lines.append("## 2. Create the `DEPLOY_CONFIG_FROM_GITHUB` Variable")
    lines.append("")
    lines.append("Set **`DEPLOY_CONFIG_FROM_GITHUB=false`** while you finish setup. Flip it to "
                 "**`true`** once `ENV_VARS` + all required Secrets are in — then the deploy "
                 "generates the server env from GitHub and pushes it (atomically, with health "
                 "check + auto-rollback). These two are the ONLY standalone Variables; every "
                 "other non-secret value lives in `ENV_VARS`.")
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

    # --- Secrets (individually managed) ---
    lines.append("## 3. Secrets (individually managed — NOT in ENV_VARS)")
    lines.append("")
    lines.append("Create each under **Secrets**. Required ones (🔴) must exist before the first "
                 "gated deploy — the preflight fails closed if any is missing. Values are never "
                 "printed anywhere.")
    lines.append("")
    secret_block("Platform secrets", scoped(secrets, "platform"))
    secret_block("Deployment secrets (GitHub Actions → server; never in the runtime env)",
                 scoped(secrets, "deployment"))

    # --- GPU node ---
    lines.append("## 4. GPU node (seller agent) — configured on the node, not the platform")
    lines.append("")
    lines.append("A seller's GPU machine gets its OWN config (it never receives any platform "
                 "secret). Generate its bundle with `python scripts/env_bundle.py generate "
                 "--scope gpu` and set its secrets on the node:")
    lines.append("")
    lines.append("```ini")
    lines += bundle_lines({"gpu"})
    lines.append("```")
    lines.append("")
    secret_block("GPU node secrets", scoped(secrets, "gpu"))

    # --- Newsletter callout ---
    lines.append("## 5. Newsletter (Mailgun) — one-time Mailgun setup")
    lines.append("")
    lines.append("The newsletter runs on the Mailgun sending subdomain **news.petabyte.market**, "
                 "sends **From `updates@petabyte.market`**, and forwards replies to "
                 "**`info@petabyte.market`**. The signup form adds subscribers to a Mailgun "
                 "mailing list. Configure in this order:")
    lines.append("")
    lines.append("1. In Mailgun, add + verify the sending domain `news.petabyte.market` "
                 "(DNS: SPF, DKIM, and a tracking CNAME).")
    lines.append("2. Create a **mailing list** on that domain (e.g. `newsletter@news.petabyte.market`) "
                 "and set its From name/address to `updates@petabyte.market` on the list itself.")
    lines.append("3. Add a Mailgun **Route** that forwards replies to that list/address on to "
                 "`info@petabyte.market`.")
    lines.append("4. The newsletter keys are already in the `ENV_VARS` bundle above "
                 "(`NEWSLETTER_PROVIDER=mailgun`, "
                 "`NEWSLETTER_LIST_ADDRESS=newsletter@news.petabyte.market`) — defaults match, no "
                 "change needed. From / Reply-To and reply-forwarding are configured **on the list "
                 "in Mailgun** (steps 2–3), not via env vars. The newsletter reuses the "
                 "`MAILGUN_API_KEY` **Secret** — no extra key.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("### Validate after entering everything")
    lines.append("")
    lines.append("```bash")
    lines.append("# validate the ENV_VARS bundle itself (syntax, no secrets, known keys):")
    lines.append("ENV_VARS=\"$(pbpaste)\" python scripts/env_bundle.py validate   # or --file bundle.txt")
    lines.append("# full preflight (bundle + Secrets + safety rules); CI runs this on every deploy:")
    lines.append("python scripts/validate_github_configuration.py --env-name auto")
    lines.append("```")
    lines.append("")
    lines.append("Secrets are reported only as `NAME=SET` / `MISSING` — values are never printed. "
                 "A secret accidentally placed in `ENV_VARS`, an unknown key, a duplicate, or a "
                 "leftover legacy individual Variable all FAIL the preflight.")
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
