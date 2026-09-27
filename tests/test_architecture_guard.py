"""Tests for Architecture Guard (Task 18)."""

from __future__ import annotations

import json

import pytest

from betrayer.architecture import guard
from betrayer.architecture.checker import ArchitectureChecker, ArchitectureResult
from betrayer.architecture.rules import (
    ArchitectureRule,
    ArchitectureViolation,
    RULES,
    rule_by_id,
)


# ── Basic structure ──────────────────────────────────────────────


class TestArchitectureGuardBasics:
    """Guard basic structure and API."""

    def test_guard_importable(self):
        """Architecture guard module is importable."""
        from betrayer.architecture import guard

        assert guard is not None
        assert hasattr(guard, "check")

    def test_guard_check_returns_result(self):
        """guard.check() returns an ArchitectureResult."""
        result = guard.check()
        assert isinstance(result, ArchitectureResult)
        assert hasattr(result, "to_dict")
        assert hasattr(result, "status")
        assert hasattr(result, "rules_checked")
        assert hasattr(result, "errors")
        assert hasattr(result, "warnings")
        assert hasattr(result, "violations")

    def test_result_serializable(self):
        """Result is JSON-serializable."""
        result = guard.check()
        d = result.to_dict()
        assert isinstance(d, dict)
        # Should serialize without error
        json_str = json.dumps(d, indent=2, sort_keys=True, default=str)
        assert isinstance(json_str, str)
        # Re-parse
        parsed = json.loads(json_str)
        assert "status" in parsed
        assert "rules_checked" in parsed
        assert "errors" in parsed
        assert "warnings" in parsed
        assert "violations" in parsed

    def test_rules_defined(self):
        """RULES list is populated."""
        assert len(RULES) >= 5
        for rule in RULES:
            assert rule.id.startswith("BET-ARCH-")
            assert rule.severity in ("error", "warning")
            assert rule.description
            assert callable(rule.check)

    def test_no_duplicate_rule_ids(self):
        """No two rules share the same ID."""
        ids = [r.id for r in RULES]
        assert len(ids) == len(set(ids)), f"Duplicate rule IDs: {ids}"

    def test_rule_by_id(self):
        """rule_by_id returns the correct rule."""
        first = RULES[0]
        found = rule_by_id(first.id)
        assert found is not None
        assert found.id == first.id
        assert found.description == first.description

    def test_rule_by_id_unknown(self):
        """rule_by_id returns None for unknown ID."""
        assert rule_by_id("BET-ARCH-999") is None

    def test_violation_to_dict(self):
        """Violation serialises correctly."""
        v = ArchitectureViolation(
            rule_id="TEST-001",
            severity="error",
            message="Test violation",
            location="test.py:1",
            remediation="Fix it.",
        )
        d = v.to_dict()
        assert d["rule_id"] == "TEST-001"
        assert d["severity"] == "error"
        assert d["message"] == "Test violation"
        assert d["location"] == "test.py:1"
        assert d["remediation"] == "Fix it."


# ── Rule correctness ──────────────────────────────────────────────


