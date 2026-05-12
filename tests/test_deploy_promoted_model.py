import json
from unittest.mock import patch

from scripts.deploy_promoted_model import deploy


def _manifest(tmp_path):
    gguf_dir = tmp_path / "gguf"
    gguf_dir.mkdir()
    (gguf_dir / "model.gguf").write_bytes(b"model")
    manifest = {
        "schema_version": "model_promotion_v1",
        "ollama_model_tag": "meeting-agent:test",
        "artifact_path": str(gguf_dir),
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def test_deploy_promoted_model_dry_run(tmp_path):
    manifest = _manifest(tmp_path)

    result = deploy(manifest, tmp_path / "serving.env", apply=False)

    assert result["model_tag"] == "meeting-agent:test"
    assert "ollama create meeting-agent:test" in result["next_command"]
    assert (tmp_path / "Modelfile.meeting-agent_test").exists()


def test_deploy_promoted_model_apply_writes_serving_env(tmp_path):
    manifest = _manifest(tmp_path)
    serving_env = tmp_path / "serving.env"
    serving_env.write_text("OLLAMA_LLM_MODEL=old\n")

    with patch("scripts.deploy_promoted_model.subprocess.run") as run:
        result = deploy(manifest, serving_env, apply=True)

    run.assert_called_once()
    assert result["deployed"] is True
    assert serving_env.read_text() == "OLLAMA_LLM_MODEL=meeting-agent:test\n"
    assert list(tmp_path.glob("serving.env.*.bak"))
