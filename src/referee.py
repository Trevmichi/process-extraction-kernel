from __future__ import annotations
from .unknown_normalize import normalize_unknowns
from typing import Dict, List, Set
from .models import ProcessDoc

def _has_action(process: ProcessDoc, action_type: str) -> bool:
    """

    Args:
      process: ProcessDoc:
      action_type: str:
      process: ProcessDoc: 
      action_type: str: 

    Returns:

    """
    for n in process.nodes:
        if n.kind == "task" and n.action and n.action.type == action_type:
            return True
    return False

def _gateway_decisions(process: ProcessDoc) -> Set[str]:
    """

    Args:
      process: ProcessDoc:
      process: ProcessDoc: 

    Returns:

    """
    out: Set[str] = set()
    for n in process.nodes:
        if n.kind == "gateway" and n.decision and n.decision.type:
            out.add(n.decision.type)
    return out

def _unknown_questions_set(process: ProcessDoc) -> Set[str]:
    """

    Args:
      process: ProcessDoc:
      process: ProcessDoc: 

    Returns:

    """
    return set(u.get("question", "") for u in (process.unknowns or []))

def referee_add_unknowns(process: ProcessDoc) -> List[Dict]:
    """Adds non-failing completeness hints as `unknowns`.
    Returns list of newly-added unknown entries.

    Args:
      process: ProcessDoc:
      process: ProcessDoc: 

    Returns:

    """
    added: List[Dict] = []
    existing_q = _unknown_questions_set(process)

    def add(q: str, utype: str = "completeness_hint", priority: str = "medium"):
        """

        Args:
          q: str:
          utype: str:  (Default value = "completeness_hint")
          priority: str:  (Default value = "medium")
          q: str: 
          utype: str:  (Default value = "completeness_hint")
          priority: str:  (Default value = "medium")

        Returns:

        """
        nonlocal added, existing_q
        if q in existing_q:
            return
        u = {
            "id": f"auto_{len(process.unknowns or []) + len(added) + 1}",
            "type": utype,
            "question": q,
            "priority": priority
        }
        added.append(u)
        existing_q.add(q)

    decisions = _gateway_decisions(process)

    # General AP hints
    if _has_action(process, "SCHEDULE_PAYMENT"):
        add("What are the payment terms (Net 30/45/60) and are there early-pay discounts?", "missing_rule", "medium")

    if _has_action(process, "MATCH_3_WAY") or "MATCH_3_WAY" in decisions or "VARIANCE_ABOVE_TOLERANCE" in decisions:
        add("What are the tolerances for quantity/price variances in matching (and who sets them)?", "missing_rule", "high")

    if _has_action(process, "APPROVE") and not _has_action(process, "REJECT"):
        add("Is there a rejection path? If rejected, how is the vendor notified and how is the invoice closed?", "missing_path", "high")

    if "HAS_PO" in decisions:
        add("If the invoice HAS a PO number, what is the standard path (2-way vs 3-way match, approvals)?", "missing_path", "high")

    if "VARIANCE_ABOVE_TOLERANCE" in decisions:
        add("If variance is within tolerance, what happens next (auto-approve, manager review, or pay hold)?", "missing_path", "high")

    if _has_action(process, "REQUEST_CLARIFICATION"):
        add("What is the escalation policy if the vendor does not respond (time limits, reminders, who owns escalation)?", "missing_rule", "medium")

    # Intake channel hint (always useful)
    add("What are the invoice intake channels (email, EDI, portal) and does intake differ by vendor?", "missing_rule", "low")

    if process.unknowns is None:
        process.unknowns = []
    process.unknowns.extend(added)
    # --- Normalized "minimum completeness" unknowns (deterministic across extractors) ---
    node_types = {n.action.type for n in (process.nodes or []) if n.action is not None}
    node_cks   = set(((n.meta or {}).get("canonical_key","")) for n in (process.nodes or []))

    # Helper: add unknown if missing (by exact question text)
    def _ensure_unknown(question: str, priority: str = "high"):
        """

        Args:
          question: str:
          priority: str:  (Default value = "high")
          question: str: 
          priority: str:  (Default value = "high")

        Returns:

        """
        qs = set(u.get("question","") for u in (process.unknowns or []))
        if question not in qs:
            (process.unknowns or []).append({
                "id": f"auto_{len(process.unknowns or []) + len(added) + 1}",
                "type": "missing_path",
                "question": question,
                "priority": priority
            })
            # do NOT append to `added` here; this is "referee normalization" not extractor output

    # If MATCH_3_WAY gateway exists, always surface the no_match path unknown
    if ("gw:MATCH_3_WAY" in node_cks) or ("MATCH_3_WAY" in node_types):
        _ensure_unknown("If 3-way match fails (no_match), what is the process (hold, vendor contact, reject, override)?")

    # If matching is present, surface match tolerance unknown (kept as a question until evidence specifies it)
    if ("gw:MATCH_3_WAY" in node_cks) or ("MATCH_3_WAY" in node_types):
        _ensure_unknown("What is the match tolerance for price/quantity variances in matching (and who sets it)?", priority="medium")

    normalize_unknowns(process)
    return added


