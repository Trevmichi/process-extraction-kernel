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

    # Full run — fix first failure (branch, test, PR)
    python scripts/auto_optimizer.py

    # Sweep mode — fix ALL failures, cap at 5
    python scripts/auto_optimizer.py --sweep --limit 5

Prerequisites
-------------
    pip install requests
    export GOOGLE_API_KEY="your-key-here"
    gh auth login
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_VERIFIER_PATH = _PROJECT_ROOT / "src" / "verifier.py"
_DATASETS_DIR = _PROJECT_ROOT / "datasets"
_DEFAULT_REPORT = _PROJECT_ROOT / "eval_report.json"
_DEFAULT_GEMINI_MODEL = "gemini-3.1-pro-preview"
_DEFAULT_CONNECT_TIMEOUT_SECS = 15.0
_DEFAULT_READ_TIMEOUT_SECS = 120.0
_DEFAULT_GEMINI_RETRIES = 2
_DEFAULT_RETRY_BACKOFF_SECS = 2.0


# ---------------------------------------------------------------------------
# Stage 1: Triage — find the first failure
# ---------------------------------------------------------------------------

def _parse_failure(inv: dict) -> dict:
    """Extract failure details from a per_invoice record."""
    return {
        "invoice_id": inv["invoice_id"],
        "failure_bucket": inv["failure_bucket"],
        "field_mismatches": inv.get("field_mismatches", []),
        "failure_codes": inv.get("failure_codes", []),
        "raw_text": inv.get("raw_text", ""),
        "action_plan": inv.get("action_plan", {}),
        "extraction": inv.get("extraction", {}),
    }


def stage_triage(report_path: Path) -> dict | None:
    """Read eval_report.json and return details of the first failing invoice.

    Returns None if there are no failures.
    """
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    for inv in report.get("per_invoice", []):
        if inv.get("failure_bucket", "pass") != "pass":
            return _parse_failure(inv)

    return None


def stage_triage_all(report_path: Path) -> list[dict]:
    """Read eval_report.json and return ALL unique failures."""
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    seen: set[str] = set()
    failures: list[dict] = []
    for inv in report.get("per_invoice", []):
        if inv.get("failure_bucket", "pass") != "pass":
            inv_id = inv["invoice_id"]
            if inv_id not in seen:
                seen.add(inv_id)
                failures.append(_parse_failure(inv))
    return failures


# ---------------------------------------------------------------------------
# Stage 2: Gemini Brain — generate a patch
# ---------------------------------------------------------------------------

