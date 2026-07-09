# Push-to-deploy (server)

Push to `main` → GitHub Actions SSHes into the droplet and runs
`deploy/update.sh` (pull + migrate-if-needed + restart). No manual SSH.

## One-time setup

### 1. Make `/opt/lumaris` a git checkout
The first `deploy.sh` rsyncs code into `/opt/lumaris` (no `.git`). Convert it once
so `git pull` works there:
```bash
ssh root@DROPLET_IP
systemctl stop lumaris-api lumaris-reaper
mv /opt/lumaris /opt/lumaris.bak
git clone https://github.com/BDR-Pro/lumaris_api.git /opt/lumaris   # your API repo
cd /opt/lumaris
python3 -m venv .venv && .venv/bin/pip install -U pip -r requirements.txt
cp -n /opt/lumaris.bak/.venv/../*.db . 2>/dev/null || true          # (sqlite only; skip on Postgres)
chown -R lumaris:lumaris /opt/lumaris
systemctl start lumaris-api lumaris-reaper
```
`/etc/lumaris/lumaris.env` is untouched — secrets and DB stay put.

### 2. A deploy SSH key
```bash
ssh-keygen -t ed25519 -f deploy_key -N ""      # on your machine
# add the PUBLIC key to the droplet:
ssh-copy-id -i deploy_key.pub root@DROPLET_IP   # or append to ~/.ssh/authorized_keys
```

### 3. GitHub repo secrets (Settings → Secrets and variables → Actions)
| Secret           | Value                                  |
|------------------|----------------------------------------|
| `DROPLET_HOST`   | droplet IP or `api.yourdomain.com`     |
| `DROPLET_USER`   | `root` (or a deploy user, see below)   |
| `DEPLOY_SSH_KEY` | contents of the **private** `deploy_key` |

### 4. (Recommended) non-root deploy user
Instead of `root`, use a `deploy` user limited to just the update command:
```bash
useradd -m -s /bin/bash deploy
mkdir -p /home/deploy/.ssh && cp ~/.ssh/authorized_keys /home/deploy/.ssh/ && chown -R deploy:deploy /home/deploy/.ssh
# allow only the update script via sudo, no password:
echo 'deploy ALL=(root) NOPASSWD: /opt/lumaris/deploy/update.sh' > /etc/sudoers.d/deploy-lumaris
chmod 440 /etc/sudoers.d/deploy-lumaris
```
Set `DROPLET_USER=deploy`.

## How it triggers
Any push to `main` that touches `lumaris_api/**` runs the workflow. You can also run
it manually from the Actions tab ("Run workflow"). Watch the run log for the
`deployed <old> -> <new>` line; verify with `curl https://api.yourdomain.com/healthz`.

## Rollback
```bash
ssh root@DROPLET_IP 'cd /opt/lumaris && git reset --hard HEAD~1 && systemctl restart lumaris-api lumaris-reaper'
```
