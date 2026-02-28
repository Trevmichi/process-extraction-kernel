from __future__ import annotations
import re
from typing import List, Tuple, Dict, Optional, TypedDict, Literal
from .models import ProcessDoc, Node, Edge, Action, Decision, Evidence
from .ontology import ActionType, DecisionType

VERB_ACTIONS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\b(receive|received)\b", re.I), "RECEIVE_MESSAGE"),
    (re.compile(r"\benter|entered|key(?:ed)?\s+in\b", re.I), "ENTER_RECORD"),
    (re.compile(r"\bvalidate|validates|validated\b", re.I), "VALIDATE_FIELDS"),
    (re.compile(r"\bmatch|matching\b", re.I), "MATCH_3_WAY"),
    (re.compile(r"\broute|routes|routing\b", re.I), "ROUTE_FOR_REVIEW"),
    (re.compile(r"\bconfirm(s|ed)?\b.*\bexpense\b", re.I), "REVIEW"),
    (re.compile(r"\b(account\s*code|gl\s*code|g/l\s*code)\b", re.I), "UPDATE_RECORD"),
    (re.compile(r"\breview|reviews\b", re.I), "REVIEW"),
    (re.compile(r"\bapprove|approved|approval\b", re.I), "APPROVE"),
    (re.compile(r"\breject|rejected|rejection\b", re.I), "REJECT"),
    (re.compile(r"\b(on hold|hold)\b", re.I), "UPDATE_STATUS"),
    (re.compile(r"\bcontact(s)?\b", re.I), "REQUEST_CLARIFICATION"),
    (re.compile(r"\bupdate(s|d)?\b", re.I), "UPDATE_RECORD"),
    (re.compile(r"\bschedule(d)?\b|\bnet\s*\d+\b", re.I), "SCHEDULE_PAYMENT"),
    (re.compile(r"\bnotify|notifies\b", re.I), "NOTIFY"),
    (re.compile(r"\bpay|paid\b", re.I), "EXECUTE_PAYMENT"),
]

APPROVER_WORDS = re.compile(r"\b(director|cfo|vp|controller|manager)\b", re.I)

_BRANCH_GW_TYPES: Dict[str, str] = {
    "approve": "APPROVE_OR_REJECT",
    "reject": "APPROVE_OR_REJECT",
    "above_tolerance": "VARIANCE_ABOVE_TOLERANCE",
    "within_tolerance": "VARIANCE_ABOVE_TOLERANCE",
}

class ParsedIntent(TypedDict, total=False):
    kind: Literal["action", "decision"]
    intent: str  # ActionType or DecisionType
    actor_id: str
    artifact_id: str
    branch_label: Optional[str]
    expression: Optional[str]
    evidence_span: str
    inputs: List[str]  # Decision.inputs (for MATCH_3_WAY)

def _split_sentences(text: str) -> List[str]:
    # Normalize wrapped lines: keep blank lines as paragraph breaks, flatten other newlines
    t = text.strip()
    t = re.sub(r"\r\n", "\n", t)
    t = re.sub(r"\n\s*\n+", "\n\n", t)
    t = t.replace("\n\n", "__PARA__")
    t = re.sub(r"\n+", " ", t)
    t = t.replace("__PARA__", ". ")
    raw = re.split(r"(?<=[\.\!\?])\s+", t)
    return [s.strip() for s in raw if s and s.strip()]

def _guess_actor(action_type: str) -> str:
    systemish = {"MATCH_3_WAY", "SCHEDULE_PAYMENT", "EXECUTE_PAYMENT", "UPDATE_STATUS", "RECEIVE_MESSAGE"}
    return "sys_erp" if action_type in systemish else "role_ap_clerk"

def _guess_artifact(action_type: str) -> str:
    if action_type in {"SCHEDULE_PAYMENT", "EXECUTE_PAYMENT"}:
        return "art_payment"
    return "art_invoice"

