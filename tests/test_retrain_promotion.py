import json

from meeting_agent.mlops import retrain
from meeting_agent.mlops.retrain import _build_promotion_manifest


def test_build_promotion_manifest_records_serving_target(monkeypatch, tmp_path):
    output_dir = tmp_path / "qwen-meeting-latest"
    gguf_dir = output_dir / "gguf"
    gguf_dir.mkdir(parents=True)
    (gguf_dir / "model.gguf").write_bytes(b"model-bytes")
    monkeypatch.setenv("PROMOTED_OLLAMA_MODEL_TAG", "meeting-agent:test")
    monkeypatch.setenv("OLLAMA_LLM_MODEL", "meeting-agent:old")

    manifest = _build_promotion_manifest(
        {"avg_f1": 0.81},
        str(output_dir),
        mlflow_model_version="7",
        mlflow_run_id="run-1",
    )

    assert manifest["schema_version"] == "model_promotion_v1"
    assert manifest["ollama_model_tag"] == "meeting-agent:test"
    assert manifest["artifact_path"].endswith("gguf")
    assert manifest["artifact_sha256"]
    assert manifest["mlflow_model_version"] == "7"
    assert manifest["serving_update"] == {
        "automatic": False,
        "env_var": "OLLAMA_LLM_MODEL",
        "target_value": "meeting-agent:test",
        "rollback_value": "meeting-agent:old",
    }


def test_write_promotion_manifest_uses_models_registry(monkeypatch, tmp_path):
    registry_dir = tmp_path / "models" / "registry"
    monkeypatch.setattr(retrain, "_PROMOTION_MANIFEST_PATH", registry_dir / "promotion_manifest.json")

    retrain._write_promotion_manifest({"schema_version": "model_promotion_v1"})

    manifest_path = registry_dir / "promotion_manifest.json"
    assert json.loads(manifest_path.read_text()) == {"schema_version": "model_promotion_v1"}
