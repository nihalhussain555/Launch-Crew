"""Planning a feature build from a sentence: what it may claim, and what it must refuse to claim.

These tests hold the honesty rules Brief 1 depends on. A plan is only useful if it can be trusted next
to the code it describes, so each one measures something real - the keys the catalog actually has source
for, the bytes the composer actually writes, the state of the weakest surface - rather than a string the
planner chose.

The refusals matter as much as the answers: an unknown key is refused instead of being swapped for the
nearest real feature, a sentence that names nothing is refused with the words that do work, and a
dependency pulled in silently is a bug, not a convenience.
"""
import pytest

from app.agents import capabilities as caps
from app.services import feature_build, feature_plan, feature_templates as templates
from app.services.workspace_manager import WorkspaceError


def plan(text, **kw):
    return feature_plan.resolve(text, **kw)


# ------------------------------------------------------------------ what a sentence means
def test_a_sentence_names_the_features_it_words():
    p = plan("I need a product catalog with a cart and checkout")
    assert p["keys"] == ["catalog"]
    assert p["named"] == ["catalog"]
    assert sorted(p["needs"]) == ["database", "integration", "page", "server"]
    assert p["need_words"] == ["frontend changes", "backend logic", "database changes",
                               "external integrations"]


def test_several_features_in_one_brief_are_all_kept():
    p = plan("Add a contact form, a blog and search")
    assert set(p["keys"]) == {"contact", "blog", "browse"}
    assert set(p["statuses"]) == {"contact", "blog", "browse"}


def test_a_word_that_names_a_second_feature_is_not_left_out():
    """"products" is a catalog. Dropping the feature a sentence implies would understate the build."""
    p = plan("Add a contact form, a blog and search over the products")
    assert {"contact", "blog", "browse", "catalog"} == set(p["keys"])
    assert set(p["matched"]) == {"contact form", "blog", "search", "products"}


def test_words_that_name_nothing_are_refused_with_the_words_that_do():
    with pytest.raises(WorkspaceError) as exc:
        plan("make it sing")
    assert exc.value.status == 422
    assert "names a feature this product can build" in exc.value.message
    for label in ("Sign in and register", "Blog publishing and content management"):
        assert label in exc.value.message, "the refusal must show what can be asked for"


def test_an_unknown_key_is_refused_rather_than_replaced_by_a_near_miss():
    """'payments' has no source here. Answering it with 'catalog' would be a feature nobody wrote."""
    with pytest.raises(WorkspaceError) as exc:
        plan("", keys=["payments"])
    assert exc.value.status == 422
    assert "'payments' is not a feature Launch Crew has source for" in exc.value.message


@pytest.mark.parametrize("key", sorted(caps.keys()))
def test_every_capability_in_the_catalog_can_be_planned_alone(key):
    p = plan("", keys=[key])
    assert key in p["keys"]
    assert p["overall"] in caps.STATES
    assert p["summary"] and "\n" not in p["summary"]
    assert p["files"], "a plan that writes nothing must not be offered as a build"
    assert all(row["status"] in caps.STATES for row in p["features"])


# ------------------------------------------------------------------ dependencies are said out loud
def test_a_dependent_feature_names_the_feature_it_pulled_in():
    p = plan("", keys=["profiles"])
    assert p["keys"] == ["authentication", "profiles"]
    assert p["added"] == ["authentication"]
    assert p["named"] == ["profiles"], "the user asked for a profile, not for accounts"
    assert any("Pulled in" in warning for warning in p["warnings"])


def test_a_feature_needing_accounts_says_which_ones_and_reads_no_values():
    p = plan("a store with checkout")
    assert p["overall"] == caps.NEEDS_SETUP
    assert {"PAYMENT_PROVIDER", "PAYMENT_SECRET_KEY"} <= set(p["env"])
    assert all("=" not in name for name in p["env"]), "names only - a plan never carries a value"
    provider = [row for row in p["features"] if row["key"] == "catalog"][0]
    assert any("payment" in line.lower() for line in p["warnings"] + [provider["limits"]])


def test_a_page_only_feature_is_the_one_kind_reported_as_working_now():
    p = plan("a multi step onboarding form")
    assert p["keys"] == ["wizard"] and p["overall"] == caps.GENERATED
    assert p["needs"] == {"page": ["wizard"]} and p["env"] == []
    assert not templates.needs_server(p["keys"])
    assert not any(name == caps.SHARED_SERVER for name in (f["name"] for f in p["files"]))


# ------------------------------------------------------------------ measured, not asserted
def test_the_file_list_is_the_bytes_the_composer_actually_writes():
    p = plan("sign in, a blog and search")
    files = templates.compose(p["keys"], site="", idea=p["request"], plan=p["doc"])
    assert [f["name"] for f in p["files"]] == sorted(files)
    for entry in p["files"]:
        assert entry["bytes"] == len(files[entry["name"]].encode("utf-8", "ignore"))
    assert p["total_bytes"] == sum(f["bytes"] for f in p["files"])
    assert p["page_bytes"] == len(files[templates.PAGE_SECTIONS].encode("utf-8", "ignore"))


def test_a_named_site_and_idea_reach_the_measured_bytes():
    """FEATURES.md and server.py carry the site's own words, so their sizes move with them."""
    plain = plan("bookings", keys=["booking"])
    named = feature_plan.build(plain["keys"], request="bookings", site="Nimbus Roasters",
                               idea="a coffee subscription")
    assert any(f["name"] == caps.SHARED_SERVER for f in named["files"])
    for entry in named["files"]:
        assert entry["bytes"] == len(templates.compose(named["keys"], site="Nimbus Roasters",
                                                       idea="a coffee subscription",
                                                       plan=named["doc"])[entry["name"]].encode()), entry


def test_the_whole_catalog_at_once_still_fits_one_workspace_patch():
    """Sixteen features is the worst case a plan can produce; the page block has one home and one size."""
    p = plan("", keys=list(caps.keys()))
    assert len(p["keys"]) == len(caps.keys())
    assert p["page_bytes"] <= feature_build.MAX_PATCH_BYTES
    assert len(p["files"]) <= 12, "one build may not write more files than the workspace allows"
    assert p["overall"] == caps.NEEDS_SETUP, "at least one part still waits on an account"


def test_the_routes_and_tables_a_plan_promises_exist_in_the_source_it_lists():
    p = plan("bookings and an activity feed")
    for row in p["features"]:
        for route in p["routes"].get(row["key"], []):
            assert route in p["routes"][row["key"]]
        for table in p["tables"].get(row["key"], []):
            assert f"CREATE TABLE IF NOT EXISTS {table}" in templates.schema_text(p["keys"])


def test_summarise_says_the_state_it_measured_in_one_line():
    generated = feature_plan.summarise(plan("search and filters"))
    assert generated == feature_plan.summarise(plan("search and filters"))
    assert "\n" not in generated and len(generated) <= 240
    assert "works in the published page now" in generated
    assert "needs your account or keys" in feature_plan.summarise(plan("a store with checkout"))
