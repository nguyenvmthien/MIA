# Assignment Compliance Checklist

Source of truth: `Prokct.md`, converted from the original assignment PDF.

## Required Components

| Requirement | Current coverage |
| --- | --- |
| Written report, 10-15 pages PDF | Submit `report.pdf`. |
| Complete runnable source code | `src/meeting_agent/`, `web/`, Dockerfiles, `docker-compose.yml`, `README.md` |
| Presentation slide deck, 10-15 slides | Submit `slide.pdf`. |

## Section I Coverage

| Rubric item | Evidence in repo/report |
| --- | --- |
| Business problem definition | `docs/final-report/chapter1.tex` |
| Business and technical success metrics | `docs/final-report/chapter1.tex`, `docs/final-report/chapter4.tex` |
| Development infrastructure and tooling | `README.md`, `pyproject.toml`, `Dockerfile*`, `docker-compose.yml`, `.github/workflows/ci.yml` |
| Required structure: `src/`, `data/`, `models/`, `configs/`, `tests/` | Present; `configs/app.example.yml` is loaded by runtime settings; `models/` contains a real trained baseline checkpoint under `models/baseline-action-detector/`. Retraining output and promotion metadata are generated later under the ignored runtime paths documented in `models/README.md`. |
| Data management and limitations | `docs/final-report/chapter3.tex`, `docs/data-pipeline.md` |
| Model selection, baseline comparison, error analysis | `docs/final-report/chapter4.tex`, `docs/eval-results.md` |
| Deployable system | `README.md`, `docs/final-report/chapter2.tex`, `docs/public-demo-deployment.md` |
| Agentic AI component | `docs/final-report/chapter5.tex` |
| Continual learning and monitoring | `docs/final-report/chapter6.tex`, `docs/monitoring-guide.md`, `docs/mlops-runbook.md` |
| Privacy and robustness | `docs/final-report/chapter7.tex`, tests for PII/guardrails |
| Project management and teamwork | `docs/final-report/chapter8.tex` |
| Ethics and responsible AI | `docs/final-report/chapter7.tex` |

## Final Submission Files

Only these files are intended as final submitted documents:

1. `report.pdf`
2. `slide.pdf`

The slide deck should cover:

1. Title and team information
2. Business problem and motivation
3. Proposed NLP solution
4. System architecture diagram
5. Data overview
6. Model and evaluation results
7. Agentic AI component
8. Deployment overview
9. Ethics, privacy, and risks
10. Key takeaways and future work
