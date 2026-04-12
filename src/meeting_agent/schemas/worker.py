"""Worker and WorkerRoster schemas."""

from pydantic import BaseModel, Field


class Worker(BaseModel):
    worker_id: str = Field(description="Unique identifier for the worker")
    name: str = Field(description="Full display name")
    aliases: list[str] = Field(
        default_factory=list,
        description="Alternative names / nicknames (e.g. 'Bob' for 'Robert Kim')",
    )
    role: str | None = Field(default=None, description="Job role or title")
    email: str | None = Field(default=None, description="Contact email for notifications")
    skills: list[str] = Field(
        default_factory=list,
        description="Skill tags used for fuzzy assignment fallback",
    )

    def all_names(self) -> list[str]:
        """Return name + all aliases, lowercased for matching."""
        return [self.name.lower()] + [a.lower() for a in self.aliases]


class WorkerRoster(BaseModel):
    workers: list[Worker] = Field(default_factory=list)

    def find_by_name(self, name: str) -> Worker | None:
        """Exact or alias match, case-insensitive."""
        target = name.strip().lower()
        for worker in self.workers:
            if target in worker.all_names():
                return worker
        return None

    def names_for_prompt(self) -> str:
        """Compact representation injected into the LLM prompt."""
        lines = []
        for w in self.workers:
            aliases = f" (aka {', '.join(w.aliases)})" if w.aliases else ""
            role = f" [{w.role}]" if w.role else ""
            lines.append(f"- {w.name}{aliases}{role}")
        return "\n".join(lines)
