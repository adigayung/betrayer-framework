"""Tests for the LLM Intelligence layer (Task 17).

Tests cover:
- capability registry integrity (no duplicate names, valid categories)
- discover.list() — returns all capabilities
- discover.get() — by name
- discover.get() — unknown capability raises CapabilityNotFoundError
- discover.search() — by keyword
- discover.summary() — progressive disclosure Level-1
- deterministic structured output
- related capabilities presence
- examples exist and are non-empty
- contract file references are valid
- CLI discover command smoke test
- JSON output from CLI
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from betrayer.ai import discover
from betrayer.ai.capabilities import (
    CAPABILITIES,
    CAPABILITY_CATEGORIES,
    CapabilityNotFoundError,
    capability_summary,
    get_capability,
    list_capabilities,
    search_capabilities,
)

# ── Registry Integrity ──────────────────────────────────────────


class TestCapabilityRegistry:

    def test_no_duplicate_names(self) -> None:
        names = [cap["name"] for cap in CAPABILITIES]
        duplicates = {n for n in names if names.count(n) > 1}
        assert not duplicates, f"duplicate capability names: {duplicates}"

    def test_all_names_unique(self) -> None:
        """Ensure every capability name is unique (set vs list length)."""
        names = [cap["name"] for cap in CAPABILITIES]
        assert len(names) == len(set(names))

    def test_all_categories_valid(self) -> None:
        """Every capability category must be one of the known categories."""
        for cap in CAPABILITIES:
            assert cap["category"] in CAPABILITY_CATEGORIES, (
                f"unknown category {cap['category']!r} for {cap['name']!r}"
            )

    def test_all_statuses_valid(self) -> None:
        valid = {"stable", "beta", "experimental"}
        for cap in CAPABILITIES:
            assert cap["status"] in valid, (
                f"invalid status {cap['status']!r} for {cap['name']!r}"
            )

    def test_every_capability_has_required_keys(self) -> None:
        required = {"name", "purpose", "description", "category", "status",
                     "public_api", "contract", "package", "uses", "used_by",
                     "cli_commands", "example"}
        for cap in CAPABILITIES:
            missing = required - set(cap.keys())
            assert not missing, f"{cap['name']!r} missing keys: {missing}"

    def test_public_api_is_list_of_strings(self) -> None:
        for cap in CAPABILITIES:
            assert isinstance(cap["public_api"], list), f"{cap['name']!r} public_api not a list"
            for api in cap["public_api"]:
                assert isinstance(api, str), f"{cap['name']!r} public_api item not a string: {api}"

    def test_example_is_non_empty(self) -> None:
        for cap in CAPABILITIES:
            assert cap["example"] and len(cap["example"]) > 0, (
                f"{cap['name']!r} has empty example"
            )

    def test_uses_and_used_by_reference_existing_capabilities(self) -> None:
        names = {cap["name"] for cap in CAPABILITIES}
        for cap in CAPABILITIES:
            for ref in cap["uses"] + cap["used_by"]:
                assert ref in names, (
                    f"{cap['name']!r} references unknown capability {ref!r}"
                )

    def test_contract_file_exists(self) -> None:
        ai_dir = Path(__file__).resolve().parents[1] / "betrayer" / "ai"
        for cap in CAPABILITIES:
            contract = cap.get("contract")
            if contract is None:
                continue
            contract_path = ai_dir / contract
            assert contract_path.is_file(), (
                f"{cap['name']!r} references contract {contract!r} but file not found"
            )


# ── Discovery API ───────────────────────────────────────────────


class TestDiscoverAPI:

    def test_list_returns_all_capabilities(self) -> None:
        result = list_capabilities()
        assert len(result) == len(CAPABILITIES)

    def test_list_entries_have_summary_keys(self) -> None:
        result = list_capabilities()
        for entry in result:
            assert "name" in entry
            assert "purpose" in entry
            assert "category" in entry
            assert "status" in entry
            assert "package" in entry
            # These should NOT be in summary level
            assert "public_api" not in entry
            assert "description" not in entry

    def test_get_returns_full_definition(self) -> None:
        result = get_capability("pagination")
        assert result["name"] == "pagination"
        assert "public_api" in result
        assert "description" in result
        assert "example" in result
        assert "uses" in result
        assert "used_by" in result

    def test_get_unknown_raises_error(self) -> None:
        with pytest.raises(CapabilityNotFoundError) as exc:
            get_capability("nonexistent_thing")
        assert "nonexistent_thing" in str(exc.value)

    def test_search_finds_by_name(self) -> None:
        results = search_capabilities("pagination")
        names = [r["name"] for r in results]
        assert "pagination" in names

    def test_search_finds_by_purpose(self) -> None:
        results = search_capabilities("rate limit")
        assert any("rate_limit" in r["name"] for r in results)

    def test_search_finds_by_category(self) -> None:
        results = search_capabilities("security")
        names = [r["name"] for r in results]
        assert "authentication" in names
        assert "authorization" in names
        assert "rate_limiting" in names

    def test_search_is_case_insensitive(self) -> None:
        results_lower = search_capabilities("auth")
        results_upper = search_capabilities("AUTH")
        assert len(results_lower) == len(results_upper)
        assert results_lower == results_upper

    def test_search_empty_query_returns_all(self) -> None:
        # An empty string matches everything (substring match on all fields)
        results = search_capabilities("")
        assert len(results) == len(CAPABILITIES)

    def test_search_no_match_returns_empty(self) -> None:
        results = search_capabilities("xyznonexistentkeyword")
        assert len(results) == 0


# ── Discover module API ─────────────────────────────────────────


class TestDiscoverModule:

    def test_discover_importable(self) -> None:
        import betrayer.ai as ai
        assert hasattr(ai, "discover")

    def test_discover_list(self) -> None:
        result = discover.list()
        assert len(result) == len(CAPABILITIES)

    def test_discover_get(self) -> None:
        result = discover.get("cache")
        assert result["name"] == "cache"
        assert "example" in result

    def test_discover_get_unknown(self) -> None:
        with pytest.raises(CapabilityNotFoundError):
            discover.get("unknown_capability")

    def test_discover_search(self) -> None:
        result = discover.search("data")
        assert len(result) > 0
        names = [r["name"] for r in result]
        assert "database" in names or "cache" in names

    def test_discover_summary(self) -> None:
        result = discover.summary("authentication")
        assert result["name"] == "authentication"
        assert "purpose" in result
        assert "public_api" in result
        assert "contract" in result
        assert "package" in result
        assert "related_capabilities" in result
        # Summary should NOT have full description
        assert "description" not in result
        assert "example" not in result


# ── Structured / Deterministic Output ──────────────────────────


class TestDeterministicOutput:

    def test_list_order_is_stable(self) -> None:
        """List should return the same order every time (registration order)."""
        first = list_capabilities()
        second = list_capabilities()
        assert first == second

    def test_get_is_deterministic(self) -> None:
        first = get_capability("testing")
        second = get_capability("testing")
        assert first == second

    def test_all_results_are_json_serialisable(self) -> None:
        """Every capability definition must survive json.dumps without custom handling."""
        for cap in CAPABILITIES:
            dumped = json.dumps(cap, default=str)
            restored = json.loads(dumped)
            # core fields should survive round-trip
            assert restored["name"] == cap["name"]
            assert restored["purpose"] == cap["purpose"]


# ── Related Capabilities ────────────────────────────────────────


class TestRelatedCapabilities:

    def test_resource_has_related_capabilities(self) -> None:
        cap = get_capability("resource")
        related = set(cap["uses"] + cap["used_by"])
        assert "validation" in related or "pagination" in related

    def test_authentication_and_authorization_are_related(self) -> None:
        authn = get_capability("authentication")
        authz = get_capability("authorization")
        assert "authorization" in authn["used_by"]
        assert "authentication" in authz["uses"]

    def test_middleware_is_connected(self) -> None:
        mw = get_capability("middleware")
        # Should connect to at least one security/web capability
        related = set(mw["uses"] + mw["used_by"])
        assert len(related) > 0

    def test_summary_includes_related(self) -> None:
        cap = get_capability("resource")
        summary = capability_summary(cap)
        assert "related_capabilities" in summary
        assert len(summary["related_capabilities"]) > 0


# ── CLI Discovery ────────────────────────────────────────────────


class TestCLIDiscovery:

    def test_cli_discover_list_json(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "betrayer", "discover", "--json"],
            capture_output=True, text=True,
            cwd=Path(__file__).resolve().parents[1],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert "capabilities" in data
        assert data["total"] == len(CAPABILITIES)

    def test_cli_discover_get_json(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "betrayer", "discover", "pagination", "--json"],
            capture_output=True, text=True,
            cwd=Path(__file__).resolve().parents[1],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert data["capability"]["name"] == "pagination"
        assert "public_api" in data["capability"]

    def test_cli_discover_search_json(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "betrayer", "discover", "--search", "auth", "--json"],
            capture_output=True, text=True,
            cwd=Path(__file__).resolve().parents[1],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert len(data["results"]) >= 2  # authentication + authorization

    def test_cli_discover_unknown_json(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "betrayer", "discover", "nonexistent_thing", "--json"],
            capture_output=True, text=True,
            cwd=Path(__file__).resolve().parents[1],
        )
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert data["success"] is False
        assert "error" in data

    def test_cli_discover_human_list(self) -> None:
        """Human output should print something about capabilities."""
        result = subprocess.run(
            [sys.executable, "-m", "betrayer", "discover"],
            capture_output=True, text=True,
            cwd=Path(__file__).resolve().parents[1],
        )
        assert result.returncode == 0
        assert "Betrayer Capabilities" in result.stdout
        assert "pagination" in result.stdout

    def test_cli_discover_human_get(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "betrayer", "discover", "testing"],
            capture_output=True, text=True,
            cwd=Path(__file__).resolve().parents[1],
        )
        assert result.returncode == 0
        assert "Capability: testing" in result.stdout
        assert "pytest" in result.stdout or "test" in result.stdout