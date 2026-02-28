from __future__ import annotations
import re
from typing import List, Tuple, Dict, Optional
from .models import ProcessDoc, Node, Edge, Action, Decision, Evidence

VERB_ACTIONS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\b(receive|received)\b", re.I), "RECEIVE_MESSAGE"),
    (re.compile(r"\benter|entered|key(?:ed)?\s+in\b", re.I), "ENTER_RECORD"),
    (re.compile(r"\bvalidate|validates|validated\b", re.I), "VALIDATE_FIELDS"),
    (re.compile(r"\bmatch|matching\b", re.I), "MATCH_3_WAY"),
    (re.compile(r"\broute|routes|routing\b", re.I), "ROUTE_FOR_REVIEW"),
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

    # Generic conditional
    if re.search(r"\bif\b|\bunless\b|\bwhen\b", s, re.I):
        m2 = re.search(r"\bif\b(.+?)(,|then|$)", s, re.I)
        expr = m2.group(1).strip() if m2 else None
        return Decision(type="IF_CONDITION", expression=expr)

    return None

def _actions_from_sentence(s: str) -> List[str]:
    acts: List[str] = []
    for pat, act in VERB_ACTIONS:
        if pat.search(s):
            acts.append(act)
    # De-dupe while preserving order
    seen = set()
    out: List[str] = []
    for a in acts:
        if a not in seen:
            out.append(a)
            seen.add(a)
    return out

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

    for s in sentences:
        s_clean = s.strip()

        decision = _detect_gateway(s_clean)
        if decision is not None:
            gid = f"n{next_num}"; next_num += 1
            nodes.append(Node(
                id=gid,
                kind="gateway",
                name="Decision",
                decision=decision,
                evidence=ev(s_clean),
                meta={"canonical_key": f"gw:{decision.type}"},
            ))
            edges.append(Edge(frm=cur_id, to=gid))
            cur_id = gid
            unknowns.append({
                "id": f"auto_u{len(unknowns)+1}",
                "type": "missing_path",
                "question": f"Decision detected but branches not fully modeled: '{s_clean}' — what are the explicit outcomes and next steps?",
                "priority": "high",
            })
            continue

        # If approver authority mentioned but no digits anywhere in sentence, ask for missing threshold/rule
        if APPROVER_WORDS.search(s_clean) and re.search(r"\bapproval\b|\bapprove\b|\brequire(s|d)?\b|\bmust\b", s_clean, re.I):
            if not any(ch.isdigit() for ch in s_clean):
                q = f"Approval authority mentioned without explicit threshold/criteria: '{s_clean}' — what is the dollar threshold or rule that triggers this approver?"
                existing = set(u.get("question","") for u in (unknowns or []))
                if q not in existing:
                    unknowns.append({"id": f"auto_u{len(unknowns)+1}", "type": "missing_rule", "question": q, "priority": "high"})

        acts = _actions_from_sentence(s_clean)
        if acts:
            for act in acts:
                task_key = f"task:{act}"
                if task_key == last_task_key:
                    continue
                tid = f"n{next_num}"; next_num += 1
                nodes.append(Node(
                    id=tid,
                    kind="task",
                    name=s_clean[:60] + ("..." if len(s_clean) > 60 else ""),
                    action=Action(type=act, actor_id=_guess_actor(act), artifact_id=_guess_artifact(act)),
                    evidence=ev(s_clean),
                    meta={"canonical_key": task_key},
                ))
                edges.append(Edge(frm=cur_id, to=tid))
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

    return ProcessDoc(
        meta=meta,
        actors=actors,
        artifacts=artifacts,
        nodes=nodes,
        edges=edges,
        unknowns=unknowns,
    )
