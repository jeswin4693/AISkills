"""Evidence: the places in a repository a skill cites, with the facts the graph had, and a recheck that says what changed.

Docs: docs/evidence.md. Deterministic like the graph it reads: no model, nothing is run."""

from .model import EVIDENCE_FILE, MAX_REFS, Evidence, EvidenceError, Ref, evidence_bytes, fit, read_evidence, safe
from .recheck import LIMITS, STATUSES, Finding, RecheckReport, recheck
from .snapshot import Collected, Resolved, collect, git_dirty, git_head, node_of, resolve_ref

__all__ = [
    "EVIDENCE_FILE", "MAX_REFS", "Evidence", "EvidenceError", "Ref", "evidence_bytes", "fit", "read_evidence", "safe",
    "LIMITS", "STATUSES", "Finding", "RecheckReport", "recheck",
    "Collected", "Resolved", "collect", "git_dirty", "git_head", "node_of", "resolve_ref",
]
