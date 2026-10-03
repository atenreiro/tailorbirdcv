"""Fact-check bypasses found in review: each input used to PASS and must now fail.
Plus regressions that legitimate phrasing still passes. Fixtures are fictional."""

from pathlib import Path

import pytest

from autocv import critique as hm
from autocv.factcheck import FactChecker, Report, check, numbers
from autocv.schema import Claim, load_profile, load_tailored

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def profile():
    return load_profile(FIX / "profile.yaml")


@pytest.fixture
def tailored():
    return load_tailored(FIX / "tailored.yaml")


def errs_at(profile, tailored, where):
    return [e.message for e in check(profile, tailored).errors if e.where == where]


def acme_bullet(profile, tailored, text, sources=("acme-bank.a1",)):
    tailored.experience[0].bullets[0].text = text
    tailored.experience[0].bullets[0].sources = list(sources)
    return errs_at(profile, tailored, "experience[0].bullets[0]")


def telco_bullet(profile, tailored, text, sources=("telco.a1",)):
    tailored.experience[1].bullets[0].text = text
    tailored.experience[1].bullets[0].sources = list(sources)
    return errs_at(profile, tailored, "experience[1].bullets[0]")


def test_fixture_draft_still_passes(profile, tailored):
    report = check(profile, tailored)
    assert report.ok, report.errors


# ---- 1. cross-role / cross-section citations ----------------------------------------------------

@pytest.mark.parametrize("source", ["highlight.h1", "summary.s1", "project.toolx", "edu.bsc", "extra.languages"])
def test_role_bullet_cannot_cite_non_role_evidence(profile, tailored, source):
    errs = telco_bullet(profile, tailored, "Saved US$1.7M in one year through vendor contract negotiation.",
                        sources=["telco.a1", source])
    assert any("another role or section" in e and source in e for e in errs), errs


def test_role_scope_cannot_cite_a_highlight(profile, tailored):
    tailored.experience[1].scope.sources = ["telco.scope", "highlight.h1"]
    assert any("another role" in e for e in errs_at(profile, tailored, "experience[1].scope"))


def test_project_text_cannot_cite_role_evidence(profile, tailored):
    tailored.projects[0].text = Claim(text="Negotiated vendor contracts saving US$1.7M.", sources=["telco.a1"])
    errs = errs_at(profile, tailored, "projects[0]")
    assert any("another entry" in e and "project.toolx" in e for e in errs), errs


def test_project_text_citing_itself_passes(profile, tailored):
    tailored.projects[0].text = Claim(text="Open-source threat-intel tool with 400+ GitHub stars.",
                                      sources=["project.toolx"])
    assert check(profile, tailored).ok, check(profile, tailored).errors


def test_sub_role_text_may_only_cite_itself(profile, tailored):
    tailored.experience[0].sub_roles[0].text = Claim(text="Cut false positives by over 65%.",
                                                     sources=["acme-bank.a1"])
    assert any("another entry" in e for e in errs_at(profile, tailored, "experience[0].sub_roles[0]"))
    tailored.experience[0].sub_roles[0].text = Claim(text="Triaged alerts.", sources=["acme-bank.sub1"])
    assert check(profile, tailored).ok


def test_highlights_and_summary_may_still_cite_any_evidence(profile, tailored):
    tailored.highlights[0] = Claim(text="Saved US$1.7M in one year; ToolX has 400+ GitHub stars.",
                                   sources=["telco.a1", "project.toolx"])
    assert check(profile, tailored).ok, check(profile, tailored).errors


def test_hm_rewrite_citing_a_highlight_from_a_role_is_blocked(profile, tailored):
    review = {"issues": [{"where": "experience[1].bullets[0]", "action": "rewrite", "severity": "high",
                          "kind": "x", "problem": "p",
                          "rewrite": {"text": "Saved US$1.7M in one year, with no added headcount.",
                                      "sources": ["telco.a1", "highlight.h1"]}}]}
    out = hm._sanitize(profile, tailored, review, run_no=1)
    assert out["issues"][0]["action"] == "advice" and "another role" in out["issues"][0]["blocked"]


# ---- 2. spelled-out numbers ---------------------------------------------------------------------

