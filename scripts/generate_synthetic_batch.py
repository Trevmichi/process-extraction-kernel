"""
scripts/generate_synthetic_batch.py
Procedural synthetic invoice generator with OCR noise injection.

Generates varied invoice text files paired with perfect ground-truth JSONL
records for the evaluation harness.

Usage
-----
    python scripts/generate_synthetic_batch.py --count 50 --noise-level 0.02
    python scripts/generate_synthetic_batch.py --count 10 --start-id 3000 --seed 99
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_INVOICES_DIR = _PROJECT_ROOT / "datasets" / "gold_invoices"
_EXPECTED_PATH = _PROJECT_ROOT / "datasets" / "expected.jsonl"


# ---------------------------------------------------------------------------
# OCR Chaos Injector
# ---------------------------------------------------------------------------

_OCR_SWAPS: dict[str, str] = {
    "O": "0", "0": "O",
    "l": "1", "1": "l",
    "S": "5", "5": "S",
    "B": "8", "8": "B",
    ".": ",", ",": ".",
}


def _find_protected_spans(
    text: str, evidence_strings: list[str | None],
) -> list[tuple[int, int]]:
    """Locate evidence substrings in *text* and return their (start, end) spans."""
    spans: list[tuple[int, int]] = []
    for ev in evidence_strings:
        if ev is None:
            continue
        idx = text.find(ev)
        if idx >= 0:
            spans.append((idx, idx + len(ev)))
    return spans


def apply_ocr_noise(
    text: str,
    noise_level: float,
    rng: random.Random,
    protected_spans: list[tuple[int, int]] | None = None,
) -> str:
    """Apply character-level OCR noise to *text*, skipping protected regions.

    Protected spans (evidence regions) are never mutated so that evidence
    grounding invariants hold after noise injection.
    """
    protected: set[int] = set()
    if protected_spans:
        for start, end in protected_spans:
            protected.update(range(start, end))

    result: list[str] = []
    for i, ch in enumerate(text):
        if i in protected or ch == "\n":
            result.append(ch)
            continue
        if rng.random() < noise_level:
            roll = rng.random()
            if roll < 0.6 and ch in _OCR_SWAPS:
                result.append(_OCR_SWAPS[ch])
            elif roll < 0.8:
                result.append(ch + " ")
            elif ch == " ":
                pass  # delete space
            else:
                result.append(ch)
        else:
            result.append(ch)
    return "".join(result)


# ---------------------------------------------------------------------------
# Procedural Data Engine
# ---------------------------------------------------------------------------

class InvoiceGenerator:
    """Procedurally generates invoice data dictionaries."""

    VENDORS: list[str] = [
        "Apex Maritime Logistics",
        "CloudNine Infra LLC",
        "Bob's Industrial Plumbing",
        "Pinnacle Office Solutions",
        "Redline Freight Services",
        "Emerald Bay Consulting",
        "TrueNorth Mechanical Corp",
        "SilverLeaf Paper Supplies",
        "Quantum Data Systems Inc",
        "Ironclad Safety Equipment",
        "Brightwave Telecom Ltd",
        "Harbor Point Logistics",
    ]

    PO_PREFIXES: list[str] = ["PO-", "REF-", "ORD-", "PRQ-"]

    LAYOUTS: list[str] = ["standard", "email", "messy_table"]

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng

    def generate(self, invoice_id: str) -> dict:
        """Generate a single invoice data dictionary."""
        rng = self.rng

        vendor = rng.choice(self.VENDORS)
        amount = round(rng.uniform(10.0, 5000.0), 2)
        has_po = rng.random() < 0.75
        layout_name = rng.choice(self.LAYOUTS)

        po_number: str | None = None
        if has_po:
            prefix = rng.choice(self.PO_PREFIXES)
            po_number = f"{prefix}{rng.randint(10000, 99999)}"

        # Status assignment
        if not has_po:
            expected_status = "EXCEPTION_NO_PO"
            po_match = False
        elif rng.random() < 0.15:
            expected_status = "EXCEPTION_MATCH_FAILED"
            po_match = False
        else:
            expected_status = "APPROVED"
            po_match = True

        # Tags
        tags: list[str] = ["synthetic"]
        if layout_name == "standard" and expected_status == "APPROVED":
            tags.append("happy_path")
        if layout_name == "email":
            tags.append("email_style")
        if layout_name == "messy_table":
            tags.extend(["table_like", "multiple_totals"])
        if not has_po:
            tags.append("no_po")
        if expected_status == "EXCEPTION_MATCH_FAILED":
            tags.append("match_fail")

        return {
            "invoice_id": invoice_id,
            "vendor": vendor,
            "amount": amount,
            "has_po": has_po,
            "po_number": po_number,
            "expected_status": expected_status,
            "po_match": po_match,
            "layout_name": layout_name,
            "tags": tags,
        }


# ---------------------------------------------------------------------------
# Layout Templates
# ---------------------------------------------------------------------------

_DATES = [
    "2026-01-15", "2026-02-22", "2026-03-10", "2026-04-18",
    "2026-05-05", "2026-06-30", "2026-07-14", "2026-08-21",
    "2026-09-03", "2026-10-27", "2026-11-12", "2026-12-01",
]

_ADDRESSES = [
    "742 Evergreen Terrace, Suite 200",
    "1600 Pennsylvania Ave NW",
    "350 Fifth Avenue, Floor 34",
    "One Infinite Loop, Cupertino",
    "221B Baker Street, London",
    "8000 Marina Blvd, Brisbane",
]

_ITEMS = [
    ("Office Chairs", 4, 189.00),
    ("Network Cables (100ft)", 12, 8.50),
    ("Server Rack Unit", 1, 2450.00),
    ("Toner Cartridge", 6, 42.99),
    ("USB-C Adapters", 20, 15.00),
    ("Standing Desk Converter", 2, 320.00),
    ("LED Monitor 27in", 3, 299.99),
    ("Ergonomic Keyboard", 5, 89.95),
    ("Whiteboard Markers (box)", 10, 12.50),
    ("Projector Lamp", 1, 175.00),
]


def layout_standard(data: dict, rng: random.Random) -> tuple[str, dict]:
    """Clean header, line items, clear total."""
    vendor = data["vendor"]
    invoice_id = data["invoice_id"]
    amount = data["amount"]
    has_po = data["has_po"]
    po_number = data["po_number"]

    date = rng.choice(_DATES)
    address = rng.choice(_ADDRESSES)

    lines = [
        vendor,
        address,
        "",
        f"Invoice: {invoice_id}",
        f"Date: {date}",
    ]

    if has_po:
        po_line = f"PO Number: {po_number}"
        lines.append(po_line)

    # Line items (decorative — amount is the true total)
    items = rng.sample(_ITEMS, k=min(3, len(_ITEMS)))
    lines.append("")
    lines.append("Description              Qty    Price")
    lines.append("-" * 40)
    for name, qty, price in items:
        lines.append(f"{name:<25}{qty:<7}{price:.2f}")
    lines.append("-" * 40)

    total_line = f"Total: {amount:.2f}"
    lines.append(total_line)
    lines.append("")

    text = "\n".join(lines)
    evidence = {
        "vendor_ev": vendor,
        "amount_ev": total_line,
        "po_ev": f"PO Number: {po_number}" if has_po else None,
    }
    return text, evidence


def layout_email(data: dict, rng: random.Random) -> tuple[str, dict]:
    """Email-style with buried amount."""
    vendor = data["vendor"]
    invoice_id = data["invoice_id"]
    amount = data["amount"]
    has_po = data["has_po"]
    po_number = data["po_number"]

    date = rng.choice(_DATES)

    lines = [
        f"From: {vendor}",
        "To: accounts@buyer.com",
        f"Subject: Invoice {invoice_id}",
        "",
        "Hi,",
        "",
        f"Please find attached invoice {invoice_id} dated {date}.",
    ]

    if has_po:
        po_sentence = f"This references Purchase Order {po_number}."
        lines.append(po_sentence)

    amount_line = f"The total amount due is {amount:.2f}."
    lines.extend([
        amount_line,
        "",
        "Please remit payment within 30 days.",
        "",
        "Best regards,",
        f"{vendor} Billing",
        "",
    ])

    text = "\n".join(lines)
    evidence = {
        "vendor_ev": vendor,
        "amount_ev": f"The total amount due is {amount:.2f}",
        "po_ev": f"Purchase Order {po_number}" if has_po else None,
    }
    return text, evidence


def layout_messy_table(data: dict, rng: random.Random) -> tuple[str, dict]:
    """Multiple sub-totals, confusing tax lines, final balance."""
    vendor = data["vendor"]
    invoice_id = data["invoice_id"]
    amount = data["amount"]
    has_po = data["has_po"]
    po_number = data["po_number"]

    date = rng.choice(_DATES)

    # Generate confusing sub-totals that do NOT equal the true total
    sub1 = round(rng.uniform(50.0, amount * 0.6), 2)
    sub2 = round(rng.uniform(20.0, amount * 0.3), 2)
    subtotal = round(sub1 + sub2, 2)
    tax = round(subtotal * 0.08, 2)
    shipping = round(rng.uniform(5.0, 50.0), 2)

    lines = [
        vendor,
        f"INVOICE {invoice_id} | {date}",
    ]

    if has_po:
        lines.append(f"PO# {po_number}")

    lines.extend([
        "",
        f"{'Item A':<20}{sub1:.2f}",
        f"{'Item B':<20}{sub2:.2f}",
        f"{'  Subtotal':<20}{subtotal:.2f}",
        f"{'Tax (8%)':<20}{tax:.2f}",
        f"{'Shipping':<20}{shipping:.2f}",
        "---",
        f"Final Balance Due:  {amount:.2f}",
        "",
    ])

    text = "\n".join(lines)
    evidence = {
        "vendor_ev": vendor,
        "amount_ev": f"Final Balance Due:  {amount:.2f}",
        "po_ev": f"PO# {po_number}" if has_po else None,
    }
    return text, evidence


_LAYOUT_FNS = {
    "standard": layout_standard,
    "email": layout_email,
    "messy_table": layout_messy_table,
}


# ---------------------------------------------------------------------------
# JSONL Record Builder
# ---------------------------------------------------------------------------

def build_record(data: dict, filename: str, evidence: dict) -> dict:
    """Build the gold record dict for expected.jsonl."""
    status = data["expected_status"]
    return {
        "invoice_id": data["invoice_id"],
        "file": filename,
        "po_match": data["po_match"],
        "expected_status": ["APPROVED", "PAID"] if status == "APPROVED"
                          else [status],
        "expected_fields": {
            "vendor": data["vendor"],
            "amount": data["amount"],
            "has_po": data["has_po"],
        },
        "mock_extraction": {
            "vendor": {"value": data["vendor"], "evidence": evidence["vendor_ev"]},
            "amount": {"value": data["amount"], "evidence": evidence["amount_ev"]},
            "has_po": {"value": data["has_po"], "evidence": evidence["po_ev"]},
        },
        "tags": data["tags"],
    }


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(generated: list[dict], args: argparse.Namespace) -> None:
    """Print a clean terminal summary of the generated batch."""
    total = len(generated)
    statuses: dict[str, int] = {}
    layouts: dict[str, int] = {}
    tags_count: dict[str, int] = {}

    for d in generated:
        statuses[d["expected_status"]] = statuses.get(d["expected_status"], 0) + 1
        layouts[d["layout_name"]] = layouts.get(d["layout_name"], 0) + 1
        for t in d["tags"]:
            tags_count[t] = tags_count.get(t, 0) + 1

    print(f"\n{'=' * 60}")
    print(f"  Synthetic Batch Generator — Summary")
    print(f"{'=' * 60}")
    print(f"  Generated:    {total} invoices")
    print(f"  ID range:     INV-{args.start_id:04d} .. INV-{args.start_id + total - 1:04d}")
    print(f"  Noise level:  {args.noise_level}")
    print(f"  Seed:         {args.seed}")
    print()
    print("  Status distribution:")
    for s, c in sorted(statuses.items()):
        print(f"    {s:<30} {c:>4}  ({c/total:.0%})")
    print()
    print("  Layout distribution:")
    for l, c in sorted(layouts.items()):
        print(f"    {l:<30} {c:>4}  ({c/total:.0%})")
    print()
    print("  Tag counts:")
    for t, c in sorted(tags_count.items()):
        print(f"    {t:<30} {c:>4}")
    print(f"{'=' * 60}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic invoices with OCR noise",
    )
    parser.add_argument("--count", type=int, default=50,
                        help="Number of invoices to generate (default: 50)")
    parser.add_argument("--noise-level", type=float, default=0.02,
                        help="Probability of character mutation (default: 0.02)")
    parser.add_argument("--start-id", type=int, default=2000,
                        help="Starting ID number (default: 2000)")
    parser.add_argument("--seed", type=int, default=42,
                        help="PRNG seed for reproducibility (default: 42)")
    args = parser.parse_args()

    # Validate ID range fits mock dispatch regex (4-digit IDs)
    max_id = args.start_id + args.count - 1
    if max_id > 9999:
        print(f"ERROR: start_id + count - 1 = {max_id} > 9999. "
              "Invoice IDs must be 4 digits for mock dispatch.",
              file=sys.stderr)
        sys.exit(1)
    if args.start_id < 0:
        print(f"ERROR: --start-id must be non-negative", file=sys.stderr)
        sys.exit(1)
    if args.count <= 0:
        print(f"ERROR: --count must be positive", file=sys.stderr)
        sys.exit(1)

    rng = random.Random(args.seed)
    gen = InvoiceGenerator(rng)

    _INVOICES_DIR.mkdir(parents=True, exist_ok=True)

    generated: list[dict] = []
    for i in range(args.count):
        num = args.start_id + i
        invoice_id = f"INV-{num:04d}"
        filename = f"INV-{num}.txt"

        data = gen.generate(invoice_id)

        # Add noisy_ocr tag if noise is active
        if args.noise_level > 0 and "noisy_ocr" not in data["tags"]:
            data["tags"].append("noisy_ocr")

        # Generate layout text + evidence
        layout_fn = _LAYOUT_FNS[data["layout_name"]]
        text, evidence = layout_fn(data, rng)

        # Compute protected spans from evidence strings + invoice ID
        # Invoice ID must survive noise for mock dispatch to find it.
        ev_strings = [
            evidence["vendor_ev"], evidence["amount_ev"], evidence["po_ev"],
            invoice_id,
        ]
        protected = _find_protected_spans(text, ev_strings)

        # Apply noise (evidence regions protected)
        noisy_text = apply_ocr_noise(text, args.noise_level, rng, protected)

        # Write .txt file
        txt_path = _INVOICES_DIR / filename
        txt_path.write_text(noisy_text, encoding="utf-8")

        # Build + append JSONL record
        record = build_record(data, filename, evidence)
        with open(_EXPECTED_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        generated.append(data)

    print_summary(generated, args)


if __name__ == "__main__":
    main()
