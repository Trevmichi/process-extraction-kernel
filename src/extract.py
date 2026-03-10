from __future__ import annotations
from .models import ProcessDoc, Node, Edge, Action, Decision, Evidence

def _base_ap_meta(source_id: str, process_id: str) -> dict:
    """

    Args:
      source_id: str:
      process_id: str:
      source_id: str: 
      process_id: str: 

    Returns:

    """
    return {"process_id": process_id, "domain": "accounts_payable", "source_ids": [source_id], "version": "0.1"}

def _base_ap_actors() -> list:
    """Return canonical AP actor definitions.

    Returns:
      list: Actor records used in manual extraction fixtures.
    """
    return [
        {"id": "role_ap_clerk", "type": "human_role", "name": "AP Clerk"},
        {"id": "role_manager", "type": "human_role", "name": "Department Manager"},
        {"id": "role_director", "type": "human_role", "name": "Director"},
        {"id": "sys_erp", "type": "system", "name": "ERP"}
    ]

def _base_ap_artifacts() -> list:
    """Return canonical AP artifact definitions.

    Returns:
      list: Artifact records used in manual extraction fixtures.
    """
    return [
        {"id": "art_invoice", "type": "document", "name": "Invoice"},
        {"id": "art_po", "type": "record", "name": "Purchase Order"},
        {"id": "art_grn", "type": "record", "name": "Goods Receipt"},
        {"id": "art_payment", "type": "record", "name": "Payment"},
        {"id": "art_account_code", "type": "field", "name": "Account Code"},
        {"id": "art_corrected_docs", "type": "document", "name": "Corrected Documents"}
    ]

def manual_extract_doc_001(text: str) -> ProcessDoc:
    """

    Args:
      text: str:
      text: str: 

    Returns:

    """
    meta = _base_ap_meta("doc_001", "ap_invoice_doc_001")
    actors = _base_ap_actors()
    artifacts = _base_ap_artifacts()

    ev = lambda s: [Evidence(source_id="doc_001", span=s)]

    nodes = [
        Node(id="n1", kind="event", name="Invoice received", evidence=ev("Invoices are received by email")),
        Node(id="n2", kind="task", name="Enter invoice in ERP",
             action=Action(type="ENTER_RECORD", actor_id="role_ap_clerk", artifact_id="art_invoice"),
             evidence=ev("entered into the ERP by the AP clerk")),
        Node(id="n3", kind="task", name="Validate invoice fields",
             action=Action(type="VALIDATE_FIELDS", actor_id="role_ap_clerk", artifact_id="art_invoice"),
             evidence=ev("validates required fields")),
        Node(id="n4", kind="gateway", name="3-way match?",
             decision=Decision(type="MATCH_3_WAY", inputs=["art_invoice","art_po","art_grn"]),
             evidence=ev("matches the PO and goods receipt")),
        Node(id="n5", kind="gateway", name="Amount > 5000?",
             decision=Decision(type="THRESHOLD_AMOUNT", expression="invoice.amount > 5000"),
             evidence=ev("Invoices over $5,000 require director approval")),
        Node(id="n6", kind="task", name="Approve invoice",
             action=Action(type="APPROVE", actor_id="sys_erp", artifact_id="art_invoice"),
             evidence=ev("it can be approved")),
        Node(id="n7", kind="task", name="Director approves",
             action=Action(type="APPROVE", actor_id="role_director", artifact_id="art_invoice"),
             evidence=ev("require director approval")),
        Node(id="n8", kind="task", name="Schedule payment",
             action=Action(type="SCHEDULE_PAYMENT", actor_id="sys_erp", artifact_id="art_payment"),
             evidence=ev("payment is scheduled for Net 30")),
        Node(id="n9", kind="end", name="Paid/Complete", evidence=ev("then paid"))
    ]

    edges = [
        Edge(frm="n1", to="n2"),
        Edge(frm="n2", to="n3"),
        Edge(frm="n3", to="n4"),
        Edge(frm="n4", to="n5", condition="match"),
        Edge(frm="n5", to="n7", condition="amount>5000"),
        Edge(frm="n5", to="n6", condition="amount<=5000"),
        Edge(frm="n6", to="n8"),
        Edge(frm="n7", to="n8"),
        Edge(frm="n8", to="n9")
    ]

    unknowns = [
        {"id": "u1", "type": "missing_rule", "question": "What is the match tolerance for price/quantity variances?", "priority": "high"},
        {"id": "u2", "type": "missing_path", "question": "What happens if the invoice does NOT match (hold, vendor contact, reject)?", "priority": "high"}
    ]

    return ProcessDoc(meta=meta, actors=actors, artifacts=artifacts, nodes=nodes, edges=edges, unknowns=unknowns)

