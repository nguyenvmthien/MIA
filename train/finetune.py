"""
QLoRA fine-tuning script for Qwen2.5-3B-Instruct on action item extraction.

Uses Unsloth for 4-bit NF4 base + LoRA adapters (rank=16).
Logs every run to MLflow for model versioning.

Usage:
    python train/finetune.py \
        --data data/training/meetings.jsonl \
        --output models/qwen-meeting-v1 \
        --epochs 3

Requirements:
    pip install -e ".[train]"
    # GPU with ≥8GB VRAM recommended; falls back to CPU (slow)
"""

import argparse
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ── Hyperparameters ───────────────────────────────────────────────────────────
DEFAULTS = {
    "model_name": "unsloth/Qwen2.5-3B-Instruct-bnb-4bit",
    "max_seq_length": 2048,
    "lora_rank": 16,
    "lora_alpha": 32,
    "lora_dropout": 0.05,
    "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj",
                       "gate_proj", "up_proj", "down_proj"],
    "learning_rate": 2e-4,
    "batch_size": 2,
    "grad_accumulation": 4,
    "warmup_ratio": 0.03,
    "epochs": 3,
    "weight_decay": 0.01,
    "optimizer": "adamw_8bit",
    "lr_scheduler": "cosine",
    "seed": 42,
    # Optuna hyperparameter search (run with --search to activate)
    "optuna_trials": 10,
}


def parse_args():
    p = argparse.ArgumentParser(description="QLoRA fine-tuning for Meeting Agent")
    p.add_argument("--data", nargs="+", required=True, help="JSONL training data file(s)")
    p.add_argument("--output", default="models/qwen-meeting-finetuned", help="Output directory")
    p.add_argument("--epochs", type=int, default=DEFAULTS["epochs"])
    p.add_argument("--rank", type=int, default=DEFAULTS["lora_rank"], help="LoRA rank")
    p.add_argument("--lr", type=float, default=DEFAULTS["learning_rate"])
    p.add_argument("--batch-size", type=int, default=DEFAULTS["batch_size"])
    p.add_argument("--mlflow-uri", default="http://localhost:5000", help="MLflow tracking URI")
    p.add_argument("--experiment", default="meeting-agent-finetune", help="MLflow experiment name")
    p.add_argument("--search", action="store_true", help="Run Optuna hyperparameter search")
    return p.parse_args()


def build_model_and_tokenizer(model_name: str, rank: int, max_seq_length: int):
    """Load 4-bit quantized base model + LoRA adapters via Unsloth."""
    from unsloth import FastLanguageModel  # type: ignore

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_name,
        max_seq_length=max_seq_length,
        dtype=None,        # auto-detect (bfloat16 on Ampere+, float16 otherwise)
        load_in_4bit=True,
    )

    model = FastLanguageModel.get_peft_model(
        model,
        r=rank,
        target_modules=DEFAULTS["target_modules"],
        lora_alpha=DEFAULTS["lora_alpha"],
        lora_dropout=DEFAULTS["lora_dropout"],
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=DEFAULTS["seed"],
    )
    return model, tokenizer


def formatting_fn(examples, tokenizer):
    """Format instruction/input/output into the chat template."""
    texts = []
    for instruction, inp, output in zip(
        examples["instruction"], examples["input"], examples["output"]
    ):
        messages = [
            {"role": "system", "content": instruction},
            {"role": "user",   "content": inp},
            {"role": "assistant", "content": output},
        ]
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
        texts.append(text)
    return {"text": texts}


