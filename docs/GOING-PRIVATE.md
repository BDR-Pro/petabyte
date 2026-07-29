# Making the repo private — what changes

Short version: mostly nothing breaks, and the one thing that WOULD break (seller
onboarding) is now fixed. Do the checklist below before you flip the switch.

## Fixed already (was the real breakage)
The node installer used to `git clone` this repo to get the agent code. On a private
repo that clone fails auth on every host, silently killing all seller onboarding.
Now the agent is served from YOUR server as `/agent.tar.gz` (built on every deploy),
and the installer + updater pull it from there. GitHub clone remains only as a fallback.
Hosts never need any GitHub credential. Guarded by smoke tests.

## Do these before flipping to private
1. **Droplet git pull** — /root/petabyte must be able to pull from a private repo.
   Check: `cd /root/petabyte && git remote -v`.
   - If it's an https:// remote, add a deploy key or a fine-grained PAT, or switch to SSH:
     `git remote set-url origin git@github.com:BDR-Pro/petabyte.git` and add a read-only
     **deploy key** (repo → Settings → Deploy keys) for the droplet's SSH key.
2. **GitHub Actions deploy** — no change needed. Actions always has access to its own
   private repo; the SSH deploy secrets are unaffected.
3. **Nothing else fetches the repo anonymously** — verified: no raw.githubusercontent
   URLs are used at runtime; installers are served by the API.

## Things that change but don't break
- **Actions minutes**: public repos get unlimited Actions; private repos are metered on
  the free tier (generous monthly allowance). Your deploy job is tiny, so this is
  negligible — just no longer literally unlimited.
- **Anything that assumed the code was public** (e.g. someone reading install.sh on
  github.com) now needs access. Your install one-liners already come from
  petabyte.market, not GitHub, so users are unaffected.
- The footer "GitHub" link (github.com/BDR-Pro) will 404 for logged-out visitors. Decide
  whether to keep it, point it at a public profile, or remove it.

## Doesn't change
- Deploy over SSH from Actions, secrets, the droplet app, the API, all installers for end
  users (served from your domain), Cal.com, everything runtime.
