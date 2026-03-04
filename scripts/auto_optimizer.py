"""
scripts/auto_optimizer.py
Autonomous evaluation optimizer (Meta-Agent).

Reads eval_report.json, identifies the first failure, uses Gemini to
propose a patch to src/verifier.py, tests the patch in a Git sandbox,
and opens a Pull Request via ``gh`` if all tests pass.

Usage
-----
    # Dry run (review proposed patch, no git changes)
    python scripts/auto_optimizer.py --dry-run

    # Full run (branch, test, PR)
    python scripts/auto_optimizer.py

Prerequisites
-------------
    pip install google-genai
    export GEMINI_API_KEY="your-key-here"
    gh auth login
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import requests

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_VERIFIER_PATH = _PROJECT_ROOT / "src" / "verifier.py"
_DATASETS_DIR = _PROJECT_ROOT / "datasets"
_DEFAULT_REPORT = _PROJECT_ROOT / "eval_report.json"


# ---------------------------------------------------------------------------
# Stage 1: Triage — find the first failure
# ---------------------------------------------------------------------------

def stage_triage(report_path: Path) -> dict | None:
    """Read eval_report.json and return details of the first failing invoice.

    Returns None if there are no failures.
    """
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    for inv in report.get("per_invoice", []):
        if inv.get("failure_bucket", "pass") != "pass":
            return {
                "invoice_id": inv["invoice_id"],
                "failure_bucket": inv["failure_bucket"],
                "field_mismatches": inv.get("field_mismatches", []),
                "failure_codes": inv.get("failure_codes", []),
                "raw_text": inv.get("raw_text", ""),
                "action_plan": inv.get("action_plan", {}),
                "extraction": inv.get("extraction", {}),
            }

    return None


# ---------------------------------------------------------------------------
# Stage 2: Gemini Brain — generate a patch
# ---------------------------------------------------------------------------

def stage_gemini(failure: dict, verifier_code: str) -> str:
    """Call Gemini via direct REST API to generate a patched verifier.py.

    Uses ``requests.post`` — no Google SDK needed. Requires GOOGLE_API_KEY
    environment variable.
    """
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY environment variable is not set")

    field_list = ", ".join(failure["field_mismatches"]) or "(terminal mismatch)"
    code_list = ", ".join(failure["failure_codes"]) or "(none)"

    prompt = (
        "You are an elite Staff Python Engineer. Your task is to fix a bug "
        "in our deterministic AP extraction verifier.\n\n"
        f"The invoice text is:\n{failure['raw_text']}\n\n"
        f"It failed on the field(s): {field_list}\n"
        f"Failure codes: {code_list}\n\n"
        "The triage system suggests:\n"
        f"{json.dumps(failure['action_plan'], indent=2)}\n\n"
        "Here is the current source code of `src/verifier.py`:\n"
        f"{verifier_code}\n\n"
        "Rewrite `src/verifier.py` to handle this edge case. "
        "Return ONLY the raw, complete Python code. "
        "Do not wrap it in markdown formatting or backticks. "
        "It must be valid Python."
    )

    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/gemini-3.1-pro-preview:generateContent?key={api_key}"
    )
    headers = {"Content-Type": "application/json"}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    print("[Stage 2] Calling Gemini API (direct REST) ...")
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    result = response.json()

    if response.status_code != 200:
        print(f"ERROR: Gemini API returned {response.status_code}: {result}")
        sys.exit(1)

    raw_code = result["candidates"][0]["content"]["parts"][0]["text"]
    return _strip_markdown_fences(raw_code)


def _strip_markdown_fences(code: str) -> str:
    """Strip markdown code fences (```python ... ```) from LLM output."""
    code = code.strip()
    if code.startswith("```python"):
        code = code[len("```python"):]
    elif code.startswith("```"):
        code = code[3:]
    if code.endswith("```"):
        code = code[:-3]
    return code.strip()


# ---------------------------------------------------------------------------
# Stage 3: Git Crucible — branch, write, test
# ---------------------------------------------------------------------------

def stage_crucible(
    invoice_id: str,
    patched_code: str,
    original_branch: str,
) -> tuple[bool, str, str]:
    """Create a branch, write the patch, run the test suite.

    Returns (tests_passed, branch_name, test_output).
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    branch = f"auto-patch-{invoice_id}-{timestamp}"

    print(f"[Stage 3] Creating branch: {branch}")
    subprocess.run(
        ["git", "checkout", "-b", branch],
        check=True, cwd=str(_PROJECT_ROOT),
    )

    print(f"[Stage 3] Writing patched src/verifier.py ...")
    _VERIFIER_PATH.write_text(patched_code, encoding="utf-8")

    print(f"[Stage 3] Running test suite ...")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q"],
        capture_output=True, text=True, cwd=str(_PROJECT_ROOT),
    )

    print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
    if result.stderr:
        print(result.stderr[-300:] if len(result.stderr) > 300 else result.stderr)

    return result.returncode == 0, branch, result.stdout


