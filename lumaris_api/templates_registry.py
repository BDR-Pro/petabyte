"""Template registry.

EGRESS POLICY — read this before adding a template.

A rented container runs on a stranger's machine, on their home internet, behind their
IP address. If a buyer port-scans, spams, joins a botnet, or mines from it, it is the
SELLER who gets the abuse complaint and the SELLER who can lose their home connection.
We are asking a volunteer to carry that risk, so the default must be closed.

    "none"      no network at all. Correct for batch work: render a frame, transcode a
                segment, run an inference job. The input arrives by volume, the output
                leaves by volume. Nothing needs to dial out.
    "limited"   outbound allowed, inbound only on the declared service port via the
                tunnel. For serving templates (an LLM endpoint, a game server) that
                genuinely must be reachable.
    "open"      unrestricted. Reserved for templates that must pull models/packages at
                runtime. Highest abuse risk to the host — use sparingly and say so.

Batch templates MUST be "none". If you find yourself writing "open" for a batch job,
you are about to hand someone else's IP address to a stranger.
"""


TEMPLATES = {
    "ollama": {
        "egress": "limited",
        "image": "ollama/ollama:latest", "port": 11434, "gpu": True,
        "desc": "Ollama — local LLM server (OpenAI-compatible /api)",
        "model_env": "OLLAMA_MODEL",           # e.g. llama3
        "cache": "/root/.ollama",
    },
    "vllm": {
        "egress": "limited",
        "image": "vllm/vllm-openai:latest", "port": 8000, "gpu": True,
        "desc": "vLLM — high-throughput OpenAI-compatible inference",
        "model_arg": "--model",                # e.g. a HF model id
        # vLLM will NOT boot without a model. A one-click launch falls back to this small,
        # ungated model so the server actually starts; the buyer can override via params.model.
        "default_model": "facebook/opt-125m",
        "cache": "/root/.cache/huggingface",
    },
    "comfyui": {
        "egress": "limited",
        "image": "yanwk/comfyui-boot:latest", "port": 8188, "gpu": True,
        "desc": "ComfyUI — node-based Stable Diffusion",
        "cache": "/root/.cache",
    },
    "blender": {
        "egress": "none",
        "image": "linuxserver/blender:latest", "port": 3000, "gpu": True,
        "desc": "Blender headless render node (use /render for frame jobs)",
        "cache": "/config",
    },
    "minecraft": {
        "egress": "limited",
        "image": "itzg/minecraft-server:latest", "port": 25565, "gpu": False,
        "desc": "Minecraft Java server (stateful — enable backups)",
        "cache": "/data", "stateful": True, "volume": "minecraft-world",
    },
    "valheim": {
        "egress": "limited",
        "image": "lloesche/valheim-server:latest", "port": 2456, "gpu": False,
        "desc": "Valheim dedicated server (stateful — enable backups)",
        "cache": "/config", "stateful": True, "volume": "valheim-world",
    },
    "factorio": {
        "egress": "limited",
        "image": "factoriotools/factorio:stable", "port": 34197, "gpu": False,
        "desc": "Factorio headless server (stateful — enable backups)",
        "cache": "/factorio", "stateful": True, "volume": "factorio-saves",
    },
    "jupyter": {
        "egress": "limited",
        "image": "quay.io/jupyter/pytorch-notebook:cuda12-latest", "port": 8888, "gpu": True,
        "desc": "JupyterLab + PyTorch + CUDA — a notebook on a real GPU",
        "cache": "/home/jovyan/work",
        "stateful": True,                 # people leave notebooks running; snapshot them
    },
    "sd-webui": {
        "egress": "limited",
        "image": "universonic/stable-diffusion-webui:latest", "port": 7860, "gpu": True,
        "desc": "Stable Diffusion WebUI (AUTOMATIC1111)",
        "cache": "/root/.cache",
    },
}


_KIND = {"blender": "render", "comfyui": "art", "sd-webui": "art",
         "minecraft": "game", "valheim": "game", "factorio": "game",
         "jupyter": "notebook"}


def public_catalog():
    return [{"name": k, "desc": v["desc"], "port": v["port"], "gpu": v["gpu"],
             "stateful": v.get("stateful", False), "kind": _KIND.get(k, "ai"),
             "egress": v.get("egress", "none")}      # default CLOSED
            for k, v in TEMPLATES.items()]