def train(args, hparams: dict | None = None):
    """Run one training job and return eval metrics."""
    from trl import SFTTrainer, SFTConfig  # type: ignore
    from train.dataset import build_dataset, train_val_split

    hp = {**DEFAULTS, **(hparams or {})}

    # ── MLflow setup ──────────────────────────────────────────────────────────
    import mlflow  # type: ignore
    mlflow.set_tracking_uri(args.mlflow_uri)
    mlflow.set_experiment(args.experiment)

    with mlflow.start_run() as run:
        mlflow.log_params({
            "model_name": hp["model_name"],
            "lora_rank": hp.get("lora_rank", args.rank),
            "learning_rate": hp.get("learning_rate", args.lr),
            "epochs": args.epochs,
            "batch_size": hp.get("batch_size", args.batch_size),
            "data_files": args.data,
        })

        # ── Data ──────────────────────────────────────────────────────────────
        dataset = build_dataset(args.data)
        train_ds, val_ds = train_val_split(dataset)
        log.info("Train: %d samples | Val: %d samples", len(train_ds), len(val_ds))

        # ── Model ─────────────────────────────────────────────────────────────
        model, tokenizer = build_model_and_tokenizer(
            hp["model_name"], hp.get("lora_rank", args.rank), hp["max_seq_length"]
        )

        train_ds = train_ds.map(
            lambda ex: formatting_fn(ex, tokenizer), batched=True, remove_columns=train_ds.column_names
        )
        val_ds = val_ds.map(
            lambda ex: formatting_fn(ex, tokenizer), batched=True, remove_columns=val_ds.column_names
        )

        # ── Trainer ───────────────────────────────────────────────────────────
        output_dir = Path(args.output)
        trainer = SFTTrainer(
            model=model,
            tokenizer=tokenizer,
            train_dataset=train_ds,
            eval_dataset=val_ds,
            args=SFTConfig(
                output_dir=str(output_dir),
                num_train_epochs=args.epochs,
                per_device_train_batch_size=hp.get("batch_size", args.batch_size),
                gradient_accumulation_steps=hp["grad_accumulation"],
                learning_rate=hp.get("learning_rate", args.lr),
                warmup_ratio=hp["warmup_ratio"],
                weight_decay=hp["weight_decay"],
                lr_scheduler_type=hp["lr_scheduler"],
                optim=hp["optimizer"],
                seed=hp["seed"],
                evaluation_strategy="epoch",
                save_strategy="epoch",
                load_best_model_at_end=True,
                metric_for_best_model="eval_loss",
                fp16=True,
                logging_steps=10,
                report_to="none",   # metrics go to MLflow manually below
                dataset_text_field="text",
                max_seq_length=hp["max_seq_length"],
            ),
        )

        trainer.train()

        # ── Eval ──────────────────────────────────────────────────────────────
        eval_result = trainer.evaluate()
        log.info("Eval results: %s", eval_result)
        mlflow.log_metrics({k.replace("/", "_"): v for k, v in eval_result.items()})

        # ── Save + convert to GGUF ────────────────────────────────────────────
        model.save_pretrained(str(output_dir / "adapter"))
        tokenizer.save_pretrained(str(output_dir / "adapter"))
        log.info("Adapter saved to %s", output_dir / "adapter")

        # Convert to GGUF Q4_K_M for Ollama deployment
        try:
            from unsloth import FastLanguageModel  # type: ignore
            model.save_pretrained_gguf(
                str(output_dir / "gguf"),
                tokenizer,
                quantization_method="q4_k_m",
            )
            log.info("GGUF model saved to %s", output_dir / "gguf")
            mlflow.log_artifact(str(output_dir / "gguf"))
        except Exception as exc:
            log.warning("GGUF export failed (optional): %s", exc)

        # ── Log model to MLflow registry ──────────────────────────────────────
        mlflow.peft.log_model(
            model,
            artifact_path="model",
            registered_model_name="meeting-agent-qwen",
        )
        log.info("Model logged to MLflow run %s", run.info.run_id)

        return eval_result


def optuna_search(args):
    """Run Optuna hyperparameter search over LoRA rank and learning rate."""
    import optuna  # type: ignore

    def objective(trial):
        hparams = {
            "lora_rank": trial.suggest_categorical("lora_rank", [8, 16, 32]),
            "learning_rate": trial.suggest_float("learning_rate", 1e-5, 5e-4, log=True),
            "batch_size": trial.suggest_categorical("batch_size", [1, 2, 4]),
        }
        result = train(args, hparams=hparams)
        return result.get("eval_loss", float("inf"))

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=DEFAULTS["optuna_trials"])
    log.info("Best params: %s", study.best_params)
    log.info("Best eval_loss: %.4f", study.best_value)
    return study.best_params


if __name__ == "__main__":
    args = parse_args()
    if args.search:
        best = optuna_search(args)
        log.info("Re-training with best params: %s", best)
        train(args, hparams=best)
    else:
        train(args)
