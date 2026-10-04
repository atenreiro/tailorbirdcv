"""Fact-check bypasses from the second audit: each used to PASS and must now fail; legitimate phrasing still
passes. Fixtures are fictional (tests/fixtures/profile.yaml)."""

from pathlib import Path

import pytest

from autocv.factcheck import check
from autocv.schema import Claim, load_profile, load_tailored

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def profile():
    return load_profile(FIX / "profile.yaml")


@pytest.fixture
def tailored():
    return load_tailored(FIX / "tailored.yaml")


def errs(profile, tailored, where):
    return [e.message for e in check(profile, tailored).errors if e.where == where]


def acme(profile, tailored, text, sources=("acme-bank.a1",)):
    tailored.experience[0].bullets[0] = Claim(text=text, sources=list(sources))
    return errs(profile, tailored, "experience[0].bullets[0]")


def summary(profile, tailored, text, sources):
    tailored.summary = Claim(text=text, sources=list(sources))
    return errs(profile, tailored, "summary")


@pytest.mark.parametrize("text", [
    "Headed the detection rebuild, cutting false positives by over 65%, to roughly nine per month, in Splunk.",
    "Holds multiple certifications; cut false positives by over 65%, to roughly nine per month, in Splunk.",
    "Awarded for cutting false-positive alert volume by over 65%, to roughly nine per month, in Splunk.",
    "Cut false-positive alert volume by over 65%, to roughly nine per month, in Splunk; patents pending.",
    "Directed an enterprise wide rebuild of detection logic in Splunk, cutting false positives by over 65%.",
    "Cut false positives by over 65% in Splunk for a multinational group.",
    "Cut false positives by over 65% in Splunk across all regions and internationally.",
    "Rebuilt machine-learning detection logic in Splunk, cutting false positives by over 65%.",
])
def test_inflections_hyphens_and_scope_words_need_their_source(profile, tailored, text):
    assert acme(profile, tailored, text), text


def test_owning_the_department_needs_its_source(profile, tailored):
    e = acme(profile, tailored, "Led and owned alert triage for the department.", sources=("acme-bank.sub1",))
    assert e  # the sub-role only says "Triaged alerts"


def test_numbers_cannot_be_recombined_across_sources(profile, tailored):
    e = summary(profile, tailored, "Led a team of 4,500 engineers protecting 20M+ customers.",
                ["acme-bank.scope", "telco.scope"])
    assert any("3,000" in m and "engineers" in m for m in e), e
    e = acme(profile, tailored, "Cut false positives by over 3% for 65 engineers.", ("acme-bank.a1", "acme-bank.scope"))
    assert e, "3% and 65 engineers aren't stated anywhere"
    e = acme(profile, tailored, "Cut false positives by 2022 alerts.", ("acme-bank.a1",))
    assert e, "a role's dates are not a count"


def test_titles_stay_with_their_employer(profile, tailored):
    e = summary(profile, tailored, "Head of Security at Acme Bank who cut false positives by over 65%.",
                ["acme-bank.a1", "telco.a1"])
    assert any("Telco" in m and "Acme Bank" in m for m in e), e


@pytest.mark.parametrize("text", ["Elastic dashboards cut false positives by over 65% in Splunk.",
                                  "Jenkins pipelines cut false positives by over 65% in Splunk."])
def test_products_that_are_dictionary_words_need_a_source(profile, tailored, text):
    assert acme(profile, tailored, text)


def test_vocabulary_doesnt_widen_a_roles_own_lines(profile, tailored):
    profile.vocabulary = ["APAC"]
    text = "Led a team of 5 engineers protecting 20M+ customers across APAC."
    tailored.experience[0].scope = Claim(text=text, sources=["acme-bank.scope"])
    assert errs(profile, tailored, "experience[0].scope")
    assert summary(profile, tailored, "Security VP with 15 years across banking and telecom in APAC.",
                   ["summary.s1"]) == []  # still fine in the summary


@pytest.mark.parametrize("label", ["Cloud Security Architecture", "Regulatory Compliance",
                                   "Identity & Access Management", "Executive Leadership & Budget"])
def test_domain_labels_need_support_in_the_profile(profile, tailored, label):
    tailored.competencies[1].label = label
    assert errs(profile, tailored, "competencies[1].label")


def test_a_role_listed_twice_is_an_error(profile, tailored):
    tailored.experience.append(tailored.experience[0].model_copy(deep=True))
    assert any("appears twice" in e.message for e in check(profile, tailored).errors)


@pytest.mark.parametrize("text,sources", [
    ("Rebuilt detection logic in Splunk, cutting false positives by over 65% to roughly nine a month.", ["acme-bank.a1"]),
    ("Led a team of 5 engineers protecting 20M+ customers.", ["acme-bank.scope"]),
    ("Saved US$1.7M in one year by negotiating vendor contracts.", ["telco.a1"]),
])
def test_legitimate_rephrasing_still_passes(profile, tailored, text, sources):
    if sources[0].startswith("telco"):
        tailored.experience[1].bullets[0] = Claim(text=text, sources=sources)
        assert errs(profile, tailored, "experience[1].bullets[0]") == []
    elif sources[0].endswith("scope"):
        tailored.experience[0].scope = Claim(text=text, sources=sources)
        assert errs(profile, tailored, "experience[0].scope") == []
    else:
        assert acme(profile, tailored, text, sources) == []