@pytest.mark.parametrize("text, shown", [
    ("Protected a million customers by rebuilding detection logic in Splunk.", "1,000,000"),
    ("Protected a billion requests by rebuilding detection logic in Splunk.", "1,000,000,000"),
    ("Protected millions of customers by rebuilding detection logic in Splunk.", '"millions"'),
    ("Rebuilt detection logic in Splunk, cutting false positives by half.", "0.5"),
    ("Rebuilt detection logic in Splunk, cutting false positives by two-thirds.", "0.667"),
    ("Doubled detection coverage by rebuilding detection logic in Splunk.", '"doubled"'),
    ("Tripled detection coverage by rebuilding detection logic in Splunk.", '"tripled"'),
    ("First bank in the region to rebuild detection logic in Splunk.", "number 1 "),
    ("Ranked second for rebuilding detection logic in Splunk.", "number 2 "),
    ("Rebuilt tens of detection rules in Splunk.", '"tens"'),
    ("Rebuilt dozens of detection rules in Splunk.", '"dozens"'),
    ("Rebuilt hundreds of detection rules in Splunk.", '"hundreds"'),
    ("Cut false positives by over eighty-six percent by rebuilding detection logic in Splunk.", "number 86 "),
    ("Rebuilt detection logic in Splunk across two hundred rules.", "number 200 "),
    ("Rebuilt detection logic in Splunk for a thousand analysts.", "number 1,000 "),
])
def test_number_words_must_be_in_sources(profile, tailored, text, shown):
    errs = acme_bullet(profile, tailored, text)
    assert any(shown in e for e in errs), errs


def test_number_word_parsing():
    assert numbers("eighty-six") == {86}
    assert numbers("a million users") == {1e6}
    assert numbers("half a million users") == {5e5}
    assert numbers("two hundred and fifty thousand") == {250_000}
    assert numbers("twenty-first") == {21}
    assert numbers("half a dozen") == {6}
    assert numbers("a third of alerts") == {1 / 3}
    assert numbers("a third data center") == {3}
    assert numbers("one of the first-line teams") == set()       # lone "one" and idioms aren't counts
    assert numbers("cloud-first; per second; each quarter") == set()
    assert numbers("first line of defense") == set()
    assert numbers("50 million customers") == {50e6}              # "million" isn't counted twice
    assert numbers("3 thousand staff") == {3000}
    assert numbers("two three-person teams") == {2, 3}            # adjacent cardinals aren't summed


def test_spelled_number_matching_source_digits_passes(profile, tailored):
    tailored.experience[0].scope.text = "Led a team of five engineers protecting 20M+ customers."
    assert check(profile, tailored).ok, check(profile, tailored).errors


# ---- 3. invisible / format characters -----------------------------------------------------------

@pytest.mark.parametrize("ch", ["\xad", "\u200b", "\u200c", "\u200d", "\u2060", "\ufeff", "\u2061", "\u2064",
                                "\u202a", "\u202e", "\u2066", "\u2069", "\u200e", "\u200f"])
def test_invisible_characters_are_rejected(profile, tailored, ch):
    text = f"Rebuilt Splunk detection logic, cutting false positives by over 65%{ch} to roughly nine a month."
    errs = acme_bullet(profile, tailored, text)
    assert any("invisible" in e and f"U+{ord(ch):04X}" in e for e in errs), errs


def test_invisible_character_inside_a_word_is_rejected(profile, tailored):
    errs = acme_bullet(profile, tailored, "Rebuilt Kuber\xadnetes detection logic.")
    assert any("invisible" in e for e in errs)


def test_invisible_character_in_competency_label_and_item_is_rejected(profile, tailored):
    tailored.competencies[1].label = "Plat\u200bforms"
    tailored.competencies[1].items[0] = "Splunk\u200b"
    errs = [str(e) for e in check(profile, tailored).errors]
    assert any("competencies[1].label" in e and "invisible" in e for e in errs), errs
    assert any("competencies[1].items[0]" in e and "invisible" in e for e in errs), errs


# ---- 4. lookalikes --------------------------------------------------------------------------------

@pytest.mark.parametrize("text, needle", [
    ("Rebuilt Ⅿicrosoft detection logic in Splunk.", "U+216F"),           # Roman numeral M
    ("Rebuilt Splunk detection logic Ⅰ rebuilt again.", "U+2160"),         # Roman numeral one
    ("Rebuilt detection logic for Ørsted in Splunk.", "U+00D8"),           # Ø not in sources
    ("Rebuilt detection logic for Șhell in Splunk.", "U+0218"),            # Ș not in sources
])
def test_lookalike_characters_not_in_sources_are_rejected(profile, tailored, text, needle):
    errs = acme_bullet(profile, tailored, text)
    assert any(needle in e for e in errs), errs


def test_non_ascii_uppercase_word_is_an_entity(profile, tailored):
    # Ø is allowed once the cited evidence contains it, but each Ø-word is still an entity to verify
    profile.roles[0].achievements[0].text += " Built for Ørsted."
    assert acme_bullet(profile, tailored, "Rebuilt Splunk detection logic for Ørsted.") == []
    errs = acme_bullet(profile, tailored, "Rebuilt Splunk detection logic for Øresund.")
    assert any('"Øresund"' in e for e in errs), errs


@pytest.mark.parametrize("dash", ["‐", "‑", "‒", "–", "—", "―", "−",
                                  "﹘", "﹣", "－"])
