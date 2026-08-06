#!/usr/bin/env bash
# Install GPU host dependencies for a Petabyte seller node: Docker, NVIDIA drivers check,
# and the NVIDIA Container Toolkit (so containers can use the GPU). Idempotent + verbose.
# Run as root on the seller GPU Droplet. Copy/paste ready.
set -Eeuo pipefail
step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
ok()   { printf '   \033[32mOK\033[0m %s\n' "$1"; }
warn() { printf '   \033[33m!!\033[0m %s\n' "$1"; }

step "NVIDIA driver"
if command -v nvidia-smi >/dev/null; then nvidia-smi | head -15; ok "driver present"; else
  warn "no NVIDIA driver — install the vendor driver for your GPU before continuing"; fi

step "Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
docker --version && ok "docker present"

step "NVIDIA Container Toolkit"
if ! docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi >/dev/null 2>&1; then
  distribution=$(. /etc/os-release; echo "$ID$VERSION_ID")
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -fsSL "https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list" \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update -y && apt-get install -y nvidia-container-toolkit
  nvidia-ctk runtime configure --runtime=docker && systemctl restart docker
fi
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi >/dev/null \
  && ok "GPU visible inside containers" || { warn "GPU still not visible in containers"; exit 1; }

step "Python for the agent"
command -v python3 >/dev/null || apt-get install -y python3 python3-pip
python3 -m pip install -q -r /opt/petabyte/lumaris_agent/requirements.txt 2>/dev/null || \
  warn "agent requirements not installed (clone the repo to /opt/petabyte first)"

echo; ok "GPU dependencies ready. Next: set PETABYTE_API_URL/API_KEY/SPEC_ID and start the agent."
