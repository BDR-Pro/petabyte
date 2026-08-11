# Signing agent releases (so auto-update can be turned on)

The seller-agent auto-updaters **fail closed**: they apply an update ONLY if it is signed by a
**pinned** Ed25519 release key (`desktop-app/updater.py` `verify_update`; `lumaris_agent/update.sh`
`verify_bundle`). This is deliberate — TLS alone would let a compromised server or GitHub account
push root-run code to the whole fleet. The consequence, called out in PR #12 review, is that until
releases are actually **signed** and the **public key is pinned into the build**, auto-update
cannot be enabled. That is safe (nothing runs unsigned), but the wiring below is required before
turning `PETABYTE_AUTO_UPDATE=true` on for any node.

Nothing here is a code change — it is a one-time founder/CI setup. The producer (`scripts/sign_release.py`)
and both verifiers already exist and are round-trip tested (`scripts/sign_release_test.py`,
`desktop-app/updater_test.py`).

## 1. Generate the release key (once, offline)
```bash
python scripts/sign_release.py --gen-key release_ed25519.pem   # writes a 0600 PKCS8 key
```
Keep `release_ed25519.pem` **offline** (a hardware token or an encrypted secrets store). The command
prints the PUBLIC key in the two encodings you pin below. **Never commit the private key.**

## 2. Pin the PUBLIC key into the build
- **Windows desktop agent:** set `_PINNED_RELEASE_PUBKEY` in `desktop-app/updater.py` to the printed
  base64 value at build time (or ship `PETABYTE_RELEASE_PUBKEY` in the packaged env). A build with no
  pinned key refuses to auto-update — by design.
- **Linux node agent:** ship the printed PEM to `/etc/petabyte/release_ed25519.pub` in the installer
  (`lumaris_agent/update.sh` reads `PETABYTE_RELEASE_PUBKEY`, default that path). `install.sh` already
  leaves the update timer **disabled** unless `PETABYTE_AUTO_UPDATE=true`.

## 3. Sign every release in CI (private key as a Secret)
Store the private key as the `RELEASE_SIGNING_KEY` GitHub **Secret** (never in git). After the build
produces `PetabyteAgent.exe` and `agent.tar.gz`, sign and attach the outputs to the GitHub Release:
```bash
printf '%s' "$RELEASE_SIGNING_KEY" > /tmp/rk.pem && chmod 600 /tmp/rk.pem
python scripts/sign_release.py --key /tmp/rk.pem --version "${GITHUB_REF_NAME#v}" \
    --exe dist/PetabyteAgent.exe --tarball dist/agent.tar.gz --out-dir dist
rm -f /tmp/rk.pem
# upload dist/PetabyteAgent.exe.manifest.json and dist/agent.tar.gz.sig as release assets
```
The manifest's signed `version` MUST equal the release tag and its `asset` MUST be
`PetabyteAgent.exe` — the updater now enforces both (anti-replay), so a re-uploaded older signed
build is rejected under a newer tag.

## 4. Turn auto-update on (per node, opt-in)
Only after 1–3 are in place: re-run the installer with `PETABYTE_AUTO_UPDATE=true` (Linux), or ship
a desktop build carrying the pinned key. Until then the fail-closed default keeps the fleet safe.

## Rotation
Generate a new key, pin the new public key in the next build, and sign subsequent releases with it.
Because the key is pinned in the build, a rotation reaches a node only via an update that was signed
by the **previous** key — so rotate in two steps (ship the new pin signed by the old key, then start
signing with the new key).
