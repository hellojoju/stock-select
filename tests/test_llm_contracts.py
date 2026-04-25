"""Tests for LLMReviewContract validation."""
from __future__ import annotations

import pytest

from stock_select.llm_contracts import LLMReviewContract, AttributionClaim, LLMContractError


class TestAttributionClaim:
    def test_valid_extracted_claim(self):
        payload = {
            "claim": "Tech sector drove gains",
            "confidence": "EXTRACTED",
            "evidence_ids": ["ev_001"],
        }
        claim = AttributionClaim.validate(payload)
        assert claim.claim == "Tech sector drove gains"
        assert claim.confidence == "EXTRACTED"
        assert claim.evidence_ids == ["ev_001"]

    def test_valid_inferred_claim(self):
        payload = {"claim": "Market sentiment improved", "confidence": "INFERRED"}
        claim = AttributionClaim.validate(payload)
        assert claim.confidence == "INFERRED"

    def test_extracted_requires_evidence_ids(self):
        payload = {"claim": "No evidence", "confidence": "EXTRACTED", "evidence_ids": []}
        with pytest.raises(LLMContractError, match="EXTRACTED claims must have evidence"):
            AttributionClaim.validate(payload)

    def test_unknown_confidence_defaults_to_ambiguous(self):
        payload = {"claim": "Unknown", "confidence": "GUESSED"}
        claim = AttributionClaim.validate(payload)
        assert claim.confidence == "AMBIGUOUS"


class TestLLMReviewContract:
    def _valid_payload(self) -> dict:
        return {
            "review_target": {"type": "decision", "id": "pick_001"},
            "attribution": [
                {"claim": "Tech sector drove gains", "confidence": "EXTRACTED", "evidence_ids": ["ev_001"]}
            ],
            "reason_check": {"what_was_right": ["momentum"], "what_was_wrong": [], "missing_signals": []},
            "suggested_errors": [],
            "suggested_optimization_signals": [],
            "summary": "Good pick driven by sector momentum.",
        }

    def test_valid_contract(self):
        contract = LLMReviewContract.validate(self._valid_payload())
        assert contract.review_target["type"] == "decision"
        assert len(contract.attribution) == 1
        assert contract.summary == "Good pick driven by sector momentum."

    def test_extracted_requires_evidence_at_root(self):
        payload = self._valid_payload()
        payload["attribution"] = [
            {"claim": "No evidence", "confidence": "EXTRACTED", "evidence_ids": []}
        ]
        with pytest.raises(LLMContractError, match="EXTRACTED claims must have evidence"):
            LLMReviewContract.validate(payload)

    def test_missing_target_raises(self):
        payload = {
            "attribution": [],
            "reason_check": {},
            "summary": "",
        }
        with pytest.raises(LLMContractError, match="review_target"):
            LLMReviewContract.validate(payload)

    def test_missing_reason_check_defaults(self):
        payload = {
            "review_target": {"type": "decision", "id": "pick_001"},
            "attribution": [],
            "reason_check": {},
            "summary": "",
        }
        contract = LLMReviewContract.validate(payload)
        assert contract.reason_check["what_was_right"] == []
        assert contract.reason_check["what_was_wrong"] == []
        assert contract.reason_check["missing_signals"] == []

    def test_empty_attribution_allowed(self):
        payload = {
            "review_target": {"type": "decision", "id": "pick_001"},
            "attribution": [],
            "reason_check": {},
            "summary": "",
        }
        contract = LLMReviewContract.validate(payload)
        assert contract.attribution == []
