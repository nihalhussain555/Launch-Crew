"""The feature catalog: what it promises, what it admits, and the words that select it.

These tests exist because the brief's central rule is an honesty rule - "Never display fake success
messages for unimplemented functionality" - and the catalog is the single place that decides what the
product is allowed to claim. So the interesting assertions here are not "does the dict have keys" but
"does any capability sneak a promise of live, working behaviour past a surface this product cannot run".
"""
import re

import pytest

from app.agents import capabilities as cap
from app.services import workspace_manager as wm

# The sixteen areas the brief lists, in the brief's order. A rename here is a deliberate change to what
# users can ask for, so it has to show up as a test failure rather than a silent drop.
BRIEF_KEYS = ("authentication", "profiles", "admin", "records", "catalog", "browse", "blog", "booking",
              "contact", "uploads", "activity", "analytics", "wizard", "pricing", "api", "layout")

# Only these three are the page's own work: they need no server, no database and no account, which is
# why they are the only ones allowed to say "works in the published page now".
PAGE_ONLY = ("browse", "wizard", "layout")

ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")

# Words that would turn a scaffold into a lie when they sit next to a surface this product cannot run.
OVERPROMISE = ("is live", "works live", "deployed", "payment succeeded", "email sent", "now running",
               "automatically sends", "guaranteed", "fully working", "no setup")


def caps():
    return list(cap.CAPABILITIES)


# ------------------------------------------------------------------ the catalog itself

def test_catalog_offers_exactly_the_briefs_areas():
    assert cap.keys() == BRIEF_KEYS
    assert len(cap.CAPABILITIES) == 16


def test_every_capability_is_labelled_described_and_bounded():
    labels, blurbs, limits = set(), set(), set()
    for item in caps():
        assert item.label and item.label not in labels
        assert item.blurb and item.blurb not in blurbs
        assert len(item.limits) >= 60, f"{item.key} barely states its limits"
        assert item.limits not in limits
        labels.add(item.label)
        blurbs.add(item.blurb)
        limits.add(item.limits)


def test_labels_and_blurbs_are_plain_words_not_identifiers():
    """CRUD and API are what users say; SESSION_SECRET and server.py are what code says. Only the first
    two belong in a picker label."""
    for item in caps():
        assert not re.search(r"[A-Z][A-Z0-9]*_[A-Z0-9_]+", item.label), item.label
        assert "." not in item.label.replace("role-based", ""), item.label
        assert "\n" not in item.blurb
        assert item.blurb.endswith((".", "!")), f"{item.key}'s blurb trails off"


def test_aliases_never_overlap_between_capabilities():
    """One phrase naming two features would make the planner guess."""
    owner = {}
    for item in caps():
        assert len(set(item.aliases)) == len(item.aliases), f"{item.key} repeats an alias"
        for alias in item.aliases:
            assert alias == alias.lower(), alias
            assert alias not in owner, f"{alias!r} claims {owner[alias]} and {item.key}"
            owner[alias] = item.key


@pytest.mark.parametrize("key", BRIEF_KEYS)
def test_surfaces_and_states_are_the_declared_ones(key):
    item = cap.get(key)
    assert item.parts, f"{key} promises a feature with no surface"
    for part in item.parts:
        assert part.surface in cap.SURFACES
        assert part.state in cap.STATES
        assert len(part.detail) >= 40, f"{key}/{part.surface} does not say what it does"


@pytest.mark.parametrize("key", BRIEF_KEYS)
def test_files_and_env_names_are_usable_not_decorative(key):
    item = cap.get(key)
    for part in item.parts:
        assert part.files, f"{key}/{part.surface} claims to write nothing"
        for name in part.files:
            wm.validate_name(name)                      # the workspace would accept it
        for name in item.env:
            assert ENV_NAME.match(name), f"{key} names {name!r}, not an env var"
        if part.env:
            assert cap.SHARED_ENV in part.files, f"{key}/{part.surface} reads env vars nobody is told about"


@pytest.mark.parametrize("key", BRIEF_KEYS)
def test_every_capability_has_setup_steps_and_its_own_status(key):
    item = cap.get(key)
    assert item.setup, f"{key} leaves the user with no first step"
    assert all(isinstance(step, str) and step.strip() for step in item.setup), \
        f"{key}'s setup list holds something a user cannot read"
    assert item.status in cap.STATES
    assert item.status == cap.overall_status(item.parts)
    assert item.needs_approval, "a feature build that skips review is not a build, it is a surprise"


