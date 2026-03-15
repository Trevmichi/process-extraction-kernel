from dataclasses import dataclass


@dataclass
class InvoiceFeatures:
    case_id: str
    has_po: bool | None = None
    amount_total: float | None = None
    num_dates_detected: int | None = None
    num_currency_markers: int | None = None
    num_total_candidates: int | None = None
