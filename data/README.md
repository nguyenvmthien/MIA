# Data Directory

Runtime data, generated datasets, local audio, token files, and exported
training artifacts are intentionally excluded from Git.

Expected local layout:

```text
data/
  audio/            # uploaded and preprocessed meeting audio
  transcripts/      # transcript artifacts
  tokens/           # encrypted OAuth tokens, never commit
  training/         # generated SFT/RLHF exports
  eval/             # benchmark gold files and generated reports
```

Use the scripts in `src/meeting_agent/mlops/data_pipeline/` and `scripts/` to
regenerate synthetic, feedback, and Hugging Face export datasets. Keep raw audio
and any data containing PII outside source control.