def _detect_gateway(s: str) -> Optional[Decision]:
    # 3-way match phrasing
    if re.search(r"\bmatches?\b.*\b(po|purchase order)\b.*\b(goods receipt|grn)\b", s, re.I):
        return Decision(type="MATCH_3_WAY", inputs=["art_invoice", "art_po", "art_grn"])

    # Robust amount threshold detection (policy-like)
    # Covers: "over $5,000", "$5,000 and above", ">=5000", ">$5000", "greater than 5000"
    m = re.search(r"(?:over|above|greater than)\s*\$?\s*([0-9][0-9,]*)", s, re.I)
    if not m:
        m = re.search(r"\$?\s*([0-9][0-9,]*)\s*(?:and\s+above|or\s+more)", s, re.I)
    if not m:
        m = re.search(r"(?:>=|>)\s*\$?\s*([0-9][0-9,]*)", s, re.I)

    if m and re.search(r"\brequire|requires|approval|approve|must\b", s, re.I):
        amt_raw = m.group(1).replace(",", "")
        return Decision(type="THRESHOLD_AMOUNT", expression=f"invoice.amount > {amt_raw}")

    # HAS_PO detector
    if re.search(r"\b(po\s+number|purchase\s+order\s+number|po#|p\.o\.)\b", s, re.I):
        if re.search(r"\b(does not have|doesn't have|without|no|missing)\b", s, re.I):
            return Decision(type="HAS_PO", expression="invoice.po_number exists")

    # VARIANCE_ABOVE_TOLERANCE detector
    if re.search(r"\b(variance|mismatch)\b", s, re.I) and re.search(r"\b(tolerance|threshold)\b", s, re.I):
        return Decision(type="VARIANCE_ABOVE_TOLERANCE")

    # APPROVE_OR_REJECT detector
    if re.search(r"\b(reject|rejected|rejects|approve|approved|approval)\b", s, re.I) and \
       re.search(r"\b(manager|approver|director|department manager)\b", s, re.I):
        return Decision(type="APPROVE_OR_REJECT")

    # Generic conditional
    if re.search(r"\bif\b|\bunless\b|\bwhen\b", s, re.I):
        m2 = re.search(r"\bif\b(.+?)(,|then|$)", s, re.I)
        expr = m2.group(1).strip() if m2 else None
        return Decision(type="IF_CONDITION", expression=expr)

    return None

def _branch_label(s: str) -> Optional[str]:
    s2 = (s or "").strip().lower()
    # approve/reject branch
    if re.search(r"\bif\s+approved\b", s2) or re.search(r"\bif\s+the\s+\w+\s+approves\b", s2) or re.search(r"\bapprove(d)?\b", s2):
        return "approve"
    if re.search(r"\bif\s+the\s+\w+\s+rejects\b", s2) or re.search(r"\bif\s+rejected\b", s2) or re.search(r"\breject(ed|s)?\b", s2):
        return "reject"

    # PO existence branch
    if re.search(r"\b(po\s+number|purchase\s+order\s+number|po#|p\.o\.)\b", s2):
        if re.search(r"\b(does not have|doesn't have|without|no|missing)\b", s2):
            return "no_po"
        if re.search(r"\b(has|with|includes|present)\b", s2):
            return "has_po"

    # tolerance branch
    if re.search(r"\b(variance|mismatch)\b", s2) and re.search(r"\b(tolerance|threshold)\b", s2):
        if re.search(r"\b(above|exceed|over)\b", s2):
            return "above_tolerance"
        if re.search(r"\b(within|below|under)\b", s2):
            return "within_tolerance"

    return None

def _is_rerun_matching_sentence(s: str) -> bool:
    s = (s or "").lower()
    return ("re-runs matching" in s) or ("reruns matching" in s) or ("re-run matching" in s) or ("rerun matching" in s)

def _actions_from_sentence(s: str, gw_type_for_sentence: Optional[str] = None, branch_label: Optional[str] = None) -> List[str]:
    is_rerun = _is_rerun_matching_sentence(s)
    _bl = (branch_label or "").lower()
    acts: List[str] = []
    for pat, act in VERB_ACTIONS:
        # If this sentence created a MATCH_3_WAY gateway, don't also emit MATCH_3_WAY task
        if gw_type_for_sentence == "MATCH_3_WAY" and act == "MATCH_3_WAY":
            continue
        # Existing rerun behavior
        if is_rerun and act == "MATCH_3_WAY":
            continue
        # Skip gateway-outcome verbs when sentence is a branch of that outcome
        if _bl == "approve" and act == "APPROVE":
            continue
        if _bl == "reject" and act == "REJECT":
            continue
        if pat.search(s):
            acts.append(act)
    # De-dupe while preserving order
    seen = set()
    out: List[str] = []
    for a in acts:
        if a not in seen:
            out.append(a)
            seen.add(a)
    # ENTER_RECORD subsumes UPDATE_RECORD when both appear in the same sentence
    if "ENTER_RECORD" in out and "UPDATE_RECORD" in out:
        out = [a for a in out if a != "UPDATE_RECORD"]
    if is_rerun:
        precedence = {"RECEIVE_MESSAGE": 0, "UPDATE_RECORD": 1}
        out.sort(key=lambda a: precedence.get(a, 99))
    return out

