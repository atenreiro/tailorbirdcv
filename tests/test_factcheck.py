from pathlib import Path

import pytest

from autocv.factcheck import check, entity_terms, numbers
from autocv.schema import load_profile, load_tailored

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def profile():
    return load_profile(FIX / "profile.yaml")


@pytest.fixture
def tailored():
    return load_tailored(FIX / "tailored.yaml")


def errors(profile, tailored):
    return [str(e) for e in check(profile, tailored).errors]


def test_legitimate_rephrasing_passes(profile, tailored):
    report = check(profile, tailored)
    assert report.ok, report.errors


def test_changed_number_is_rejected(profile, tailored):
    tailored.experience[0].bullets[0].text = "Cut false positives by over 90% to roughly nine a month."
    assert any("number 90" in e for e in errors(profile, tailored))


def test_inflated_currency_is_rejected(profile, tailored):
    tailored.experience[1].bullets[0].text = "Saved US$3.2M in one year through vendor negotiation."
    assert any("3,200,000" in e for e in errors(profile, tailored))


def test_number_words_are_checked(profile, tailored):
    tailored.experience[0].bullets[0].text = "Cut false positives by over 65% to roughly seven a month."
    assert any("number 7" in e for e in errors(profile, tailored))


def test_invented_tool_is_rejected(profile, tailored):
    tailored.experience[0].bullets[0].text = "Rebuilt Splunk and Kubernetes detection logic, cutting false positives by over 65%."
    assert any('"Kubernetes"' in e for e in errors(profile, tailored))


def test_entity_from_another_role_is_rejected(profile, tailored):
    # Fastly is real evidence, but not for the telco role
    tailored.experience[1].bullets[0].text = "Saved US$1.7M in one year renegotiating Fastly contracts."
    assert any('"Fastly"' in e for e in errors(profile, tailored))


def test_synonym_is_accepted(profile, tailored):
    tailored.experience[0].bullets[1].text = "Own vendor spend across five platforms, including Fastly and a Web Application Firewall."
    assert check(profile, tailored).ok


def test_claim_without_sources_is_rejected(profile, tailored):
    tailored.highlights[0].sources = []
    assert any("no sources" in e for e in errors(profile, tailored))


def test_unknown_source_is_rejected(profile, tailored):
    tailored.highlights[0].sources = ["acme-bank.a99"]
    assert any("unknown source" in e for e in errors(profile, tailored))


def test_unknown_headline_is_rejected(profile, tailored):
    tailored.headline = "h.made-up"
    assert any("headline" in e for e in errors(profile, tailored))


def test_unknown_role_is_rejected(profile, tailored):
    tailored.experience[0].role = "google"
    assert any("unknown role" in e for e in errors(profile, tailored))


def test_sub_role_of_other_role_is_rejected(profile, tailored):
    tailored.experience[1].sub_roles = [tailored.experience[0].sub_roles[0]]
    assert any("not a sub-role" in e for e in errors(profile, tailored))


def test_skill_not_in_profile_is_rejected(profile, tailored):
    tailored.competencies[1].items.append("Kubernetes")
    assert any('skill "Kubernetes"' in e for e in errors(profile, tailored))


def test_skill_subphrase_is_accepted(profile, tailored):
    tailored.competencies[0].items.append("DDoS mitigation")
    assert check(profile, tailored).ok


def test_role_order_and_omission_warn(profile, tailored):
    tailored.experience = [tailored.experience[1]]
    report = check(profile, tailored)
    assert report.ok
    assert any("omitted" in str(w) for w in report.warnings)


def test_numbers_extraction():
    assert numbers("over 65%, roughly nine; US$1.7M; 4,500+ staff; 30M+") == {80, 6, 1.7e6, 3000, 30e6}
    assert numbers("1LoD F5 BIG-IP") == set()


def test_entity_terms_skip_clause_initial_words():
    assert entity_terms("Built Splunk-based HTTP detection; Led Globex's SOC 2 work") == [
        "Splunk-based", "HTTP", "Globex", "SOC",
    ]
