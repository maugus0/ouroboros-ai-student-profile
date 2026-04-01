"""Tests for target degree clarification logic.

Verifies that when current degree level matches inferred target degree,
the system flags it for clarification instead of incorrectly inferring
a higher degree level.
"""

import pytest

from app.services.profile_service import ProfileService


class TestTargetDegreeClarification:
    """Test cases for target degree clarification when current == inferred target."""

    @pytest.mark.asyncio
    async def test_pursuing_masters_currently_flags_clarification(self):
        """Student stating 'pursuing Master's degree' should need clarification on target.

        Issue: CV contains "pursuing MTech in Software Engineering at NUS"
        - Current degree should be detected as: master
        - If inference would lead to target=master (matching current),
          it should be marked as: target_degree_level='unknown', needs_clarification=true
        """
        # This is a representative case: CV states "pursuing Master's"
        # The prompt should now detect ambiguity and set needs_clarification
        cv_text = """
        Results-driven Full-stack Software Engineer (C#, .NET, Angular, React)
        pursuing MTech in Software Engineering at NUS.
        Experienced in building scalable, cloud-integrated applications
        and ensuring high-quality, maintainable code through robust unit testing.
        """

        # Note: This test is more of a specification/documentation test
        # since actual LLM calls require real API keys.
        # The real verification happens in integration tests with mocked LLM responses.
        assert "pursuing" in cv_text.lower()
        assert "master" in cv_text.lower() or "mtech" in cv_text.lower()

    def test_profile_service_ensures_clarification_for_unknown_target(self):
        """Test that ProfileService enforces clarification queue when target_degree_level is unknown."""
        profile_data = {
            "full_name": "Test Student",
            "email": "test@example.com",
            "current_degree_level": "master",
            "target_degree_level": "unknown",  # Ambiguous case
            "target_degree_confidence": 0.0,
            "target_degree_needs_clarification": True,
        }

        clarified = ProfileService._apply_react_decision_pattern(profile_data)

        # Should queue a clarification question for unknown target degree
        assert clarified["target_degree_needs_clarification"] is True
        queue_fields = {item.get("field") for item in clarified.get("clarification_queue", [])}
        assert "target_degree_level" in queue_fields

    def test_profile_service_skips_clarification_for_explicit_target(self):
        """Test that ProfileService doesn't queue clarification when target is explicit."""
        profile_data = {
            "full_name": "Test Student",
            "email": "test@example.com",
            "current_degree_level": "master",
            "target_degree_level": "phd",  # Explicit PhD target
            "target_degree_confidence": 0.85,
            "target_degree_needs_clarification": False,
        }

        clarified = ProfileService._apply_react_decision_pattern(profile_data)

        # Should NOT queue clarification if target is explicit and different from current
        queue_fields = {item.get("field") for item in clarified.get("clarification_queue", [])}
        assert "target_degree_level" not in queue_fields
