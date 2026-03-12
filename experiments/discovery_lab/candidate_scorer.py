from candidate_types import CandidateInvariant


def score_candidate(candidate: CandidateInvariant) -> float:
    support_term = candidate.support_count
    contradiction_penalty = candidate.contradiction_count * 2
    agreement_term = (candidate.gold_agreement + candidate.runtime_agreement) * 50
    uncertainty_penalty = candidate.uncertainty_score * 25
    return support_term + agreement_term - contradiction_penalty - uncertainty_penalty
