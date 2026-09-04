"""Tests for fuzzy linking: scoring, blocking, thresholds, best matches."""

import pandas as pd
import pytest

from localdb import fuzzy_link_tables


def people_a():
    return pd.DataFrame({
        "postcode": ["4223", "4560", "3000"],
        "given_name": ["michaela", "courtney", "bruce"],
        "surname": ["neumann", "painter", "wayne"],
    })


def people_b():
    return pd.DataFrame({
        "postcode": ["4223", "4560", "90210"],
        "given_name": ["michaela", "courtny", "diana"],
        "surname": ["neuman", "painter", "prince"],
    })


def test_exact_rows_score_one():
    result = fuzzy_link_tables(people_a(), people_b().head(1), on=["postcode", "given_name"])
    assert len(result.matched) == 1
    assert result.matched["score"].iloc[0] == 1.0


def test_typo_pair_scores_between_zero_and_one():
    result = fuzzy_link_tables(
        people_a().head(2), people_b().head(2), on=["postcode", "surname"], threshold=0.7
    )
    assert len(result.matched) == 2
    assert (result.matched["score"] >= 0.7).all()


def test_below_threshold_excluded():
    result = fuzzy_link_tables(people_a(), people_b(), on=["given_name"], threshold=0.9)
    assert "bruce" not in result.matched.get("score").astype(str).values
    assert result.matched["score"].min() >= 0.9


def test_blocking_limits_candidates():
    unblocked = fuzzy_link_tables(people_a(), people_b(), on=["surname"], block_on=None)
    blocked = fuzzy_link_tables(people_a(), people_b(), on=["surname"], block_on="postcode")
    assert unblocked.candidate_pairs == 9
    assert blocked.candidate_pairs < 9


def test_block_on_list_is_union():
    left = pd.DataFrame({"pc": ["1", "2"], "sn": ["aa", "bb"]})
    right = pd.DataFrame({"pc": ["9", "1"], "sn": ["aa", "zz"]})
    result = fuzzy_link_tables(left, right, on=["pc"], block_on=["pc", "sn"])
    assert result.candidate_pairs == 2
    blocked_single = fuzzy_link_tables(left, right, on=["pc"], block_on="pc")
    assert blocked_single.candidate_pairs == 1


def test_max_pairs_guard_raises():
    with pytest.raises(ValueError, match="max_pairs"):
        fuzzy_link_tables(people_a(), people_b(), on=["surname"], max_pairs=3)


def test_missing_fields_excluded_from_denominator():
    left = pd.DataFrame({"postcode": ["4223", "4223"], "surname": ["neumann", "x"]})
    right = pd.DataFrame({"postcode": ["4223", "4223"], "surname": [None, "neuman"]})
    result = fuzzy_link_tables(left, right, on=["postcode", "surname"], threshold=0.5)
    best = result.best_matches()
    top = best[best["left_index"] == 0]["score"].iloc[0]
    assert top == 1.0


def test_best_matches_one_row_per_left():
    left = pd.DataFrame({"postcode": ["4223"] * 2, "surname": ["neumann"] * 2})
    right = pd.DataFrame({"postcode": ["4223"], "surname": ["neuman"]})
    result = fuzzy_link_tables(left, right, on=["postcode", "surname"], threshold=0.5)
    best = result.best_matches()
    assert len(best) == 2
    assert best["left_index"].is_unique


def test_weights_change_ranking():
    left = pd.DataFrame({"postcode": ["4223"], "surname": ["neumann"]})
    right = pd.DataFrame({"postcode": ["4229"], "surname": ["neuman"]})
    even = fuzzy_link_tables(left, right, on=["postcode", "surname"], threshold=0.0)
    skewed = fuzzy_link_tables(
        left, right, on=["postcode", "surname"], weights={"surname": 9.0}, threshold=0.0
    )
    assert skewed.matched["score"].iloc[0] > even.matched["score"].iloc[0]


def test_left_on_right_on_different_names():
    left = pd.DataFrame({"zip": ["4223"], "last": ["neumann"]})
    right = pd.DataFrame({"postcode": ["4223"], "surname": ["neumann"]})
    result = fuzzy_link_tables(
        left, right, left_on=["zip", "last"], right_on=["postcode", "surname"]
    )
    assert result.matched["score"].iloc[0] == 1.0


def test_unknown_columns_raise():
    with pytest.raises(KeyError, match="lacks comparison"):
        fuzzy_link_tables(people_a(), people_b(), on=["nope"])
    with pytest.raises(ValueError, match="same length"):
        fuzzy_link_tables(people_a(), people_b(), left_on=["surname"],
                          right_on=["surname", "postcode"])


def test_block_on_missing_column_raises():
    with pytest.raises(KeyError, match="block column"):
        fuzzy_link_tables(people_a(), people_b(), on=["surname"], block_on="nope")
