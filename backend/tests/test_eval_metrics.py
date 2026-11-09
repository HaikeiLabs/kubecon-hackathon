"""Metric math for eval.run_eval.score on tiny hand examples."""

import pytest

from eval.run_eval import EvalItem, descendants_index, score

CONCEPTS = [
    {"id": "fd:Parent", "ancestors": []},
    {"id": "fd:Child", "ancestors": ["fd:Parent"]},
    {"id": "fd:Other", "ancestors": []},
]


def test_descendants_index_inverts_ancestors() -> None:
    descendants = descendants_index(CONCEPTS)

    assert descendants == {"fd:Parent": {"fd:Child"}}


def test_exact_match_precision_recall_f1() -> None:
    items = [EvalItem(text="a", expected=["fd:Child", "fd:Other"])]
    metrics = score(items, [["fd:Child", "fd:Other"]], CONCEPTS)

    assert (metrics.precision, metrics.recall, metrics.f1) == (1.0, 1.0, 1.0)
    assert metrics.unlinked_rate == 0.0
    assert metrics.misses == []


def test_extra_prediction_is_false_positive_but_ancestor_tolerant() -> None:
    items = [EvalItem(text="a", expected=["fd:Child"])]
    metrics = score(items, [["fd:Child", "fd:Parent"]], CONCEPTS)

    assert metrics.precision == pytest.approx(0.5)
    assert metrics.recall == pytest.approx(1.0)
    assert metrics.f1 == pytest.approx(2 * 0.5 * 1.0 / 1.5)
    assert metrics.tolerant_precision == 1.0
    assert len(metrics.misses) == 1


def test_ancestor_prediction_is_exact_miss_but_tolerant_hit() -> None:
    items = [EvalItem(text="a", expected=["fd:Parent"])]
    metrics = score(items, [["fd:Child"]], CONCEPTS)

    assert metrics.precision == 0.0
    assert metrics.recall == 0.0
    assert metrics.f1 == 0.0
    assert metrics.tolerant_precision == 1.0


def test_unlinked_rate_and_zero_denominators_score_zero() -> None:
    items = [EvalItem(text="a", expected=[]), EvalItem(text="b", expected=["fd:Other"])]
    metrics = score(items, [[], []], CONCEPTS)

    assert metrics.unlinked_rate == pytest.approx(1.0)
    assert metrics.precision == 0.0
    assert metrics.recall == 0.0
    assert metrics.f1 == 0.0
