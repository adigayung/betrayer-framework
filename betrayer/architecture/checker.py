"""Architecture checker — runs all rules and produces structured result."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from betrayer.architecture.rules import (
    ArchitectureViolation,
    RULES,
)


# ── Result record ────────────────────────────────────────────────


@dataclass
class ArchitectureResult:
    """Structured result from running architecture guard."""

    rules_checked: int = 0
    errors: int = 0
    warnings: int = 0
    violations: list[ArchitectureViolation] = field(default_factory=list)
    status: str = "pass"  # "pass" | "fail"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "rules_checked": self.rules_checked,
            "errors": self.errors,
            "warnings": self.warnings,
            "violations": [v.to_dict() for v in self.violations],
        }


# ── Checker ──────────────────────────────────────────────────────


class ArchitectureChecker:
    """Runs all registered architecture rules and collects violations.

    Usage::

        checker = ArchitectureChecker()
        result = checker.check()
        print(result.to_dict())
    """

    def __init__(self) -> None:
        self._rules = list(RULES)

    def check(self) -> ArchitectureResult:
        """Run every registered rule and return a structured result."""
        result = ArchitectureResult()

        for rule in self._rules:
            try:
                violations = rule.check()
            except Exception as exc:
                violations = [
                    ArchitectureViolation(
                        rule_id=rule.id,
                        severity="error",
                        message=f"Rule check raised an exception: {exc}",
                        location="<checker>",
                        remediation="Fix the rule implementation.",
                    )
                ]

            for v in violations:
                result.violations.append(v)
                if v.severity == "error":
                    result.errors += 1
                elif v.severity == "warning":
                    result.warnings += 1

            result.rules_checked += 1

        if result.errors > 0:
            result.status = "fail"
        else:
            result.status = "pass"

        return result


__all__ = [
    "ArchitectureChecker",
    "ArchitectureResult",
]