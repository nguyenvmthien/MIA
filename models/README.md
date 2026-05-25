# Model Artifacts

This directory is the local model registry for trained adapters, GGUF exports, promotion manifests, and serving metadata.

Large artifacts are intentionally not committed to Git. Recreate or place them here by running the documented training and promotion commands:

Expected runtime layout:

```text
models/
├── baseline-action-detector/     # committed lightweight trained baseline
│   ├── model.joblib
│   ├── metadata.json
│   └── README.md
├── qwen-meeting-latest/        # retraining output directory
│   ├── adapter/                # PEFT/LoRA adapter, if produced
│   └── gguf/                   # Ollama-compatible export, if produced
└── registry/
    ├── promotion_manifest.json # written after a candidate passes promotion gates
    └── serving.env             # written by deploy-promoted-model
```

Typical commands:

```bash
make train-baseline

python3 -m meeting_agent.mlops.finetune \
  --data data/training/synthetic.jsonl \
  --output models/qwen-meeting-latest

make deploy-promoted-model APPLY=1
```

For the default demo, the system uses the external Ollama model name configured by `OLLAMA_LLM_MODEL` and does not require a committed checkpoint.
