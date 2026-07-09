# Push-to-deploy (server)

Push to `main` → GitHub Actions SSHes into the droplet and runs `deploy/update.sh`,
which pulls the monorepo and syncs `lumaris_api/` into the running app dir, migrates,
and restarts. No manual SSH.

Layout: the monorepo is checked out at **`/opt/petabyte`** (the pull source); the API
runs from **`/opt/lumaris`** (created by the first `deploy.sh`). `update.sh` rsyncs
`lumaris_api/` from the checkout into `/opt/lumaris`, so it never touches your venv,
database, or `/etc/lumaris/lumaris.env`.

## One-time setup

### 1. Clone the monorepo on the droplet
    ssh root@DROPLET_IP
    git clone https://github.com/BDR-Pro/petabyte.git /opt/petabyte
    # /opt/lumaris already exists from the first deploy.sh run

### 2. A deploy SSH key
    ssh-keygen -t ed25519 -f deploy_key -N ""       # on your machine
    ssh-copy-id -i deploy_key.pub root@DROPLET_IP    # add PUBLIC key to the droplet

### 3. GitHub repo secrets (Settings -> Secrets and variables -> Actions)
| Secret           | Value                                    |
|------------------|------------------------------------------|
| DROPLET_HOST     | droplet IP or api.yourdomain.com         |
| DROPLET_USER     | root (or a limited deploy user)          |
| DEPLOY_SSH_KEY   | contents of the PRIVATE deploy_key       |

### 4. (Recommended) non-root deploy user
    useradd -m -s /bin/bash deploy
    mkdir -p /home/deploy/.ssh && cp ~/.ssh/authorized_keys /home/deploy/.ssh/ && chown -R deploy:deploy /home/deploy/.ssh
    echo 'deploy ALL=(root) NOPASSWD: /opt/lumaris/deploy/update.sh' > /etc/sudoers.d/deploy-lumaris
    chmod 440 /etc/sudoers.d/deploy-lumaris
Set DROPLET_USER=deploy.

## Trigger & verify
Any push to main touching lumaris_api/** runs .github/workflows/deploy-server.yml (or
run it manually from the Actions tab). Watch for the "deployed <old> -> <new>" line,
then: curl https://api.yourdomain.com/healthz

## Rollback
    ssh root@DROPLET_IP 'cd /opt/petabyte && git reset --hard HEAD~1 && /opt/lumaris/deploy/update.sh'
