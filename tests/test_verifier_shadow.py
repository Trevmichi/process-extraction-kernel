"""
Scaffold tests for verifier modularization shadow-mode utilities.
"""
from __future__ import annotations

import json

from src import verifier as legacy_verifier
from src.verifier_registry import (
    build_legacy_validator_registry,
    validate_amount_via_legacy,
    validate_has_po_via_legacy,
    validate_vendor_via_legacy,
)
from src.verifier_shadow import (
    compare_verifier_outputs,
    run_verifier_shadow_comparison,
)


RAW_TEXT = (
    "INVOICE #001\n"
    "Vendor: Office Supplies Co\n"
    "Total: $250.00\n"
    "PO: PO-1122"
)

VALID_EXTRACTION = {
    "vendor": {"value": "Office Supplies Co", "evidence": "Vendor: Office Supplies Co"},
    "amount": {"value": 250.00, "evidence": "Total: $250.00"},
    "has_po": {"value": True, "evidence": "PO: PO-1122"},
}


def test_registry_loads_expected_validators():
    registry = build_legacy_validator_registry()
    assert registry.field_names() == [
        "vendor",
        "amount",
        "has_po",
        "invoice_date",
        "tax_amount",
    ]
    assert registry.get("vendor") is not None
    assert registry.get("amount") is not None
    assert registry.get("has_po") is not None
    assert registry.get("invoice_date") is not None
    assert registry.get("tax_amount") is not None


def test_adapters_match_legacy_field_validator_behavior():
    norm_raw = legacy_verifier._normalize_text(RAW_TEXT)
    adapters_and_legacy = [
        (validate_vendor_via_legacy, legacy_verifier._verify_vendor),
        (validate_amount_via_legacy, legacy_verifier._verify_amount),
        (validate_has_po_via_legacy, legacy_verifier._verify_has_po),
    ]

    for adapter, legacy_fn in adapters_and_legacy:
        adapter_codes: list[str] = []
        legacy_codes: list[str] = []
        adapter_prov = legacy_verifier._default_provenance()
        legacy_prov = legacy_verifier._default_provenance()

        adapter(VALID_EXTRACTION, norm_raw, adapter_codes, adapter_prov)
        legacy_fn(VALID_EXTRACTION, norm_raw, legacy_codes, legacy_prov)

        assert adapter_codes == legacy_codes
        assert adapter_prov == legacy_prov


def test_shadow_comparison_reports_no_diff_for_controlled_example():
    report = run_verifier_shadow_comparison(RAW_TEXT, VALID_EXTRACTION)
    assert report["legacy"]["valid"] is True
    assert report["registry"]["valid"] is True
    assert report["diff"]["has_diff"] is False
    assert report["diff"]["valid_match"] is True
    assert report["diff"]["codes_match"] is True


def test_shadow_comparator_detects_intentional_mismatch():
    legacy_result = (
        True,
        [],
        {"vendor": {"grounded": True}, "amount": {}, "has_po": {}},
    )
    registry_result = (
        False,
        ["WRONG_TYPE"],
        {"vendor": {"grounded": False}, "amount": {}, "has_po": {}, "extra": {}},
    )

    diff = compare_verifier_outputs(legacy_result, registry_result)
    payload = diff.to_dict()

    assert payload["has_diff"] is True
    assert payload["valid_match"] is False
    assert payload["codes_match"] is False
    assert payload["provenance_top_level_compatible"] is False
    assert payload["provenance_top_level_only_in_registry"] == ["extra"]

    # JSON serializable for downstream tooling
    json.dumps(payload)

