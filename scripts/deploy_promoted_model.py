"""Deploy a promoted model manifest to Ollama and write serving config."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_MANIFEST = Path("data/training/.promotion_manifest.json")
DEFAULT_SERVING_ENV = Path("data/training/.serving.env")


def _find_gguf(artifact_path: Path) -> Path:
    if artifact_path.is_file() and artifact_path.suffix == ".gguf":
        return artifact_path
    candidates = sorted(artifact_path.rglob("*.gguf")) if artifact_path.exists() else []
    if not candidates:
        raise FileNotFoundError(f"No .gguf file found under {artifact_path}")
    return candidates[0]


def _write_modelfile(model_file: Path, gguf_path: Path) -> None:
    model_file.write_text(
        "\n".join([
            f"FROM {gguf_path.resolve()}",
            "PARAMETER temperature 0",
            "PARAMETER seed 42",
            "",
        ])
    )


def _write_serving_env(path: Path, model_tag: str, *, backup: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, path.with_suffix(path.suffix + f".{stamp}.bak"))
    path.write_text(f"OLLAMA_LLM_MODEL={model_tag}\n")


def deploy(manifest_path: Path, serving_env: Path, *, apply: bool = False) -> dict:
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") != "model_promotion_v1":
        raise ValueError("Unsupported promotion manifest schema")

    model_tag = manifest["ollama_model_tag"]
    artifact_path = Path(manifest["artifact_path"])
    gguf_path = _find_gguf(artifact_path)
    modelfile = manifest_path.parent / f"Modelfile.{model_tag.replace(':', '_')}"
    _write_modelfile(modelfile, gguf_path)

    result = {
        "apply": apply,
        "model_tag": model_tag,
        "gguf_path": str(gguf_path),
        "modelfile": str(modelfile),
        "serving_env": str(serving_env),
    }
    if not apply:
        result["next_command"] = f"ollama create {model_tag} -f {modelfile}"
        return result

    subprocess.run(["ollama", "create", model_tag, "-f", str(modelfile)], check=True)
    _write_serving_env(serving_env, model_tag, backup=True)
    result["deployed"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--serving-env", type=Path, default=DEFAULT_SERVING_ENV)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(deploy(args.manifest, args.serving_env, apply=args.apply), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