def test_dash_variants_read_as_hyphen(profile, tailored, dash):
    ok = acme_bullet(profile, tailored, f"Rebuilt Splunk{dash}based detection logic, cutting false positives by over 65%.")
    assert ok == [], ok
    bad = acme_bullet(profile, tailored, f"Rebuilt AWS{dash}certified detection logic.")
    assert any("certified" in e for e in bad), bad


# ---- 5. lowercase tool / product names --------------------------------------------------------

@pytest.mark.parametrize("word", ["crowdstrike", "okta", "python", "aws", "zscaler", "sentinelone"])
def test_lowercase_tool_not_in_sources_is_rejected(profile, tailored, word):
    errs = telco_bullet(profile, tailored, f"Saved US$1.7M in one year renegotiating {word} contracts.")
    assert any(f'"{word}"' in e for e in errs), errs


def test_lowercase_splunk_needs_it_in_cited_sources(profile, tailored):
    errs = telco_bullet(profile, tailored, "Saved US$1.7M in one year renegotiating splunk contracts.")
    assert any('"splunk"' in e for e in errs)
    assert acme_bullet(profile, tailored, "Rebuilt detection logic in splunk, cutting false positives by over 65%.") == []


@pytest.mark.parametrize("text", [
    "Rebuilt detection logic in Splunk, cutting false-positive alert volume by over 65%.",
    "Cut noisy false positives by over 65% to roughly nine a month by rebuilding detection logic in Splunk.",
    "Re-architected detection logic in Splunk, reducing false positives by over 65%.",
    "Rebuilt the team's detection logic in Splunk; false positives fell by over 65% to roughly nine monthly.",
    "Rebuilt cloud-native, multi-tenant detection logic in Splunk to cut false positives by over 65%.",
    "Streamlined and modernized detection workflows in Splunk, cutting false positives by over 65%.",
    "Rebuilt detection logic in Splunk — the first line of defense — cutting false positives by over 65%.",
])
def test_ordinary_english_rephrasing_passes(profile, tailored, text):
    assert acme_bullet(profile, tailored, text) == [], text


def test_plural_and_possessive_of_a_cited_tool_pass(profile, tailored):
    assert acme_bullet(profile, tailored, "Rebuilt splunk's detection logic, cutting false positives by over 65%.") == []


def test_approved_synonym_lowercase_passes(profile, tailored):
    errs = acme_bullet(profile, tailored, "Own vendor spend across five platforms, including a web application firewall.",
                       sources=["acme-bank.a2"])
    assert errs == [], errs


# ---- 6. competency labels ------------------------------------------------------------------------

@pytest.mark.parametrize("label, needle", [
    ("20+ Years at Shell, Visa & Oracle", "number 20"),
    ("20+ Years at Shell, Visa & Oracle", '"Shell"'),
    ("20+ Years at Shell, Visa & Oracle", '"Visa"'),
    ("Ⅿicrosoft Platforms", "U+216F"),
    ("Hundreds of Platforms", '"hundreds"'),
    ("Okta & Splunk", '"Okta"'),
])
def test_competency_label_bypasses_are_rejected(profile, tailored, label, needle):
    tailored.competencies[1].label = label
    errs = errs_at(profile, tailored, "competencies[1].label")
    assert any(needle in e for e in errs), errs


@pytest.mark.parametrize("label", ["Platforms", "Security Platforms & Tools", "Detection Engineering",
                                   "Cloud & Edge Security", "WAF & DDoS", "Banking Security Leadership"])
def test_reasonable_competency_labels_pass(profile, tailored, label):
    tailored.competencies[1].label = label
    assert errs_at(profile, tailored, "competencies[1].label") == []


def test_competency_item_lookalike_is_rejected(profile, tailored):
    tailored.competencies[1].items[0] = "Splυnk"        # Greek upsilon
    assert any("non-Latin" in str(e) for e in check(profile, tailored).errors)


# ---- check_claim used directly (hiring-manager path) --------------------------------------------

def test_check_claim_direct_inherits_new_checks(profile):
    checker = FactChecker(profile)
    report = Report()
    checker.check_claim(Claim(text="Saved US$1.7M in one year with okta.", sources=["telco.a1"]), "x", report,
                        role="telco")
    assert any('"okta"' in e.message for e in report.errors)


@pytest.mark.parametrize("text", [
    "Shell partnered on rebuilding detection logic in Splunk.",
    "Visa: rebuilt detection logic in Splunk.",
])
def test_brand_names_that_are_dictionary_words_are_not_ordinary_first_words(profile, tailored, text):
    assert acme_bullet(profile, tailored, text)


def test_common_abbreviations_pass(profile, tailored):
    text = "Rebuilt detection logic (e.g. rules, lookups etc.) in Splunk, cutting false positives by over 65%."
    assert acme_bullet(profile, tailored, text) == []
