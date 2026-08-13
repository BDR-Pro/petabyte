# Signing desktop-agent releases (so auto-update works)

The Windows desktop agent (`PetabyteAgent.exe`) auto-updates itself, but **only applies an update
it can cryptographically verify** — the downloaded exe's SHA-256 must match a manifest that is
Ed25519-signed by a release key **pinned into the running build** (`desktop-app/updater.py`). This
is deliberate: an auto-updater that runs whatever is attached to a GitHub Release is a fleet-wide
remote-code-execution button. Until a key is configured the updater **fails closed** (refuses every
update) — safe, but no auto-update.

You sign entirely from the **GitHub UI — no terminal needed.** Two workflows do it:

| Workflow | File | What it does |
|---|---|---|
| **Generate Release Signing Key** | `.github/workflows/release-keygen.yml` | Creates the Ed25519 keypair |
| **Release Desktop Agent (.exe)** | `.github/workflows/release-desktop.yml` | Pins the public key, builds, **signs**, and publishes |

## One-time setup

1. **Generate the key.** Actions tab → **Generate Release Signing Key** → **Run workflow**. It:
   - prints the **public key** (base64) to the run log — safe to expose;
   - uploads the **private key** (`release_ed25519.pem`) as a 1-day, collaborator-only artifact —
     never printed to the log.
2. **Store the private key as a secret.** Download the `release-signing-key` artifact, open
   `release_ed25519.pem`, then: repo **Settings → Secrets and variables → Actions → Secrets → New
   repository secret** → name `RELEASE_SIGNING_KEY`, value = the full PEM (`-----BEGIN … END-----`).
3. **Store the public key as a variable.** Same page → **Variables → New repository variable** →
   name `PETABYTE_RELEASE_PUBKEY`, value = the base64 public key from the log.
4. **Delete the artifact** (the private key must live only in the secret, offline).

That's it. The private key exists only as the GitHub secret — it never lives in the app, in an
admin page, or in a log.

## Cutting a signed release

1. Bump `VERSION` in `desktop-app/version.py`.
2. Tag and push: `git tag v1.2.3 && git push origin v1.2.3`.

The **Release Desktop Agent** workflow then, for that tag:
- **pins** `PETABYTE_RELEASE_PUBKEY` into the binary (`pin_pubkey.py` → `updater.py`),
- **builds** `PetabyteAgent.exe`,
- **signs** it with `RELEASE_SIGNING_KEY` (`scripts/sign_release.py` →
  `PetabyteAgent.exe.manifest.json`),
- **attaches both** the exe and the manifest to the GitHub Release.

Installed agents poll the Releases API, download the exe **and** the manifest, and swap themselves
in only after verifying the exe against the pinned key + the signed, release-bound manifest
(`desktop-app/updater.verify_update`). The whole producer↔verifier loop is tested offline by
`scripts/sign_release_test.py` (in CI).

## If the keys aren't set

The release workflow still builds and publishes the exe, but logs a warning and attaches **no**
manifest — so those installs keep running and simply **do not auto-update** (fail-closed). Set the
secret + variable and cut a new tagged release to turn auto-update on.

## Rotating the key

Re-run **Generate Release Signing Key**, replace the secret + variable, and cut a new release.
Installs updated from a release signed by the **old** key won't accept updates signed by the
**new** key until they're reinstalled from a new-key release — so rotate deliberately.

## Why a workflow and not an admin page

A release signing key is the most sensitive key the project holds — whoever has it can push code to
every installed agent. It belongs in an offline/secret store (a GitHub Actions secret), used only by
the release pipeline. Exposing it through an admin web page — generated, displayed, or used to sign
there — would put that key on a running, internet-facing server and in a browser session, which is
exactly what we don't want. The GitHub-secret model keeps it out of the app entirely.

## Linux / WSL agent auto-update

The same key also signs the Linux agent bundle. The app side is fully wired:

- The API **serves `/agent.tar.gz.sig`** (the detached signature) and **pins the public key into
  the served `install.sh`** — it substitutes `PETABYTE_RELEASE_PUBKEY` (as PEM) at download time,
  and the installer writes it to `/etc/petabyte/release_ed25519.pub`. Unset ⇒ no key is pinned and
  `update.sh` refuses to auto-update (fail-closed; it never trusts TLS alone for root-run code).
- `lumaris_agent/update.sh` downloads the bundle + its `.sig` and verifies with
  `openssl pkeyutl -verify -rawin` against the pinned key before applying.

The **one remaining operational step** is producing the signature at deploy time. Because
`agent.tar.gz` is built when you deploy, sign it in the deploy pipeline **where the private key is
available** (never place the key on the app server):

```bash
# in the deploy runner, with RELEASE_SIGNING_KEY available as an env/secret:
printf '%s\n' "$RELEASE_SIGNING_KEY" > /tmp/rk.pem
python scripts/sign_release.py --key /tmp/rk.pem \
    --tarball lumaris_api/installers/agent.tar.gz --out-dir lumaris_api/installers
shred -u /tmp/rk.pem
```

That writes `agent.tar.gz.sig` next to the bundle; the API then serves it and signed WSL
auto-update works. Set the `PETABYTE_RELEASE_PUBKEY` variable so new installs pin the key.
The producer↔verifier loop (both exe manifest and raw tarball `.sig`) is tested offline in
`scripts/sign_release_test.py`.