def manual_extract_doc_002(text: str) -> ProcessDoc:
    """

    Args:
      text: str:
      text: str: 

    Returns:

    """
    meta = _base_ap_meta("doc_002", "ap_invoice_doc_002")
    actors = _base_ap_actors()
    artifacts = _base_ap_artifacts()

    ev = lambda s: [Evidence(source_id="doc_002", span=s)]

    nodes = [
        Node(id="n1", kind="event", name="Invoice received", evidence=ev("If an invoice does not have a PO number")),
        Node(id="n2", kind="gateway", name="Has PO number?",
             decision=Decision(type="HAS_PO", expression="invoice.po_number exists"),
             evidence=ev("does not have a PO number")),
        Node(id="n3", kind="task", name="Route to manager for coding",
             action=Action(type="ROUTE_FOR_REVIEW", actor_id="role_ap_clerk", artifact_id="art_invoice", extra={"to": "role_manager"}),
             evidence=ev("AP routes it to the department manager")),
        Node(id="n4", kind="task", name="Manager confirms expense",
             action=Action(type="REVIEW", actor_id="role_manager", artifact_id="art_invoice"),
             evidence=ev("must confirm the expense")),
        Node(id="n5", kind="task", name="Manager provides account code",
             action=Action(type="UPDATE_RECORD", actor_id="role_manager", artifact_id="art_account_code"),
             evidence=ev("provide an account code")),
        Node(id="n6", kind="gateway", name="Manager decision",
             decision=Decision(type="APPROVE_OR_REJECT", inputs=["art_invoice"]),
             evidence=ev("If the manager rejects the expense")),
        Node(id="n7", kind="task", name="Notify vendor and close",
             action=Action(type="NOTIFY", actor_id="role_ap_clerk", artifact_id="art_invoice", extra={"to": "vendor"}),
             evidence=ev("AP notifies the vendor and closes the invoice")),
        Node(id="n8", kind="task", name="Enter account code in ERP",
             action=Action(type="ENTER_RECORD", actor_id="role_ap_clerk", artifact_id="art_account_code"),
             evidence=ev("AP enters the account code")),
        Node(id="n9", kind="task", name="Schedule payment",
             action=Action(type="SCHEDULE_PAYMENT", actor_id="sys_erp", artifact_id="art_payment"),
             evidence=ev("proceeds to schedule payment")),
        Node(id="n10", kind="end", name="Complete", evidence=ev("schedule payment"))
    ]

    edges = [
        Edge(frm="n1", to="n2"),
        Edge(frm="n2", to="n3", condition="no_po"),
        Edge(frm="n3", to="n4"),
        Edge(frm="n4", to="n5"),
        Edge(frm="n5", to="n6"),
        Edge(frm="n6", to="n7", condition="reject"),
        Edge(frm="n6", to="n8", condition="approve"),
        Edge(frm="n8", to="n9"),
        Edge(frm="n9", to="n10")
    ]

    unknowns = [
        {"id": "u1", "type": "missing_path", "question": "If the invoice DOES have a PO number, what is the standard AP path (2-way/3-way match, approvals)?", "priority": "high"},
        {"id": "u2", "type": "missing_rule", "question": "What validation is required before routing to manager (vendor verification, duplicate invoice check)?", "priority": "medium"}
    ]

    return ProcessDoc(meta=meta, actors=actors, artifacts=artifacts, nodes=nodes, edges=edges, unknowns=unknowns)

