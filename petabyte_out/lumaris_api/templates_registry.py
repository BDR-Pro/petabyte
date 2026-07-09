"""One-click deployment templates. The agent launches the image; the API records
the dispatch and the connection details the agent reports back."""

TEMPLATES = {
    "ollama": {
        "image": "ollama/ollama:latest", "port": 11434, "gpu": True,
        "desc": "Ollama — local LLM server (OpenAI-compatible /api)",
        "model_env": "OLLAMA_MODEL",           # e.g. llama3
        "cache": "/root/.ollama",
    },
    "vllm": {
        "image": "vllm/vllm-openai:latest", "port": 8000, "gpu": True,
        "desc": "vLLM — high-throughput OpenAI-compatible inference",
        "model_arg": "--model",                # e.g. a HF model id
        "cache": "/root/.cache/huggingface",
    },
    "tensorrt-llm": {
        "image": "nvcr.io/nvidia/tritonserver:24.05-trtllm-python-py3", "port": 8000,
        "gpu": True, "desc": "TensorRT-LLM via Triton (max throughput on NVIDIA)",
        "cache": "/root/.cache/huggingface",
    },
    "comfyui": {
        "image": "yanwk/comfyui-boot:latest", "port": 8188, "gpu": True,
        "desc": "ComfyUI — node-based Stable Diffusion",
        "cache": "/root/.cache",
    },
    "ffmpeg": {
        "image": "jrottenberg/ffmpeg:6.1-nvidia", "port": 0, "gpu": True,
        "desc": "FFmpeg transcode node (NVENC/NVDEC; use /transcode for segment jobs)",
        "cache": "/tmp",
    },
    "blender": {
        "image": "linuxserver/blender:latest", "port": 3000, "gpu": True,
        "desc": "Blender headless render node (use /render for frame jobs)",
        "cache": "/config",
    },
    "minecraft": {
        "image": "itzg/minecraft-server:latest", "port": 25565, "gpu": False,
        "desc": "Minecraft Java server (stateful — enable backups)",
        "cache": "/data", "stateful": True, "volume": "minecraft-world",
    },
    "valheim": {
        "image": "lloesche/valheim-server:latest", "port": 2456, "gpu": False,
        "desc": "Valheim dedicated server (stateful — enable backups)",
        "cache": "/config", "stateful": True, "volume": "valheim-world",
    },
    "factorio": {
        "image": "factoriotools/factorio:stable", "port": 34197, "gpu": False,
        "desc": "Factorio headless server (stateful — enable backups)",
        "cache": "/factorio", "stateful": True, "volume": "factorio-saves",
    },
    "sd-webui": {
        "image": "universonic/stable-diffusion-webui:latest", "port": 7860, "gpu": True,
        "desc": "Stable Diffusion WebUI (AUTOMATIC1111)",
        "cache": "/root/.cache",
    },
}


def public_catalog():
    return [{"name": k, "desc": v["desc"], "port": v["port"], "gpu": v["gpu"],
             "stateful": v.get("stateful", False)}
            for k, v in TEMPLATES.items()]