class TestArchitectureRules:
    """Individual rule checks."""

    def test_rule_001_core_isolation(self):
        """BET-ARCH-001: Core must not import web/Flask/Werkzeug."""
        from betrayer.architecture.rules import _check_core_isolation

        violations = _check_core_isolation()

        # Check if there are violations
        for v in violations:
            assert v.rule_id == "BET-ARCH-001"
            assert v.severity == "error"

        # In current framework, core does NOT import web/flask - this should pass
        # But let's just check the structure is correct regardless
        for v in violations:
            assert "web" in v.message.lower() or "flask" in v.message.lower() or "werkzeug" in v.message.lower()

    def test_rule_002_core_no_ai(self):
        """BET-ARCH-002: Core must not import AI layer."""
        from betrayer.architecture.rules import _check_core_no_ai

        violations = _check_core_no_ai()
        for v in violations:
            assert v.rule_id == "BET-ARCH-002"

    def test_rule_003_runtime_no_cli(self):
        """BET-ARCH-003: Runtime must not depend on CLI/diagnostics."""
        from betrayer.architecture.rules import _check_runtime_no_cli

        violations = _check_runtime_no_cli()
        for v in violations:
            assert v.rule_id == "BET-ARCH-003"
            assert v.severity == "error"

    def test_rule_004_ai_aether_isolation(self):
        """BET-ARCH-004: AI layer must not depend on AETHER."""
        from betrayer.architecture.rules import _check_ai_aether_isolation

        violations = _check_ai_aether_isolation()
        # Current framework has no AETHER dependency - should be empty
        for v in violations:
            assert v.rule_id == "BET-ARCH-004"
            assert v.severity == "error"

    def test_rule_005_infrastructure_no_web(self):
        """BET-ARCH-005: Infrastructure must not import web/Flask."""
        from betrayer.architecture.rules import _check_infrastructure_no_web

        violations = _check_infrastructure_no_web()
        for v in violations:
            assert v.rule_id == "BET-ARCH-005"
            assert v.severity == "error"

    def test_rule_009_circular_dependency(self):
        """BET-ARCH-009: No circular dependencies between layers."""
        from betrayer.architecture.rules import _check_circular_dependency

        violations = _check_circular_dependency()
        for v in violations:
            assert v.rule_id == "BET-ARCH-009"
            assert v.severity == "error"

    def test_rule_010_metadata_consistency(self):
        """BET-ARCH-010: Architecture metadata consistency."""
        from betrayer.architecture.rules import _check_architecture_metadata_consistency

        violations = _check_architecture_metadata_consistency()
        for v in violations:
            assert v.rule_id == "BET-ARCH-010"

    def test_rule_011_public_api_violations(self):
        """BET-ARCH-011: Public API symbol availability."""
        from betrayer.architecture.rules import _check_public_api_violations

        violations = _check_public_api_violations()
        for v in violations:
            assert v.rule_id == "BET-ARCH-011"


# ── Full check ────────────────────────────────────────────────────


class TestFullArchitectureCheck:
    """Full architecture guard execution."""

    def test_full_check_runs(self):
        """Full check completes without exception."""
        result = guard.check()
        assert result.rules_checked == len(RULES)

    def test_checker_deterministic(self):
        """Checker produces same results on repeated runs."""
        r1 = guard.check()
        r2 = guard.check()
        assert r1.rules_checked == r2.rules_checked
        assert r1.errors == r2.errors
        assert r1.warnings == r2.warnings
        assert r1.status == r2.status
        # Violations should have same rule_ids
        r1_ids = [v.rule_id for v in r1.violations]
        r2_ids = [v.rule_id for v in r2.violations]
        assert r1_ids == r2_ids

    def test_status_is_pass_or_fail(self):
        """Status is always 'pass' or 'fail'."""
        result = guard.check()
        assert result.status in ("pass", "fail")

    def test_full_check_known_rules(self):
        """All expected rules are checked."""
        result = guard.check()
        rule_ids = {r.id for r in RULES}
        expected = {
            "BET-ARCH-001", "BET-ARCH-002", "BET-ARCH-003",
            "BET-ARCH-004", "BET-ARCH-005", "BET-ARCH-006",
            "BET-ARCH-007", "BET-ARCH-008", "BET-ARCH-009",
            "BET-ARCH-010", "BET-ARCH-011",
        }
        assert rule_ids == expected, f"Missing rules: {expected - rule_ids}"

    def test_violations_have_remediation(self):
        """Every violation has non-empty remediation."""
        result = guard.check()
        for v in result.violations:
            assert v.remediation, f"Missing remediation for {v.rule_id}"
            assert len(v.remediation) > 5


# ── Integration ───────────────────────────────────────────────────


