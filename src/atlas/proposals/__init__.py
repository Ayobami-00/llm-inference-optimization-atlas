"""Proposal scaffolding, rendering, and approval records."""

from atlas.proposals.service import (
    PROPOSAL_TYPES,
    create_github_issue,
    new_proposal,
    render_proposal,
    validate_proposal,
)

__all__ = [
    "PROPOSAL_TYPES",
    "create_github_issue",
    "new_proposal",
    "render_proposal",
    "validate_proposal",
]
