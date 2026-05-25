# Assignment Compliance Checklist

Source of truth: `Prokct.md`, converted from the original assignment PDF.

## Required Components

| Requirement | Current coverage |
| --- | --- |
| Written report, 10-15 pages PDF | `docs/final-report/` LaTeX source and `docs/final-report/MIA_System.pdf` |
| Complete runnable source code | `src/meeting_agent/`, `web/`, Dockerfiles, `docker-compose.yml`, `README.md` |
| Presentation slide deck, 10-15 slides | Still needs final slide deck export |

## Section I Coverage

| Rubric item | Evidence in repo/report |
| --- | --- |
| Business problem definition | `docs/final-report/chapter1.tex` |
| Business and technical success metrics | `docs/final-report/chapter1.tex`, `docs/final-report/chapter5.tex` |
| Development infrastructure and tooling | `README.md`, `pyproject.toml`, `Dockerfile*`, `docker-compose.yml`, `.github/workflows/ci.yml` |
| Required structure: `src/`, `data/`, `models/`, `configs/`, `tests/` | Present; `configs/app.example.yml` is loaded by runtime settings; `models/` contains a real trained baseline checkpoint plus registry paths for retraining output and promotion metadata |
| Data management and limitations | `docs/final-report/chapter3.tex`, `docs/data-pipeline.md` |
| Model selection, baseline comparison, error analysis | `docs/final-report/chapter3.tex`, `docs/final-report/chapter5.tex`, `docs/eval-results.md` |
| Deployable system | `README.md`, `docs/final-report/chapter4.tex`, `docs/public-demo-deployment.md` |
| Agentic AI component | `docs/final-report/chapter3.tex` |
| Continual learning and monitoring | `docs/final-report/chapter4.tex`, `docs/final-report/chapter7.tex`, `docs/monitoring-guide.md`, `docs/mlops-runbook.md` |
| Privacy and robustness | `docs/final-report/chapter6.tex`, tests for PII/guardrails |
| Project management and teamwork | `docs/final-report/chapter7.tex` |
| Ethics and responsible AI | `docs/final-report/chapter6.tex` |

## Remaining Manual Deliverable

Create/export the presentation deck as PDF or PPTX with 10-15 slides:

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