# ------------------------------------------------------------------ the honesty rules

def test_page_only_features_are_the_only_ones_claimed_as_working_now():
    generated = {item.key for item in caps() if item.status == cap.GENERATED}
    assert generated == set(PAGE_ONLY)


@pytest.mark.parametrize("key", [k for k in BRIEF_KEYS if k not in PAGE_ONLY])
def test_nothing_that_needs_a_server_or_an_account_is_reported_as_done(key):
    item = cap.get(key)
    assert item.status in (cap.SCAFFOLD, cap.NEEDS_SETUP)
    assert cap.STATE_LABEL[item.status] != cap.STATE_LABEL[cap.GENERATED]


@pytest.mark.parametrize("key", BRIEF_KEYS)
def test_scaffolds_never_promise_live_behaviour(key):
    item = cap.get(key)
    if item.status == cap.GENERATED:
        return
    prose = " ".join([item.blurb, item.limits] + [p.detail for p in item.parts]).lower()
    for phrase in OVERPROMISE:
        assert phrase not in prose, f"{key} says {phrase!r} about a surface that cannot run yet"


def test_external_services_are_always_the_weakest_part():
    """Money, mail and other people's APIs are handed over as setup, never as a finished integration."""
    for item in caps():
        for part in item.parts:
            if part.surface == "integration":
                assert part.state == cap.NEEDS_SETUP, f"{item.key} calls {part.state} an integration"
                assert part.env, f"{item.key}'s integration names no credential for the user to set"
                assert item.status == cap.NEEDS_SETUP


@pytest.mark.parametrize("key", ["catalog", "booking", "contact", "uploads", "activity", "analytics",
                                 "pricing", "api"])
def test_the_provider_backed_features_carry_their_integration_as_a_part(key):
    """A part left out of `parts` would disappear from the plan while its setup text stayed, which is
    how a feature ends up described as configured when nothing was ever wired."""
    item = cap.get(key)
    assert [p.surface for p in item.parts].count("integration") == 1
    assert "integration" in item.needs
    assert item.env, f"{key} depends on a provider but names no variable"


def test_the_four_paid_or_provided_services_say_who_they_belong_to():
    for key in ("catalog", "pricing", "contact", "api"):
        item = cap.get(key)
        setup = " ".join(item.setup).lower()
        assert "set" in setup or "create" in setup, f"{key} hands over no configuration action"
        assert any(part.surface == "integration" for part in item.parts)


def test_authentication_is_described_as_its_real_mechanism():
    item = cap.get("authentication")
    detail = " ".join(p.detail for p in item.parts).lower()
    assert "pbkdf2" in detail, "password hashing must be named, not implied"
    assert "session" in detail
    assert "SESSION_SECRET" in item.env
    assert "oauth" not in item.blurb.lower(), "OAuth is not generated and must not be advertised"


def test_no_credential_value_appears_anywhere_in_the_catalog():
    """Names of variables are fine; anything shaped like a key, token or secret is not."""
    blob = repr(cap.catalog())
    for pattern in (r"sk_live", r"sk_test", r"AKIA[0-9A-Z]{8}", r"Bearer\s+\S", r"=[A-Za-z0-9]{20,}"):
        assert not re.search(pattern, blob), pattern


def test_weakest_state_wins_whatever_the_order():
    parts = (cap.Part("page", cap.GENERATED, "a" * 40),
             cap.Part("integration", cap.NEEDS_SETUP, "b" * 40),
             cap.Part("server", cap.SCAFFOLD, "c" * 40))
    assert cap.overall_status(parts) == cap.NEEDS_SETUP
    assert cap.overall_status(tuple(reversed(parts))) == cap.NEEDS_SETUP
    assert cap.overall_status((parts[0], parts[2])) == cap.SCAFFOLD
    assert cap.overall_status(()) == cap.GENERATED


# ------------------------------------------------------------------ plain-English matching

@pytest.mark.parametrize("sentence, expected", [
    ("Add a signup form so people can create an account", "authentication"),
    ("I want a shopping cart and a checkout", "catalog"),
    ("let customers book an appointment", "booking"),
    ("we need role based access for the back office", "admin"),
    ("a blog with posts and drafts", "blog"),
    ("a contact form that emails us", "contact"),
    ("visitors should be able to upload photos", "uploads"),
    ("pricing plans with monthly subscriptions", "pricing"),
    ("add search, sorting and pagination to the list", "browse"),
    ("a multi-step onboarding wizard", "wizard"),
    ("an analytics dashboard of our own visitor stats", "analytics"),
    ("call our external service from a webhook endpoint", "api"),
    ("make the navigation responsive and accessible", "layout"),
    ("edit my account settings and change my password", "profiles"),
    ("database backed records with add item and delete item", "records"),
    ("an activity feed and alerts", "activity"),
])
def test_plain_english_names_the_feature_it_means(sentence, expected):
    found = cap.match(sentence)
    assert [row["key"] for row in found][:1] == [expected], found
    assert expected in {row["key"] for row in found}