def manual_extract_doc_003(text: str) -> ProcessDoc:
    """

    Args:
      text: str:
      text: str: 

    Returns:

    """
    meta = _base_ap_meta("doc_003", "ap_invoice_doc_003")
    actors = _base_ap_actors()
    artifacts = _base_ap_artifacts()

    ev = lambda s: [Evidence(source_id="doc_003", span=s)]

    nodes = [
        Node(id="n1", kind="event", name="Start: perform 3-way match", evidence=ev("AP performs a 3-way match")),
        Node(id="n2", kind="task", name="Run 3-way match",
             action=Action(type="MATCH_3_WAY", actor_id="sys_erp", artifact_id="art_invoice", extra={"inputs": ["art_po","art_grn"]}),
             evidence=ev("performs a 3-way match")),
        Node(id="n3", kind="gateway", name="Variance above tolerance?",
             decision=Decision(type="VARIANCE_ABOVE_TOLERANCE"),
             evidence=ev("price variance above the tolerance")),
        Node(id="n4", kind="task", name="Place invoice on hold",
             action=Action(type="UPDATE_STATUS", actor_id="sys_erp", artifact_id="art_invoice", extra={"status": "hold"}),
             evidence=ev("invoice is placed on hold")),
        Node(id="n5", kind="task", name="Contact vendor",
             action=Action(type="REQUEST_CLARIFICATION", actor_id="role_ap_clerk", artifact_id="art_invoice", extra={"to": "vendor"}),
             evidence=ev("contacts the vendor for clarification")),
        # FIX: this is not a new START; it's an intermediate receipt step.
        Node(id="n6", kind="task", name="Receive corrected documents",
             action=Action(type="RECEIVE_MESSAGE", actor_id="sys_erp", artifact_id="art_corrected_docs"),
             evidence=ev("Once corrected documents are received")),
        Node(id="n7", kind="task", name="Update invoice",
             action=Action(type="UPDATE_RECORD", actor_id="role_ap_clerk", artifact_id="art_invoice"),
             evidence=ev("AP updates the invoice")),
        Node(id="n8", kind="task", name="Re-run matching",
             action=Action(type="MATCH_3_WAY", actor_id="sys_erp", artifact_id="art_invoice"),
             evidence=ev("re-runs matching")),
        Node(id="n9", kind="end", name="Return to normal flow", evidence=ev("re-runs matching"))
    ]

    edges = [
        Edge(frm="n1", to="n2"),
        Edge(frm="n2", to="n3"),
        Edge(frm="n3", to="n4", condition="above_tolerance"),
        # within_tolerance path is unknown for now; referee will suggest it too
        Edge(frm="n4", to="n5"),
        Edge(frm="n5", to="n6"),
        Edge(frm="n6", to="n7"),
        Edge(frm="n7", to="n8"),
        Edge(frm="n8", to="n9")
    ]

    unknowns = [
        {"id": "u1", "type": "missing_rule", "question": "What are the tolerance thresholds for quantity/price variance?", "priority": "high"},
        {"id": "u2", "type": "missing_path", "question": "If variance is within tolerance, what is the next step (auto-approve, manager review)?", "priority": "high"}
    ]

    return ProcessDoc(meta=meta, actors=actors, artifacts=artifacts, nodes=nodes, edges=edges, unknowns=unknowns)

