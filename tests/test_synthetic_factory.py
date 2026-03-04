"""
tests/test_synthetic_factory.py
Unit tests for scripts/generate_synthetic_batch.py.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from generate_synthetic_batch import (
    InvoiceGenerator,
    apply_ocr_noise,
    build_record,
    layout_email,
    layout_messy_table,
    layout_standard,
    _find_protected_spans,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REQUIRED_JSONL_KEYS = {
    "invoice_id", "file", "po_match", "expected_status",
    "expected_fields", "mock_extraction", "tags",
}

_MOCK_EXTRACTION_FIELDS = {"vendor", "amount", "has_po"}


def _make_data(
    has_po: bool = True,
    layout: str = "standard",
    status: str = "APPROVED",
) -> dict:
    """Build a minimal data dict matching InvoiceGenerator.generate() output."""
    return {
        "invoice_id": "INV-9001",
        "vendor": "Test Vendor Inc",
        "amount": 1234.56,
        "has_po": has_po,
        "po_number": "PO-55555" if has_po else None,
        "expected_status": status,
        "po_match": has_po and status == "APPROVED",
        "layout_name": layout,
        "tags": ["synthetic"],
    }


# ===========================================================================
# OCR Noise
# ===========================================================================

class TestOCRNoise:

    def test_noise_mutates_text(self):
        """Non-zero noise level changes at least some characters."""
        text = "The quick brown fox jumps over the lazy dog. 0123456789" * 5
        rng = random.Random(42)
        noisy = apply_ocr_noise(text, 0.1, rng)
        assert noisy != text

    def test_zero_noise_no_change(self):
        """noise_level=0 returns identical text."""
        text = "Hello World 123"
        rng = random.Random(42)
        assert apply_ocr_noise(text, 0.0, rng) == text

    def test_preserves_protected_spans(self):
        """Evidence regions must be unchanged after noise."""
        text = "HEADER STUFF Total: 500.00 FOOTER NOISE"
        evidence = "Total: 500.00"
        spans = _find_protected_spans(text, [evidence])
        rng = random.Random(42)
        noisy = apply_ocr_noise(text, 0.5, rng, protected_spans=spans)

        # Evidence string appears verbatim in noisy output
        # (position may shift due to insertions/deletions before it)
        assert evidence in noisy

    def test_deterministic_with_seed(self):
        """Same seed produces identical output."""
        text = "Some OCR text with numbers 12345 and letters ABCDE"
        r1 = apply_ocr_noise(text, 0.05, random.Random(99))
        r2 = apply_ocr_noise(text, 0.05, random.Random(99))
        assert r1 == r2

    def test_newlines_preserved(self):
        """Newline characters are never mutated."""
        text = "Line1\nLine2\nLine3\n"
        rng = random.Random(42)
        noisy = apply_ocr_noise(text, 0.5, rng)
        assert noisy.count("\n") == text.count("\n")


# ===========================================================================
# JSON Record Schema
# ===========================================================================

class TestJSONRecord:

    def test_record_has_required_keys(self):
        data = _make_data()
        record = build_record(data, "INV-9001.txt", {
            "vendor_ev": "Test Vendor Inc",
            "amount_ev": "Total: 1234.56",
            "po_ev": "PO Number: PO-55555",
        })
        assert _REQUIRED_JSONL_KEYS <= set(record.keys())

    def test_mock_extraction_structure(self):
        data = _make_data()
        record = build_record(data, "INV-9001.txt", {
            "vendor_ev": "Test Vendor Inc",
            "amount_ev": "Total: 1234.56",
            "po_ev": "PO Number: PO-55555",
        })
        mock = record["mock_extraction"]
        assert _MOCK_EXTRACTION_FIELDS == set(mock.keys())
        for field in _MOCK_EXTRACTION_FIELDS:
            assert "value" in mock[field]
            assert "evidence" in mock[field]

    def test_has_po_false_evidence_is_none(self):
        data = _make_data(has_po=False, status="EXCEPTION_NO_PO")
        record = build_record(data, "INV-9001.txt", {
            "vendor_ev": "Test Vendor Inc",
            "amount_ev": "Total: 1234.56",
            "po_ev": None,
        })
        assert record["mock_extraction"]["has_po"]["value"] is False
        assert record["mock_extraction"]["has_po"]["evidence"] is None

    def test_has_po_true_evidence_is_string(self):
        data = _make_data(has_po=True)
        record = build_record(data, "INV-9001.txt", {
            "vendor_ev": "Test Vendor Inc",
            "amount_ev": "Total: 1234.56",
            "po_ev": "PO Number: PO-55555",
        })
        ev = record["mock_extraction"]["has_po"]["evidence"]
        assert isinstance(ev, str)
        assert len(ev) > 0

    def test_approved_status_list(self):
        data = _make_data(status="APPROVED")
        record = build_record(data, "test.txt", {
            "vendor_ev": "X", "amount_ev": "Y", "po_ev": "Z",
        })
        assert record["expected_status"] == ["APPROVED", "PAID"]

    def test_exception_status_list(self):
        data = _make_data(has_po=False, status="EXCEPTION_NO_PO")
        record = build_record(data, "test.txt", {
            "vendor_ev": "X", "amount_ev": "Y", "po_ev": None,
        })
        assert record["expected_status"] == ["EXCEPTION_NO_PO"]


# ===========================================================================
# Layout Templates
# ===========================================================================

class TestLayouts:

    def test_standard_contains_evidence(self):
        data = _make_data(layout="standard")
        text, evidence = layout_standard(data, random.Random(42))
        assert evidence["vendor_ev"] in text
        assert evidence["amount_ev"] in text
        assert evidence["po_ev"] in text

    def test_email_contains_evidence(self):
        data = _make_data(layout="email")
        text, evidence = layout_email(data, random.Random(42))
        assert evidence["vendor_ev"] in text
        assert evidence["amount_ev"] in text
        assert evidence["po_ev"] in text

    def test_messy_table_contains_evidence(self):
        data = _make_data(layout="messy_table")
        text, evidence = layout_messy_table(data, random.Random(42))
        assert evidence["vendor_ev"] in text
        assert evidence["amount_ev"] in text
        assert evidence["po_ev"] in text

    def test_invoice_id_in_text(self):
        """Invoice ID must appear in generated text for mock dispatch."""
        data = _make_data()
        for fn in [layout_standard, layout_email, layout_messy_table]:
            text, _ = fn(data, random.Random(42))
            assert data["invoice_id"] in text, (
                f"{fn.__name__} does not contain invoice_id"
            )

    def test_no_po_layouts_omit_po(self):
        """has_po=False layouts should not mention PO."""
        data = _make_data(has_po=False, status="EXCEPTION_NO_PO")
        for fn in [layout_standard, layout_email, layout_messy_table]:
            text, evidence = fn(data, random.Random(42))
            assert evidence["po_ev"] is None
            # Text should not contain a PO reference line
            assert "PO Number:" not in text
            assert "PO#" not in text
            assert "Purchase Order" not in text


# ===========================================================================
# InvoiceGenerator
# ===========================================================================

class TestInvoiceGenerator:

    def test_generate_returns_required_keys(self):
        gen = InvoiceGenerator(random.Random(42))
        data = gen.generate("INV-9000")
        required = {
            "invoice_id", "vendor", "amount", "has_po", "po_number",
            "expected_status", "po_match", "layout_name", "tags",
        }
        assert required <= set(data.keys())

    def test_amount_range(self):
        gen = InvoiceGenerator(random.Random(42))
        for i in range(50):
            data = gen.generate(f"INV-{9000 + i:04d}")
            assert 10.0 <= data["amount"] <= 5000.0

    def test_no_po_means_exception_no_po(self):
        gen = InvoiceGenerator(random.Random(42))
        for i in range(100):
            data = gen.generate(f"INV-{8000 + i:04d}")
            if not data["has_po"]:
                assert data["expected_status"] == "EXCEPTION_NO_PO"
                assert data["po_match"] is False
                assert data["po_number"] is None