def test_a_brief_can_name_several_features_at_once():
    found = {row["key"]: row["matched"] for row in cap.match("a shop with staff logins and a contact form")}
    assert {"catalog", "authentication", "contact"} <= set(found)
    assert found["authentication"] == "login", "the longest honest phrase should be the one reported"


@pytest.mark.parametrize("sentence", [
    "make the hero bigger and friendlier",
    "use a warmer palette and rounder corners",
    "please add some animations",
])
def test_words_that_name_no_feature_return_nothing(sentence):
    """A style request must not silently become a feature request."""
    assert cap.match(sentence) == []


def test_matching_is_on_word_boundaries_not_substrings():
    assert cap.match("the logo is a synonym for orchestral music") == []
    assert cap.match("the logos of our two best-known brands") == []


@pytest.mark.parametrize("phrase", ["role-based", "role based", "Role Based", "RBAC", "rbac"])
def test_one_feature_survives_spelling_and_casing(phrase):
    assert "admin" in {row["key"] for row in cap.match(phrase + " access for moderators")}


def test_match_rows_are_ordered_and_unique():
    rows = cap.match("payments, subscriptions, checkout, webhooks and an admin dashboard")
    keys = [row["key"] for row in rows]
    assert len(keys) == len(set(keys))
    lengths = [len(row["matched"]) for row in rows]
    assert lengths == sorted(lengths, reverse=True)
    for row in rows:
        assert row["matched"] in cap.get(row["key"]).aliases
        assert row["status"] == cap.get(row["key"]).status


# ------------------------------------------------------------------ the payloads the UI reads

def test_card_carries_everything_a_picker_needs_to_be_honest():
    item = cap.get("booking")
    row = cap.card(item)
    assert set(row) >= {"key", "label", "blurb", "status", "status_label", "needs", "parts", "files",
                        "env", "setup", "limits", "aliases", "tags"}
    assert row["status_label"] == cap.STATE_LABEL[item.status]
    assert len(row["parts"]) == len(item.parts)
    assert row["parts"][0] == {"surface": "page", "state": "generated", "detail": item.parts[0].detail,
                               "files": ["index.html"], "env": []}
    assert row["needs"] == ["page", "server", "database", "integration"]
    assert row["limits"] == item.limits


def test_cards_cover_the_catalog_in_order():
    rows = cap.cards()
    assert [row["key"] for row in rows] == list(BRIEF_KEYS)
    assert all(len(row["aliases"]) <= 8 for row in rows), "the picker is not a thesaurus"


def test_catalog_describes_the_states_and_the_shared_scaffold():
    cat = cap.catalog()
    assert tuple(cat["surfaces"]) == cap.SURFACES
    assert [entry["state"] for entry in cat["states"]] == list(cap.STATES)
    assert cat["shared_files"] == list(cap.SHARED_FILES)
    assert set(cat["shared_files"]) == {cap.SHARED_SERVER, cap.SHARED_DB, cap.SHARED_SCHEMA,
                                        cap.SHARED_ENV, cap.SHARED_SETUP}
    counts = cat["counts"]
    assert counts["capabilities"] == 16
    assert sum(counts[state] for state in cap.STATES) == counts["capabilities"], "a status fell through"
    assert counts[cap.NEEDS_SETUP] == sum(1 for row in cat["capabilities"]
                                          if any(p["surface"] == "integration" for p in row["parts"]))


def test_get_refuses_a_near_miss():
    assert cap.get("shooping-cart") is None
    assert cap.get("") is None
    assert cap.get(None) is None
    assert cap.get("catalog").key == "catalog"


def test_files_and_env_are_merged_in_first_seen_order():
    item = cap.get("catalog")
    assert item.files[0] == "index.html"
    assert item.files.count(cap.SHARED_SERVER) == 1
    assert item.files.count(cap.SHARED_ENV) == 1, "three parts add it, one listing may name it"
    assert list(item.env) == list(dict.fromkeys(item.env))