class TestArchitectureGuardIntegration:
    """Integration with CLI and validation."""

    def test_discoverable_via_capabilities(self):
        """Architecture guard is discoverable through capability registry."""
        from betrayer.ai.capabilities import list_capabilities, get_capability

        caps = list_capabilities()
        names = [c["name"] for c in caps]
        assert "architecture_guard" in names, "Architecture guard capability not registered"

        cap = get_capability("architecture_guard")
        assert cap["category"] == "cli"
        assert "guard.check()" in str(cap["public_api"]) or "guard" in str(cap["public_api"])

    def test_validate_includes_architecture(self):
        """bet validate --json includes architecture section."""
        from betrayer.cli.main import run_validate

        results = run_validate()
        assert "architecture" in results, "Architecture section missing from validate"
        arch = results["architecture"]
        assert arch["status"] in ("pass", "fail")
        assert arch["name"] == "architecture"
        assert arch["label"] == "architecture rules"
        assert arch["detail"] != ""

    def test_architecture_violation_structure(self):
        """Each violation in full check has complete structure."""
        result = guard.check()
        for v in result.violations:
            data = v.to_dict()
            assert "rule_id" in data
            assert "severity" in data
            assert "message" in data
            assert "location" in data
            assert "remediation" in data


# ── Baseline / Pre-existing ──────────────────────────────────────


class TestArchitectureBaseline:
    """Record current architecture baseline."""

    def test_baseline_recorded(self):
        """Record current violations for architecture baseline tracking."""
        result = guard.check()
        # Print baseline info (not an assertion, just for record)
        print(f"\nArchitecture baseline: {result.rules_checked} rules checked, "
              f"{result.errors} errors, {result.warnings} warnings, "
              f"status={result.status}")

        if result.violations:
            print("Pre-existing violations:")
            for v in result.violations:
                print(f"  [{v.rule_id}] {v.severity}: {v.message}")
                print(f"    Location: {v.location}")
                print(f"    Remediation: {v.remediation}")


class TestArchitectureRuleIds:
    """Test that rule IDs are well-formed."""

    def test_all_rule_ids_well_formed(self):
        for rule in RULES:
            parts = rule.id.split("-")
            assert len(parts) == 3, f"Rule ID {rule.id!r} should be BET-ARCH-NNN"
            assert parts[0] == "BET"
            assert parts[1] == "ARCH"
            assert parts[2].isdigit(), f"Rule ID {rule.id!r} should end with a number"

    def test_all_severities_valid(self):
        for rule in RULES:
            assert rule.severity in (
                "error",
                "warning",
            ), f"Rule {rule.id} has invalid severity: {rule.severity!r}"


class TestArchitectureCheckerEdgeCases:
    """Edge cases for the checker."""

    def test_checker_handles_empty_rules(self):
        """Checker works with no rules."""
        checker = ArchitectureChecker()
        # Temporarily replace rules
        import betrayer.architecture.rules as rules_mod
        original = list(rules_mod.RULES)
        try:
            rules_mod.RULES.clear()
            # Re-init checker
            checker2 = ArchitectureChecker()
            result = checker2.check()
            assert result.rules_checked == 0
            assert result.status == "pass"
            assert result.errors == 0
            assert result.warnings == 0
        finally:
            rules_mod.RULES.extend(original)


class TestArchitectureRulesBehaviour:
    """Test that rules don't produce false positives on known-good code."""

    def test_core_does_not_import_web(self):
        """Core isolation rule should pass on current framework."""
        from betrayer.architecture.rules import _check_core_isolation
        violations = _check_core_isolation()
        # Current framework has clean core - should have no violations
        web_violations = [v for v in violations if "web" in v.message.lower() or "flask" in v.message.lower()]
        assert len(web_violations) == 0, (
            f"Core should not import web but found {len(web_violations)} violations"
        )

    def test_ai_does_not_import_aether(self):
        """AI isolation rule should pass on current framework."""
        from betrayer.architecture.rules import _check_ai_aether_isolation
        violations = _check_ai_aether_isolation()
        assert len(violations) == 0, (
            f"AI layer should not import AETHER but found {len(violations)} violations"
        )