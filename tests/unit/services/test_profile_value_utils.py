"""Unit tests for profile value normalization utilities."""

from app.services.profile_value_utils import normalize_field_name


def test_normalize_field_name_country_aliases_to_target_study_country():
    assert normalize_field_name("preferred_country") == "target_study_country"
    assert normalize_field_name("target_country") == "target_study_country"
    assert normalize_field_name("country_preference") == "target_study_country"
    assert normalize_field_name("preferred-study-country") == "target_study_country"
    assert normalize_field_name("preferred_study_country") == "target_study_country"


def test_normalize_field_name_timeline_and_funding_aliases():
    assert normalize_field_name("target_intake") == "enrollment_timeline"
    assert normalize_field_name("planned_intake") == "enrollment_timeline"
    assert normalize_field_name("intake_timeline") == "enrollment_timeline"
    assert normalize_field_name("funding") == "funding_source"


def test_normalize_field_name_field_of_study_aliases():
    assert normalize_field_name("field_of_study") == "intended_field_of_study"
    assert normalize_field_name("preferred_field_of_study") == "intended_field_of_study"
