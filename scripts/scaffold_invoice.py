"""
scripts/scaffold_invoice.py
Generate a new test case stub: invoice text template + JSONL metadata record.

Usage
-----
    python scripts/scaffold_invoice.py \\
        --id INV-1051 --vendor "Acme Corp" --amount 450.00 \\
        --has-po true --tags happy_path,table_like \\
        --expected-status APPROVED
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Ensure project root is importable
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

_INVOICES_DIR = _project_root / "datasets" / "gold_invoices"
_EXPECTED_PATH = _project_root / "datasets" / "expected.jsonl"

_ID_RE = re.compile(r"^(INV|NR|TG|GLC|APX)-\d{4}$")
_FILE_NUM_RE = re.compile(r"inv_(\d+)\.txt$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_file_number() -> int:
    """Scan existing inv_*.txt for the highest N, return N+1."""
    nums: list[int] = []
    for p in _INVOICES_DIR.glob("inv_*.txt"):
        m = _FILE_NUM_RE.search(p.name)
        if m:
            nums.append(int(m.group(1)))
    return max(nums) + 1 if nums else 1


def _existing_ids() -> set[str]:
    """Return the set of invoice_id values already in expected.jsonl."""
    ids: set[str] = set()
    if not _EXPECTED_PATH.exists():
        return ids
    for line in _EXPECTED_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ids.add(json.loads(line)["invoice_id"])
        except (json.JSONDecodeError, KeyError):
            pass
    return ids


def _infer_po_match(status: str, has_po: bool) -> bool:
    if status in ("EXCEPTION_NO_PO", "EXCEPTION_MATCH_FAILED"):
        return False
    return has_po


def _status_list(status: str) -> list[str]:
    if status == "APPROVED":
        return ["APPROVED", "PAID"]
    return [status]


def _auto_po_number(invoice_id: str) -> str:
    """Derive a PO number from the invoice ID numeric part."""
    num = re.search(r"\d+", invoice_id)
    return f"PO-{num.group()}" if num else "PO-00000"


# ---------------------------------------------------------------------------
# Template generation
# ---------------------------------------------------------------------------

def generate_invoice_text(
    invoice_id: str,
    vendor: str,
    amount: float,
    has_po: bool,
    po_number: str | None,
) -> str:
    """Return the invoice text template string."""
    lines = [
        vendor,
        "123 Business Rd, Suite 100",
        "",
        "Date: 2026-06-01",
        f"Invoice Number: {invoice_id}",
    ]

    if has_po and po_number:
        lines.append(f"PO Number: {po_number}")
    else:
        lines.append("N/A")

    lines += [
        "",
        "Description: [TODO: Add line items]",
        "",
        f"Total Amount Due: {amount:.2f}",
    ]

    return "\n".join(lines) + "\n"


def build_jsonl_record(
    invoice_id: str,
    filename: str,
    vendor: str,
    amount: float,
    has_po: bool,
    po_number: str | None,
    status: str,
    tags: list[str],
) -> dict:
    """Build the gold record dict for expected.jsonl."""
    if has_po and po_number:
        po_evidence = f"PO Number: {po_number}"
    else:
        po_evidence = "N/A"

    return {
        "invoice_id": invoice_id,
        "file": filename,
        "po_match": _infer_po_match(status, has_po),
        "expected_status": _status_list(status),
        "expected_fields": {
            "vendor": vendor,
            "amount": amount,
            "has_po": has_po,
        },
        "mock_extraction": {
            "vendor": {"value": vendor, "evidence": vendor},
            "amount": {"value": amount, "evidence": f"Total Amount Due: {amount:.2f}"},
            "has_po": {"value": has_po, "evidence": po_evidence},
        },
        "tags": tags,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_bool(value: str) -> bool:
    if value.lower() in ("true", "1", "yes"):
        return True
    if value.lower() in ("false", "0", "no"):
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean: {value!r}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scaffold a new invoice test case stub",
    )
    parser.add_argument("--id", required=True, help="Invoice ID (e.g. INV-1051)")
    parser.add_argument("--vendor", required=True, help="Vendor name")
    parser.add_argument("--amount", required=True, type=float, help="Invoice amount")
    parser.add_argument("--has-po", type=_parse_bool, default=True,
                        help="Has purchase order (true/false, default: true)")
    parser.add_argument("--tags", type=str, default="",
                        help="Comma-separated tags (e.g. happy_path,table_like)")
    parser.add_argument("--expected-status", type=str, default="APPROVED",
                        help="Expected terminal status (default: APPROVED)")
    parser.add_argument("--po-number", type=str, default=None,
                        help="PO number (auto-generated if not specified)")
    args = parser.parse_args()

    # --- Validate ---
    if not _ID_RE.match(args.id):
        print(f"ERROR: --id must match (INV|NR|TG|GLC|APX)-NNNN, got {args.id!r}",
              file=sys.stderr)
        sys.exit(1)

    if args.id in _existing_ids():
        print(f"ERROR: Invoice ID {args.id!r} already exists in {_EXPECTED_PATH}",
              file=sys.stderr)
        sys.exit(1)

    if args.amount <= 0:
        print(f"ERROR: --amount must be positive, got {args.amount}", file=sys.stderr)
        sys.exit(1)

    if args.expected_status == "EXCEPTION_NO_PO" and args.has_po:
        print("ERROR: --expected-status EXCEPTION_NO_PO requires --has-po false",
              file=sys.stderr)
        sys.exit(1)

    if not args.has_po and args.po_number:
        print("ERROR: --po-number cannot be set when --has-po is false",
              file=sys.stderr)
        sys.exit(1)

    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []

    po_number: str | None = None
    if args.has_po:
        po_number = args.po_number or _auto_po_number(args.id)

    # --- Step A: Create invoice text file ---
    file_num = _next_file_number()
    filename = f"inv_{file_num:03d}.txt"
    txt_path = _INVOICES_DIR / filename

    if txt_path.exists():
        print(f"ERROR: {txt_path} already exists", file=sys.stderr)
        sys.exit(1)

    text = generate_invoice_text(
        invoice_id=args.id,
        vendor=args.vendor,
        amount=args.amount,
        has_po=args.has_po,
        po_number=po_number,
    )
    txt_path.write_text(text, encoding="utf-8")
    print(f"Created {txt_path}")

    # --- Step B: Append JSONL record ---
    record = build_jsonl_record(
        invoice_id=args.id,
        filename=filename,
        vendor=args.vendor,
        amount=args.amount,
        has_po=args.has_po,
        po_number=po_number,
        status=args.expected_status,
        tags=tags,
    )
    with open(_EXPECTED_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Appended record to {_EXPECTED_PATH}")

    # --- Step C: Instructions ---
    print(f"\nNext steps:")
    print(f"  1. Edit {txt_path} with realistic invoice content")
    print(f"  2. Update evidence strings in expected.jsonl to match edited text")
    print(f"  3. Validate: python -m pytest tests/test_eval_harness.py::TestEvidenceGrounding -v")


if __name__ == "__main__":
    main()