def manual_extract_doc_004(text: str) -> ProcessDoc:
    """

    Args:
      text: str:
      text: str: 

    Returns:

    """
    meta = _base_ap_meta("doc_004", "ap_invoice_doc_004")
    actors = _base_ap_actors()
    artifacts = _base_ap_artifacts()
    ev = lambda s: [Evidence(source_id="doc_004", span=s)]

    nodes = [
        Node(id="n1", kind="event", name="Invoice received via portal", evidence=ev("receives the invoice via the central email portal")),
        Node(id="n2", kind="task", name="Validate invoice", action=Action(type="VALIDATE_FIELDS", actor_id="role_ap_clerk", artifact_id="art_invoice"), evidence=ev("clerk validates the invoice")),
        Node(id="n3", kind="gateway", name="Missing GL code?", decision=Decision(type="IF_CONDITION", expression="missing_gl_code"), evidence=ev("If the invoice is missing a GL account code")),
        Node(id="n4", kind="task", name="Contact manager", action=Action(type="REQUEST_CLARIFICATION", actor_id="role_ap_clerk", artifact_id="art_invoice"), evidence=ev("contacts the department manager")),
        Node(id="n5", kind="task", name="Provide account code", action=Action(type="UPDATE_RECORD", actor_id="role_manager", artifact_id="art_account_code"), evidence=ev("manager provides the account code")),
        Node(id="n6", kind="task", name="Route for director approval", action=Action(type="ROUTE_FOR_REVIEW", actor_id="role_ap_clerk", artifact_id="art_invoice", extra={"to": "role_director"}), evidence=ev("routed for director approval")),
        Node(id="n7", kind="gateway", name="Approved?", decision=Decision(type="APPROVE_OR_REJECT"), evidence=ev("If approved")),
        Node(id="n8", kind="task", name="Schedule payment", action=Action(type="SCHEDULE_PAYMENT", actor_id="sys_erp", artifact_id="art_payment"), evidence=ev("scheduled for payment")),
        Node(id="n9", kind="end", name="Complete", evidence=ev("scheduled for payment")),
    ]
    edges = [
        Edge(frm="n1", to="n2"), Edge(frm="n2", to="n3"),
        Edge(frm="n3", to="n4", condition="missing"), Edge(frm="n3", to="n6", condition="not_missing"),
        Edge(frm="n4", to="n5"), Edge(frm="n5", to="n6"),
        Edge(frm="n6", to="n7"),
        Edge(frm="n7", to="n8", condition="approve"),
        Edge(frm="n8", to="n9"),
    ]
    return ProcessDoc(meta=meta, actors=actors, artifacts=artifacts, nodes=nodes, edges=edges, unknowns=[])

def manual_extract_doc_005(text: str) -> ProcessDoc:
    """

    Args:
      text: str:
      text: str: 

    Returns:

    """
    meta = _base_ap_meta("doc_005", "ap_invoice_doc_005")
    actors = _base_ap_actors()
    artifacts = _base_ap_artifacts()
    ev = lambda s: [Evidence(source_id="doc_005", span=s)]

    nodes = [
        Node(id="n1", kind="event", name="Invoices entered", evidence=ev("Invoices are entered into the ERP")),
        Node(id="n2", kind="task", name="Enter into ERP", action=Action(type="ENTER_RECORD", actor_id="sys_erp", artifact_id="art_invoice"), evidence=ev("entered into the ERP")),
        Node(id="n3", kind="task", name="Check for duplicates", action=Action(type="VALIDATE_FIELDS", actor_id="sys_erp", artifact_id="art_invoice"), evidence=ev("system checks for duplicate invoice numbers")),
        Node(id="n4", kind="gateway", name="Duplicate detected?", decision=Decision(type="IF_CONDITION", expression="is_duplicate"), evidence=ev("If a duplicate is detected")),
        Node(id="n5", kind="task", name="Reject invoice", action=Action(type="REJECT", actor_id="sys_erp", artifact_id="art_invoice"), evidence=ev("system immediately rejects the invoice")),
        Node(id="n6", kind="task", name="Notify vendor", action=Action(type="NOTIFY", actor_id="sys_erp", artifact_id="art_invoice"), evidence=ev("notifies the vendor")),
        Node(id="n7", kind="end", name="Process Terminated", evidence=ev("notifies the vendor")),
        Node(id="n8", kind="task", name="Match against PO", action=Action(type="MATCH_3_WAY", actor_id="role_ap_clerk", artifact_id="art_invoice"), evidence=ev("match the invoice against the purchase order")),
        Node(id="n9", kind="task", name="Execute payment", action=Action(type="EXECUTE_PAYMENT", actor_id="sys_erp", artifact_id="art_payment"), evidence=ev("payment is executed")),
        Node(id="n10", kind="end", name="Paid", evidence=ev("payment is executed")),
    ]
    edges = [
        Edge(frm="n1", to="n2"), Edge(frm="n2", to="n3"), Edge(frm="n3", to="n4"),
        Edge(frm="n4", to="n5", condition="duplicate"), Edge(frm="n4", to="n8", condition="not_duplicate"),
        Edge(frm="n5", to="n6"), Edge(frm="n6", to="n7"),
        Edge(frm="n8", to="n9"), Edge(frm="n9", to="n10"),
    ]
    return ProcessDoc(meta=meta, actors=actors, artifacts=artifacts, nodes=nodes, edges=edges, unknowns=[])
