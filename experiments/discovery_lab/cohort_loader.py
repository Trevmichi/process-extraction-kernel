from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def gold_invoice_dir() -> Path:
    return repo_root() / "datasets" / "gold_invoices"


def expected_jsonl_path() -> Path:
    return repo_root() / "datasets" / "expected.jsonl"
