"""
Registry scaffolding for verifier modularization (shadow-mode phase).

This module is additive and does not change production verifier behavior.
It wraps existing field-level verifier functions behind a small registry
interface so we can validate modularization in parallel before cutover.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from . import verifier as legacy_verifier

FieldValidatorFn = Callable[[dict, str, list[str], dict], None]


@dataclass(frozen=True)
class FieldValidatorSpec:
    """Registry entry for one field validator."""

    field_name: str
    validator: FieldValidatorFn
    description: str


class FieldValidatorRegistry:
    """Ordered registry of field validators."""

    def __init__(self, specs: Iterable[FieldValidatorSpec]) -> None:
        self._specs = list(specs)
        seen: set[str] = set()
        for spec in self._specs:
            if spec.field_name in seen:
                raise ValueError(f"Duplicate field validator name: {spec.field_name!r}")
            seen.add(spec.field_name)

    def ordered_specs(self) -> list[FieldValidatorSpec]:
        """Return registry specs in deterministic execution order."""
        return list(self._specs)

    def field_names(self) -> list[str]:
        """Return ordered field names."""
        return [spec.field_name for spec in self._specs]

    def get(self, field_name: str) -> FieldValidatorSpec | None:
        """Lookup a validator by field name."""
        for spec in self._specs:
            if spec.field_name == field_name:
                return spec
        return None


def validate_vendor_via_legacy(
    extraction: dict,
    norm_raw: str,
    codes: list[str],
    provenance: dict,
) -> None:
    """Adapter wrapper for legacy vendor validator."""
    legacy_verifier._verify_vendor(extraction, norm_raw, codes, provenance)


def validate_amount_via_legacy(
    extraction: dict,
    norm_raw: str,
    codes: list[str],
    provenance: dict,
) -> None:
    """Adapter wrapper for legacy amount validator."""
    legacy_verifier._verify_amount(extraction, norm_raw, codes, provenance)


def validate_has_po_via_legacy(
    extraction: dict,
    norm_raw: str,
    codes: list[str],
    provenance: dict,
) -> None:
    """Adapter wrapper for legacy has_po validator."""
    legacy_verifier._verify_has_po(extraction, norm_raw, codes, provenance)


def build_legacy_validator_registry() -> FieldValidatorRegistry:
    """Build ordered registry backed by existing legacy validator functions."""
    return FieldValidatorRegistry(
        [
            FieldValidatorSpec(
                field_name="vendor",
                validator=validate_vendor_via_legacy,
                description="Legacy vendor grounding + value/evidence checks.",
            ),
            FieldValidatorSpec(
                field_name="amount",
                validator=validate_amount_via_legacy,
                description="Legacy amount evidence parsing and tolerance checks.",
            ),
            FieldValidatorSpec(
                field_name="has_po",
                validator=validate_has_po_via_legacy,
                description="Legacy PO grounding/pattern checks with null-tolerance branch.",
            ),
        ]
    )

