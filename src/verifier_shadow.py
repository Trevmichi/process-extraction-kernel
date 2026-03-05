"""
Shadow-mode comparison utilities for verifier modularization.

This module does NOT change production behavior. It executes:
1) Legacy verifier path (source of truth)
2) Registry-backed path (scaffold)
and returns a structured diff summary for validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import verifier as legacy_verifier
from .verifier_registry import (
    FieldValidatorRegistry,
    build_legacy_validator_registry,
)


VerifierResult = tuple[bool, list[str], dict]


@dataclass(frozen=True)
class ShadowComparisonDiff:
    """Structured compatibility report for legacy vs registry outputs."""

    has_diff: bool
    valid_match: bool
    codes_match: bool
    codes_only_in_legacy: list[str]
    codes_only_in_registry: list[str]
    provenance_top_level_compatible: bool
    provenance_top_level_only_in_legacy: list[str]
    provenance_top_level_only_in_registry: list[str]
    provenance_value_mismatches: list[str]
    notes: list[str]

    def to_dict(self) -> dict:
        """Return JSON-serializable diff payload."""
        return {
            "has_diff": self.has_diff,
            "valid_match": self.valid_match,
            "codes_match": self.codes_match,
            "codes_only_in_legacy": self.codes_only_in_legacy,
            "codes_only_in_registry": self.codes_only_in_registry,
            "provenance_top_level_compatible": self.provenance_top_level_compatible,
            "provenance_top_level_only_in_legacy": self.provenance_top_level_only_in_legacy,
            "provenance_top_level_only_in_registry": self.provenance_top_level_only_in_registry,
            "provenance_value_mismatches": self.provenance_value_mismatches,
            "notes": self.notes,
        }


def _serialize_result(result: VerifierResult) -> dict[str, Any]:
    valid, codes, provenance = result
    return {
        "valid": bool(valid),
        "codes": list(codes),
        "provenance": provenance,
    }


def verify_extraction_via_registry(
    raw_text: str,
    extraction: dict,
    registry: FieldValidatorRegistry | None = None,
) -> VerifierResult:
    """Execute verifier via registry-backed field validators."""
    active_registry = registry or build_legacy_validator_registry()
    codes: list[str] = []
    provenance = legacy_verifier._default_provenance()
    norm_raw = legacy_verifier._normalize_text(raw_text)

    for spec in active_registry.ordered_specs():
        spec.validator(extraction, norm_raw, codes, provenance)

    return (len(codes) == 0, codes, provenance)


def compare_verifier_outputs(
    legacy_result: VerifierResult,
    registry_result: VerifierResult,
) -> ShadowComparisonDiff:
    """Compare legacy and registry verifier results and produce structured diff."""
    legacy_valid, legacy_codes, legacy_prov = legacy_result
    registry_valid, registry_codes, registry_prov = registry_result

    valid_match = legacy_valid == registry_valid
    codes_match = list(legacy_codes) == list(registry_codes)

    legacy_keys = set(legacy_prov.keys())
    registry_keys = set(registry_prov.keys())
    only_legacy = sorted(legacy_keys - registry_keys)
    only_registry = sorted(registry_keys - legacy_keys)
    shared_keys = sorted(legacy_keys & registry_keys)

    value_mismatches = [
        key for key in shared_keys if legacy_prov.get(key) != registry_prov.get(key)
    ]

    notes: list[str] = []
    if not valid_match:
        notes.append("valid flag differs")
    if not codes_match:
        notes.append("failure code sequence differs")
    if only_legacy or only_registry:
        notes.append("provenance top-level keys differ")
    if value_mismatches:
        notes.append("provenance values differ on shared top-level keys")

    has_diff = not (
        valid_match
        and codes_match
        and not only_legacy
        and not only_registry
        and not value_mismatches
    )

    return ShadowComparisonDiff(
        has_diff=has_diff,
        valid_match=valid_match,
        codes_match=codes_match,
        codes_only_in_legacy=[c for c in legacy_codes if c not in registry_codes],
        codes_only_in_registry=[c for c in registry_codes if c not in legacy_codes],
        provenance_top_level_compatible=(not only_legacy and not only_registry),
        provenance_top_level_only_in_legacy=only_legacy,
        provenance_top_level_only_in_registry=only_registry,
        provenance_value_mismatches=value_mismatches,
        notes=notes,
    )


def run_verifier_shadow_comparison(
    raw_text: str,
    extraction: dict,
    registry: FieldValidatorRegistry | None = None,
) -> dict[str, Any]:
    """Run legacy and registry verifier paths and return structured comparison."""
    legacy_result = legacy_verifier.verify_extraction(raw_text, extraction)
    registry_result = verify_extraction_via_registry(
        raw_text=raw_text,
        extraction=extraction,
        registry=registry,
    )
    diff = compare_verifier_outputs(legacy_result, registry_result)
    return {
        "legacy": _serialize_result(legacy_result),
        "registry": _serialize_result(registry_result),
        "diff": diff.to_dict(),
    }