def _classify_sentence(s: str) -> List[ParsedIntent]:
    """Classify a sentence into a list of ParsedIntent dicts (decision first, then actions)."""
    intents: List[ParsedIntent] = []
    label = _branch_label(s)
    decision = _detect_gateway(s)
    gw_type = decision.type if decision is not None else None

    if decision is not None:
        intents.append({
            "kind": "decision",
            "intent": decision.type,
            "branch_label": label,
            "expression": decision.expression,
            "inputs": list(decision.inputs),
            "evidence_span": s,
        })

    for act in _actions_from_sentence(s, gw_type, branch_label=label):
        intents.append({
            "kind": "action",
            "intent": act,
            "actor_id": _guess_actor(act),
            "artifact_id": _guess_artifact(act),
            "branch_label": label,
            "evidence_span": s,
        })

    return intents

def heuristic_extract_ap(text: str, source_id: str, process_id: str) -> ProcessDoc:
    actors = [
        {"id": "role_ap_clerk", "type": "human_role", "name": "AP Clerk"},
        {"id": "role_manager", "type": "human_role", "name": "Department Manager"},
        {"id": "role_director", "type": "human_role", "name": "Director"},
        {"id": "sys_erp", "type": "system", "name": "ERP"},
    ]
    artifacts = [
        {"id": "art_invoice", "type": "document", "name": "Invoice"},
        {"id": "art_po", "type": "record", "name": "Purchase Order"},
        {"id": "art_grn", "type": "record", "name": "Goods Receipt"},
        {"id": "art_payment", "type": "record", "name": "Payment"},
    ]
    meta = {"process_id": process_id, "domain": "accounts_payable", "source_ids": [source_id], "version": "0.3.1"}

    sentences = _split_sentences(text)
    unknowns: List[Dict] = []
    nodes: List[Node] = []
    edges: List[Edge] = []

    def ev(span: str) -> List[Evidence]:
        return [Evidence(source_id=source_id, span=span)]

    nodes.append(Node(
        id="n1",
        kind="event",
        name="Start",
        evidence=ev(sentences[0] if sentences else "Start"),
        meta={"canonical_key": "event:start"},
    ))
    cur_id = "n1"
    next_num = 2
    last_task_key: Optional[str] = None
    last_gw_node: Optional[Node] = None

    for s in sentences:
        s_clean = s.strip()
        intents = _classify_sentence(s_clean)

        # Extract branch_label shared across all intents for this sentence
        label: Optional[str] = intents[0].get("branch_label") if intents else None
        decision_intents = [i for i in intents if i.get("kind") == "decision"]
        action_intents  = [i for i in intents if i.get("kind") == "action"]

        # Branch reuse: if this sentence is a branch of the immediately prior gateway, reuse it
        if label in _BRANCH_GW_TYPES and last_gw_node is not None and \
                last_gw_node.decision is not None and \
                last_gw_node.decision.type == _BRANCH_GW_TYPES[label]:
            last_branch_id: Optional[str] = None
            for ai in action_intents:
                act = ai["intent"]
                tid = f"n{next_num}"; next_num += 1
                nodes.append(Node(
                    id=tid,
                    kind="task",
                    name=s_clean[:60] + ("..." if len(s_clean) > 60 else ""),
                    action=Action(type=act, actor_id=ai.get("actor_id", ""), artifact_id=ai.get("artifact_id", "")),
                    evidence=ev(s_clean),
                    meta={"canonical_key": f"task:{act}"},
                ))
                if last_branch_id is None:
                    edges.append(Edge(frm=last_gw_node.id, to=tid, condition=label))
                else:
                    edges.append(Edge(frm=last_branch_id, to=tid))
                last_branch_id = tid
            cur_id = last_gw_node.id
            continue

        # Gateway creation
        for di in decision_intents:
            gid = f"n{next_num}"; next_num += 1
            gw_node = Node(
                id=gid,
                kind="gateway",
                name="Decision",
                decision=Decision(
                    type=di["intent"],
                    expression=di.get("expression"),
                    inputs=di.get("inputs", []),
                ),
                evidence=ev(s_clean),
                meta={"canonical_key": f"gw:{di['intent']}"},
            )
            nodes.append(gw_node)
            edges.append(Edge(frm=cur_id, to=gid))
            cur_id = gid
            last_gw_node = gw_node
            unknowns.append({
                "id": f"auto_u{len(unknowns)+1}",
                "type": "missing_path",
                "question": f"Decision detected but branches not fully modeled: '{s_clean}' — what are the explicit outcomes and next steps?",
                "priority": "high",
            })

        # If approver authority mentioned but no digits anywhere in sentence, ask for missing threshold/rule
        if APPROVER_WORDS.search(s_clean) and re.search(r"\bapproval\b|\bapprove\b|\brequire(s|d)?\b|\bmust\b", s_clean, re.I):
            if not any(ch.isdigit() for ch in s_clean):
                q = f"Approval authority mentioned without explicit threshold/criteria: '{s_clean}' — what is the dollar threshold or rule that triggers this approver?"
                existing = set(u.get("question","") for u in (unknowns or []))
                if q not in existing:
                    unknowns.append({"id": f"auto_u{len(unknowns)+1}", "type": "missing_rule", "question": q, "priority": "high"})

        # If this sentence both created a gateway and has a matching branch label,
        # label the first task edge as the branch condition
        _inline_cond: Optional[str] = None
        if label in _BRANCH_GW_TYPES and last_gw_node is not None and \
                last_gw_node.id == cur_id and last_gw_node.decision is not None and \
                _BRANCH_GW_TYPES[label] == last_gw_node.decision.type:
            _inline_cond = label

        if action_intents:
            _first_edge = True
            for ai in action_intents:
                act = ai["intent"]
                task_key = f"task:{act}"
                if task_key == last_task_key:
                    continue
                tid = f"n{next_num}"; next_num += 1
                nodes.append(Node(
                    id=tid,
                    kind="task",
                    name=s_clean[:60] + ("..." if len(s_clean) > 60 else ""),
                    action=Action(type=act, actor_id=ai.get("actor_id", ""), artifact_id=ai.get("artifact_id", "")),
                    evidence=ev(s_clean),
                    meta={"canonical_key": task_key},
                ))
                edges.append(Edge(frm=cur_id, to=tid, condition=_inline_cond if _first_edge else None))
                _first_edge = False
                cur_id = tid
                last_task_key = task_key
        else:
            unknowns.append({
                "id": f"auto_u{len(unknowns)+1}",
                "type": "unmapped_text",
                "question": f"Could not map sentence to an atomic action: '{s_clean}' — what action(s) should this become?",
                "priority": "medium",
            })

    end_id = f"n{next_num}"
    nodes.append(Node(
        id=end_id,
        kind="end",
        name="End",
        evidence=ev(sentences[-1] if sentences else "End"),
        meta={"canonical_key": "end:end"},
    ))
    edges.append(Edge(frm=cur_id, to=end_id))

    # Post-pass: collapse re-run-matching MATCH_3_WAY nodes into a loop back to match0
    match0: Optional[Node] = next(
        (n for n in nodes if n.kind == "task" and n.action is not None and n.action.type == "MATCH_3_WAY"),
        None,
    )
    end_node: Optional[Node] = next((n for n in nodes if n.kind == "end"), None)
    if match0 is not None:
        rerun_match_nodes = [
            n for n in nodes
            if n.kind == "task" and n.action is not None
            and n.action.type == "MATCH_3_WAY" and n is not match0
            and any(_is_rerun_matching_sentence(ev.span) for ev in n.evidence)
        ]
        rerun_ids = {n.id for n in rerun_match_nodes}

        # A) Collapse any residual rerun MATCH_3_WAY nodes (empty if suppressed upstream)
        if rerun_ids:
            for e in edges:
                if e.to in rerun_ids:
                    e.to = match0.id
            edges[:] = [e for e in edges if e.frm not in rerun_ids]
            nodes[:] = [n for n in nodes if n.id not in rerun_ids]

        # B-D) Run whenever there are UPDATE_RECORD nodes from rerun sentences
        rerun_update_nodes = [
            n for n in nodes
            if n.kind == "task" and n.action is not None
            and n.action.type == "UPDATE_RECORD"
            and any(_is_rerun_matching_sentence(ev.span) for ev in n.evidence)
        ]
        if rerun_update_nodes:
            existing_frm_to = {(e.frm, e.to) for e in edges}

            # B) Ensure loop edge to match0
            for u in rerun_update_nodes:
                if (u.id, match0.id) not in existing_frm_to:
                    edges.append(Edge(frm=u.id, to=match0.id))
                    existing_frm_to.add((u.id, match0.id))

            # C) Ensure match0 -> end edge exists
            if end_node is not None and (match0.id, end_node.id) not in existing_frm_to:
                edges.append(Edge(frm=match0.id, to=end_node.id))

            # D) Remove UPDATE_RECORD -> end edges for rerun update nodes
            if end_node is not None:
                rerun_update_ids = {n.id for n in rerun_update_nodes}
                edges[:] = [
                    e for e in edges
                    if not (e.frm in rerun_update_ids and e.to == end_node.id)
                ]

    return ProcessDoc(
        meta=meta,
        actors=actors,
        artifacts=artifacts,
        nodes=nodes,
        edges=edges,
        unknowns=unknowns,
    )