def stage_gemini(
    failure: dict,
    verifier_code: str,
    model: str,
    connect_timeout_secs: float,
    read_timeout_secs: float,
    retries: int,
    retry_backoff_secs: float,
    debug_prompt_stats: bool,
) -> str:
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
    if debug_prompt_stats:
        prompt_bytes = len(prompt.encode("utf-8"))
        approx_tokens = max(1, int(round(len(prompt) / 4)))
        raw_text_chars = len(failure.get("raw_text", ""))
        triage_chars = len(json.dumps(failure.get("action_plan", {}), indent=2))
        verifier_chars = len(verifier_code)
        print("[Stage 2] Prompt stats:")
        print(
            f"  chars={len(prompt)}, bytes={prompt_bytes}, "
            f"approx_tokens={approx_tokens} (~4 chars/token)"
        )
        print(
            f"  sections: raw_text_chars={raw_text_chars}, "
            f"triage_plan_chars={triage_chars}, verifier_code_chars={verifier_chars}"
        )

    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{model}:generateContent?key={api_key}"
    )
    headers = {"Content-Type": "application/json"}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    attempt_count = retries + 1
    last_error: Exception | None = None
    attempts_made = 0
    for attempt in range(1, attempt_count + 1):
        attempts_made = attempt
        t0 = datetime.now()
        print(
            f"[Stage 2] Calling Gemini API (direct REST) "
            f"(attempt {attempt}/{attempt_count}, model={model}, "
            f"connect_timeout={connect_timeout_secs}s, read_timeout={read_timeout_secs}s) "
            f"... [{t0:%H:%M:%S}]"
        )
        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=(connect_timeout_secs, read_timeout_secs),
            )
            response.raise_for_status()
            t1 = datetime.now()
            print(f"[Stage 2] Response received [{t1:%H:%M:%S}] ({(t1-t0).seconds}s)")
            result = response.json()
            raw_code = result["candidates"][0]["content"]["parts"][0]["text"]
            return _strip_markdown_fences(raw_code)
        except requests.exceptions.HTTPError as exc:
            last_error = exc
            status_code = exc.response.status_code if exc.response is not None else None
            body_preview = ""
            if exc.response is not None and exc.response.text:
                body_preview = exc.response.text.strip().replace("\n", " ")
                if len(body_preview) > 220:
                    body_preview = body_preview[:220] + "..."
            t1 = datetime.now()
            print(
                f"[Stage 2] HTTP error [{t1:%H:%M:%S}] ({(t1-t0).seconds}s): "
                f"status={status_code}; body={body_preview or '(empty)'}"
            )
            # Retry only transient HTTP statuses.
            if status_code in {429, 500, 502, 503, 504} and attempt < attempt_count:
                sleep_secs = retry_backoff_secs * attempt
                print(f"[Stage 2] Retrying in {sleep_secs:.1f}s ...")
                time.sleep(sleep_secs)
                continue
            break
        except requests.exceptions.RequestException as exc:
            last_error = exc
            t1 = datetime.now()
            print(
                f"[Stage 2] Request error [{t1:%H:%M:%S}] ({(t1-t0).seconds}s): "
                f"{type(exc).__name__}: {exc}"
            )
            if attempt < attempt_count:
                sleep_secs = retry_backoff_secs * attempt
                print(f"[Stage 2] Retrying in {sleep_secs:.1f}s ...")
                time.sleep(sleep_secs)
                continue
            break

    raise RuntimeError(
        "Gemini call failed after "
        f"{attempts_made} attempt(s); "
        "adjust --gemini-connect-timeout/--gemini-read-timeout or verify network/API key."
    ) from last_error


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

    t0 = datetime.now()
    print(f"[Stage 3] Running test suite (60s timeout) ... [{t0:%H:%M:%S}]")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q"],
            capture_output=True, text=True, cwd=str(_PROJECT_ROOT),
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        t1 = datetime.now()
        print(f"  TIMEOUT: Tests exceeded 60 seconds [{t1:%H:%M:%S}] — marking as failed.")
        return False, branch, "TIMEOUT"

    t1 = datetime.now()
    print(f"[Stage 3] Tests finished [{t1:%H:%M:%S}] ({(t1-t0).seconds}s)")
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
             "--head", branch,
             "--base", original_branch,
             "--fill"])
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
    parser.add_argument("--sweep", action="store_true",
                        help="Process ALL failures instead of just the first")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max number of failures to process in sweep mode (0 = no limit)")
    parser.add_argument("--gemini-model", type=str, default=_DEFAULT_GEMINI_MODEL,
                        help="Gemini model id for Stage 2 generateContent call")
    parser.add_argument("--gemini-connect-timeout", type=float, default=_DEFAULT_CONNECT_TIMEOUT_SECS,
                        help="Gemini HTTP connect timeout in seconds")
    parser.add_argument("--gemini-read-timeout", type=float, default=_DEFAULT_READ_TIMEOUT_SECS,
                        help="Gemini HTTP read timeout in seconds")
    parser.add_argument("--gemini-retries", type=int, default=_DEFAULT_GEMINI_RETRIES,
                        help="Retry count for Stage 2 transient failures")
    parser.add_argument("--gemini-retry-backoff", type=float, default=_DEFAULT_RETRY_BACKOFF_SECS,
                        help="Linear backoff base seconds between Stage 2 retries")
    parser.add_argument("--gemini-debug-prompt-stats", action="store_true",
                        help="Print Stage 2 prompt size stats before calling Gemini")
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

    if args.sweep:
        failures = stage_triage_all(report_path)
        if not failures:
            print("All tests passed. Nothing to optimize.")
            sys.exit(0)
        if args.limit > 0:
            failures = failures[:args.limit]
        print(f"  Sweep mode: {len(failures)} failure(s) to process")
    else:
        failure = stage_triage(report_path)
        if failure is None:
            print("All tests passed. Nothing to optimize.")
            sys.exit(0)
        failures = [failure]

    # ---- Process each failure ----
    results: list[dict] = []
    for i, failure in enumerate(failures, 1):
        inv_id = failure["invoice_id"]
        print(f"\n{'=' * 60}")
        print(f"  [{i}/{len(failures)}] Processing {inv_id}")
        print(f"{'=' * 60}")
        print(f"  Bucket:        {failure['failure_bucket']}")
        print(f"  Fields:        {failure['field_mismatches']}")
        print(f"  Codes:         {failure['failure_codes']}")
        print(f"  Triage owner:  {failure['action_plan'].get('owner', 'unknown')}")

        # Always read fresh verifier code (previous patch may have changed it)
        verifier_code = _VERIFIER_PATH.read_text(encoding="utf-8")

        # ---- Stage 2: Gemini Brain ----
        patched_code = stage_gemini(
            failure,
            verifier_code,
            model=args.gemini_model,
            connect_timeout_secs=args.gemini_connect_timeout,
            read_timeout_secs=args.gemini_read_timeout,
            retries=max(0, args.gemini_retries),
            retry_backoff_secs=max(0.0, args.gemini_retry_backoff),
            debug_prompt_stats=args.gemini_debug_prompt_stats,
        )
        print(f"  Received {len(patched_code)} chars of patched code.")

        if args.dry_run:
            print(f"\n  DRY RUN — proposed patch for {inv_id} (not applied)")
            print(patched_code[:500])
            if len(patched_code) > 500:
                print(f"  ... ({len(patched_code) - 500} more chars)")
            results.append({"invoice_id": inv_id, "status": "dry_run"})
            continue

        # ---- Stage 3: Git Crucible ----
        success, branch, _ = stage_crucible(inv_id, patched_code, original_branch)

        # ---- Stage 4: Delivery ----
        stage_delivery(success, branch, inv_id, original_branch)
        results.append({
            "invoice_id": inv_id,
            "status": "pr_created" if success else "failed",
            "branch": branch if success else None,
        })

    # ---- Summary ----
    if len(results) > 1:
        print(f"\n{'=' * 60}")
        print("  SWEEP SUMMARY")
        print(f"{'=' * 60}")
        for r in results:
            print(f"  {r['invoice_id']}: {r['status']}")
        passed = sum(1 for r in results if r["status"] == "pr_created")
        print(f"\n  {passed}/{len(results)} patches succeeded.")


if __name__ == "__main__":
    main()
