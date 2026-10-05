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
    tailored.experience[0].bullets[1].text = "Own vendor spend across four platforms, including Fastly and a Web Application Firewall."
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
    assert numbers("over 65%, roughly nine; US$1.7M; 4,500+ staff; 30M+") == {65, 9, 1.7e6, 4500, 30e6}
    assert numbers("1LoD F5 BIG-IP") == set()


def test_entity_terms_mark_clause_initial_words():
    assert entity_terms("Built Splunk-based HTTP detection; Led Globex's SOC 2 work") == [
        ("Built", True), ("Splunk-based", False), ("HTTP", False), ("Led", True), ("Globex", False), ("SOC", False),
    ]


# ---- regressions from the red-team audit -------------------------------------------------

BULLET = "experience[0].bullets[0]"


def bullet_errors(profile, tailored, text, sources=("acme-bank.a1",)):
    tailored.experience[0].bullets[0].text = text
    tailored.experience[0].bullets[0].sources = list(sources)
    return [str(e) for e in check(profile, tailored).errors if e.where == BULLET]


@pytest.mark.parametrize("text", [
    "Delivered AI programs while rebuilding detection logic",          # "ai" inside "Fastly"/"maintain"
    "Kubernetes detection logic rebuilt, cutting false positives",       # clause-initial proper noun
    "Rebuilt detection logic; Microsoft partnered on the rollout",       # after a semicolon
    "Rebuilt detection logic using kubernetes",                          # lowercase technology
    "Rebuilt detection logic as an AWS-certified engineer",              # credential via hyphen
    "Led the global detection engineering organization",                 # scope inflation
    "Single-handedly rebuilt detection logic",                           # inflation, clause-initial
    "Cut false positives by over 65% across hundreds of rules",          # vague magnitude
    "Doubled detection fidelity by rebuilding detection logic",          # multiplier word
    "Cut false positives 3x by rebuilding detection logic",              # multiplier digit
    "Ranked 1st for rebuilding detection logic",                         # ordinal
    "Rebuilt Кubernetes detection logic",                                # Cyrillic homoglyph
    "Rebuilt detection logic, cutting false positives by over 65% to roughly ninety a month",  # tens words are numbers
])
def test_red_team_bypasses_are_now_caught(profile, tailored, text):
    assert bullet_errors(profile, tailored, text), text


def test_role_header_is_not_citable(profile, tailored):
    errs = bullet_errors(profile, tailored, "Built a zero-trust program for Acme Bank", sources=["acme-bank"])
    assert any("role header" in e for e in errs)


def test_bullet_cannot_borrow_evidence_from_another_role(profile, tailored):
    tailored.experience[1].bullets[0].text = "Rebuilt Splunk detection logic, cutting false positives by over 65%."
    tailored.experience[1].bullets[0].sources = ["acme-bank.a1"]
    errs = [str(e) for e in check(profile, tailored).errors if e.where == "experience[1].bullets[0]"]
    assert any("another role" in e for e in errs)


def test_summary_may_combine_roles(profile, tailored):
    tailored.summary.text = "Security VP with 15 years; cut false positives by over 65% and saved US$1.7M."
    tailored.summary.sources = ["summary.s1", "acme-bank.a1", "telco.a1"]
    assert check(profile, tailored).ok


@pytest.mark.parametrize("item", ["AI", "IT", "Py", "Meter", "Ion"])
def test_competency_fragments_inside_words_are_rejected(profile, tailored, item):
    tailored.competencies[0].items.append(item)
    assert any(f'skill "{item}"' in str(e) for e in check(profile, tailored).errors)


def test_competency_label_is_checked(profile, tailored):
    tailored.competencies[0].label = "Kubernetes & Cloud Native Security (CISSP)"
    errs = [str(e) for e in check(profile, tailored).errors]
    assert any("Kubernetes" in e for e in errs) and any("CISSP" in e for e in errs)


def test_empty_competency_group_is_an_error(profile, tailored):
    tailored.competencies[1].items = []
    assert any("is empty" in str(e) for e in check(profile, tailored).errors)


@pytest.mark.parametrize("text", [
    "Rebuilt Splunk-based detection logic, cutting false positives by over 65% to roughly nine per month.",
    "Hands-on rebuild of detection logic in Splunk cut false positives by over 65%.",
    "Cut false-positive alert volume by over 65%, to roughly nine per month.",
])
def test_legitimate_rephrasings_still_pass(profile, tailored, text):
    assert bullet_errors(profile, tailored, text) == [], text
