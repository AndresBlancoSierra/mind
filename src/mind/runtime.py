"""Runtime inspection: GPU, CUDA, local LLM runtime and selected model."""

from __future__ import annotations

import shutil
import subprocess

from mind.config import load_settings


def _nvidia_smi() -> dict[str, str]:
    bin_path = shutil.which("nvidia-smi")
    if not bin_path:
        return {"gpu": "not_detected"}
    try:
        out = subprocess.run(
            [bin_path, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except Exception:
        return {"gpu": "inspection_failed"}
    if not out:
        return {"gpu": "not_detected"}
    parts = [p.strip() for p in out.split(",")]
    report: dict[str, str] = {"gpu": parts[0] if len(parts) > 0 else "unknown"}
    if len(parts) > 1:
        report["vram"] = parts[1]
    if len(parts) > 2:
        report["driver"] = parts[2]
    return report


def _ollama_status(settings) -> dict[str, str]:
    import httpx

    try:
        resp = httpx.get(f"{settings.llm.base_url}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        installed = {m.split(":", 1)[0] for m in models}
        has_model = settings.llm.model.split(":", 1)[0] in installed
        has_embed = settings.embeddings.model.split(":", 1)[0] in installed
        return {
            "runtime": "ollama",
            "runtime_up": "yes",
            "model": settings.llm.model,
            "model_installed": "yes" if has_model else "no",
            "embedding_model": settings.embeddings.model,
            "embedding_model_installed": "yes" if has_embed else "no",
            "installed_models": ", ".join(models) or "none",
        }
    except Exception:
        return {
            "runtime": "ollama",
            "runtime_up": "no",
            "model": settings.llm.model,
            "model_installed": "unknown",
        }


def runtime_report() -> dict[str, str]:
    settings = load_settings()
    report: dict[str, str] = {}
    report.update(_nvidia_smi())
    report.update(_ollama_status(settings))
    report["python_runtime"] = settings.llm.runtime
    return report