# ---------------------------------------------------------------------------
# Stage 4: Delivery — PR or rollback
# ---------------------------------------------------------------------------

def stage_delivery(
    success: bool,
    branch: str,
    invoice_id: str,
    original_branch: str,
) -> None:
    """If tests pass: commit, push, PR. Otherwise: rollback."""
    run = lambda cmd: subprocess.run(
        cmd, check=True, cwd=str(_PROJECT_ROOT),
    )

    if not success:
        print(f"\n[Stage 4] FAILED — rolling back ...")
        run(["git", "reset", "--hard"])
        run(["git", "checkout", original_branch])
        run(["git", "branch", "-D", branch])
        print(f"  Patch for {invoice_id} did not pass tests. Branch deleted.")
    else:
        print(f"\n[Stage 4] SUCCESS — committing and opening PR ...")
        run(["git", "add", "src/verifier.py"])
        run(["git", "commit", "-m",
             f"Auto-Optimization: Patch verifier logic for {invoice_id}"])
        run(["git", "push", "-u", "origin", branch])
        run(["gh", "pr", "create",
             "--title", f"Auto-Patch: Fix {invoice_id}",
             "--body",
             "The evaluation harness identified a failure. "
             "The Gemini Meta-Agent successfully patched `verifier.py`. "
             "All tests pass."])
        run(["git", "checkout", original_branch])
        print(f"  PR created for {invoice_id} on branch {branch}.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Auto-optimizer meta-agent: patch verifier.py via Gemini",
    )
    parser.add_argument("--report", type=str, default=str(_DEFAULT_REPORT),
                        help="Path to eval_report.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run triage + Gemini only; skip git/PR operations")
    args = parser.parse_args()

    report_path = Path(args.report)
    if not report_path.exists():
        print(f"ERROR: Report not found: {report_path}")
        print("  Run the eval harness first: python eval_runner.py --show-failures")
        sys.exit(1)

    # Capture current branch before any git operations
    original_branch = subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        text=True, cwd=str(_PROJECT_ROOT),
    ).strip()

    # ---- Stage 1: Triage ----
    print(f"[Stage 1] Reading {report_path} ...")
    failure = stage_triage(report_path)
    if failure is None:
        print("All tests passed. Nothing to optimize.")
        sys.exit(0)

    inv_id = failure["invoice_id"]
    print(f"  Found failure: {inv_id}")
    print(f"  Bucket:        {failure['failure_bucket']}")
    print(f"  Fields:        {failure['field_mismatches']}")
    print(f"  Codes:         {failure['failure_codes']}")
    print(f"  Triage owner:  {failure['action_plan'].get('owner', 'unknown')}")

    verifier_code = _VERIFIER_PATH.read_text(encoding="utf-8")

    # ---- Stage 2: Gemini Brain ----
    patched_code = stage_gemini(failure, verifier_code)
    print(f"  Received {len(patched_code)} chars of patched code.")

    if args.dry_run:
        print(f"\n{'=' * 60}")
        print("  DRY RUN — proposed patch (not applied)")
        print(f"{'=' * 60}\n")
        print(patched_code)
        print(f"\n{'=' * 60}")
        print("  To apply, run without --dry-run")
        print(f"{'=' * 60}")
        return

    # ---- Stage 3: Git Crucible ----
    success, branch, _ = stage_crucible(inv_id, patched_code, original_branch)

    # ---- Stage 4: Delivery ----
    stage_delivery(success, branch, inv_id, original_branch)


if __name__ == "__main__":
    main()
