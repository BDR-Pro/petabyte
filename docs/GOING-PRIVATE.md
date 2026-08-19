# Making the repo private — what changes

Short version: end-user installs and server deploys keep working, because the agent and
all install one-liners are served from **your** domain, not GitHub. Two things genuinely
break and both now have a fix in-tree: **Windows desktop auto-update** and the **droplet's
`git pull`**. Work the checklist before you flip the switch.

> **Read this first — privacy is not a secret-eraser.** The repo has been public, so its
> **entire git history is already cloned, forked, and cached** by third parties and code
> search engines. Anything ever committed — keys, tokens, `.env` values — must be treated
> as **compromised and rotated**, whether or not you go private. Going private only stops
> *future* exposure. See `SECURITY.md` and `docs/PRODUCTION_GAPS.md` ("Rotate historically
> committed secrets").

## Already fixed (the parts that used to break)
- **Seller onboarding (Linux/agent).** The node installer used to `git clone` this repo to
  get the agent code — that fails auth on every host once private. The agent is now served
  from your server as `/agent.tar.gz` (rebuilt on every deploy) and `install.sh`/`update.sh`
  pull it from there; `git clone` remains only a last-resort fallback. Hosts need no GitHub
  credential. Guarded by `sandbox_test`/`smoke_test`.
- **Windows desktop auto-update.** `desktop-app/updater.py` used to hit
  `api.github.com/.../releases/latest` only — and GitHub Releases inherit repo visibility, so
  a private repo returns 404 to anonymous agents and silently stops all desktop updates. The
  updater now takes a private-safe source (see next section). Integrity is unchanged: every
  update is still refused unless it matches the **pinned Ed25519 signature**, so the source
  can be anything.
- **security.txt contact.** `/.well-known/security.txt` no longer points at
  `github.com/<repo>/security/advisories` (unreachable to outside researchers on a private
  repo); it uses `mailto:security@petabyte.market`, which works regardless.

## Desktop auto-update: pick ONE source before going private
Updates are Ed25519-signed against a build-pinned key, so a public transport leaks nothing and
can't inject an unsigned binary. Either option is safe:

1. **Separate PUBLIC releases repo (recommended, no code change).** Create e.g.
   `BDR-Pro/petabyte-releases` holding ONLY the built `PetabyteAgent.exe` + its signed
   `.manifest.json` (no source). Point `release-desktop.yml` at it (`softprops/action-gh-release`
   `repository:` + a token) and ship agents with `PETABYTE_UPDATE_REPO=BDR-Pro/petabyte-releases`.
   The main code repo goes private; GitHub still serves the releases as a free CDN.
2. **Host it on your domain (fully GitHub-free).** Serve a JSON at, say,
   `https://petabyte.market/desktop/latest.json` →
   `{ "tag": "v1.4.0", "exe_url": "...", "manifest_url": "..." }`, plus the two assets, and ship
   agents with `PETABYTE_UPDATE_URL=https://petabyte.market/desktop/latest.json`. `updater._latest()`
   already reads this shape (covered by `updater_test.py`). Mirrors how the Linux agent is served.

If you ship neither, private is still *safe* — desktop agents just stop auto-updating and log a
warning (they never apply an unsigned/unreachable update).

## Do these before flipping to private
1. **Droplet `git pull`.** The deploy (`/opt/lumaris/deploy/update.sh`) does `git pull` on
   `/root/petabyte`. Give that checkout read access to a private repo:
   `cd /root/petabyte && git remote -v`; if it's `https://`, switch to SSH
   (`git remote set-url origin git@github.com:BDR-Pro/petabyte.git`) and add a **read-only
   deploy key** (repo → Settings → Deploy keys) for the droplet's SSH key — or use a
   fine-grained read-only PAT.
2. **Choose the desktop update source** above and set the env in the shipped build.
3. **Rotate every secret** that was ever committed (see the note at the top).
4. **GitHub Actions** needs no change — a workflow always has access to its own private repo,
   and the SSH deploy secrets are unaffected.

## Things that change but don't break
- **Actions minutes.** Public repos get unlimited Actions; private repos are metered (generous
  free tier). Note the deploy now runs the **full test suite as a gate** (`deploy-server.yml` →
  `tests.yml` via `workflow_call`), plus the normal push/PR runs — so budget for more minutes
  than the old tiny deploy job. Still comfortably within the free allowance for this cadence.
- **Reading the code on github.com** (e.g. someone inspecting `install.sh`) now needs access.
  End users are unaffected — the install one-liners come from `petabyte.market`, not GitHub.
- **`github.com/BDR-Pro`** in the site footer and `sameAs` is the owner **profile**, which
  stays public regardless of repo visibility — no change needed. Only *repo* links would 404.

## Doesn't change
- SSH deploy from Actions, secrets, the droplet app, the API, Cal.com, and every end-user
  installer served from your domain — all runtime paths are GitHub-independent.
