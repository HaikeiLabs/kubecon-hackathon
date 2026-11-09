"""Concept-linking precision/recall against the hand-labeled gold set.

Usage (from backend/):
    uv run --extra dev python -m eval.run_eval           # offline: pure-python exact linker
    uv run --extra dev python -m eval.run_eval --live    # live: link_concepts(Elasticsearch, ...)

Scoring is exact-id micro precision/recall; ancestor-tolerant precision is reported separately
(a prediction also counts there when it is an ancestor or descendant of an expected id).
A 0/0 denominator scores 0.0. The exit code is always 0 so eval runs never fail CI.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if __package__ in (None, ""):  # allow direct execution: python eval/run_eval.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if TYPE_CHECKING:
    from app.search import Concept

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_GOLD_PATH = EVAL_DIR / "gold.jsonl"


@dataclass(frozen=True)
class EvalItem:
    text: str
    expected: list[str]


@dataclass
class ItemScore:
    position: int
    item: EvalItem
    predicted: list[str]
    tp: int
    fp: int
    fn: int
    tolerant_correct: int


@dataclass
class Metrics:
    precision: float
    recall: float
    f1: float
    tolerant_precision: float
    unlinked_rate: float
    predicted_total: int
    expected_total: int
    items: int
    misses: list[ItemScore] = field(default_factory=list)


def load_gold(path: str | Path | None = None) -> list[EvalItem]:
    file = Path(path or DEFAULT_GOLD_PATH)
    items: list[EvalItem] = []
    with file.open() as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            items.append(EvalItem(text=row["text"], expected=list(row.get("expected", []))))
    return items


def descendants_index(concepts: Sequence[Concept]) -> dict[str, set[str]]:
    """Map concept id -> the ids of all its descendants (children, grandchildren, ...)."""
    descendants: dict[str, set[str]] = {}
    for concept in concepts:
        for ancestor in concept.get("ancestors", []):
            descendants.setdefault(ancestor, set()).add(concept["id"])
    return descendants


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def score(
    items: Sequence[EvalItem], predictions: Sequence[Sequence[str]], concepts: Sequence[Concept]
) -> Metrics:
    """Micro precision/recall (exact id only) plus ancestor-tolerant precision separately."""
    by_id = {c["id"]: c for c in concepts}
    descendants = descendants_index(concepts)
    tp_total = fp_total = fn_total = tolerant_total = predicted_total = 0
    unlinked = 0
    misses: list[ItemScore] = []

    for position, (item, predicted) in enumerate(zip(items, predictions), start=1):
        expected = set(item.expected)
        pred = list(dict.fromkeys(predicted))
        predicted_total += len(pred)
        tp = len(expected & set(pred))
        fp = len(pred) - tp
        fn = len(expected) - tp
        tp_total += tp
        fp_total += fp
        fn_total += fn
        tolerant_correct = tp
        for cid in pred:
            if cid in expected:
                continue
            for want in expected:
                ancestors = set(by_id.get(want, {}).get("ancestors", []))
                if cid in ancestors or cid in descendants.get(want, set()):
                    tolerant_correct += 1
                    break
        tolerant_total += tolerant_correct
        if not pred:
            unlinked += 1
        if fp or fn:
            misses.append(ItemScore(position, item, pred, tp, fp, fn, tolerant_correct - tp))

    precision = _ratio(tp_total, tp_total + fp_total)
    recall = _ratio(tp_total, tp_total + fn_total)
    return Metrics(
        precision=precision,
        recall=recall,
        f1=_ratio(2 * precision * recall, precision + recall) if precision + recall else 0.0,
        tolerant_precision=_ratio(tolerant_total, predicted_total),
        unlinked_rate=_ratio(unlinked, len(items)),
        predicted_total=predicted_total,
        expected_total=tp_total + fn_total,
        items=len(items),
        misses=misses,
    )


def offline_predictor(concepts: Sequence[Concept]) -> Callable[[str], list[str]]:
    """Pass 1 of link_concepts: word-boundary label matching, no Elasticsearch."""
    from app.search import exact_concept_matches

    def predict(text: str) -> list[str]:
        return [tag.concept_id for tag in exact_concept_matches(text, concepts)]

    return predict


def live_predictor(concepts: Sequence[Concept]) -> Callable[[str], list[str]]:
    """Full link_concepts against a real cluster; creds come from the environment."""
    from elasticsearch import Elasticsearch

    from app.search import link_concepts

    url = os.environ.get("ELASTICSEARCH_URL")
    api_key = os.environ.get("ELASTICSEARCH_API_KEY")
    if not url or not api_key:
        raise ValueError("ELASTICSEARCH_URL and ELASTICSEARCH_API_KEY must be set for --live")
    client: Any = Elasticsearch(url, api_key=api_key)

    def predict(text: str) -> list[str]:
        return [tag.concept_id for tag in link_concepts(client, text, concepts=concepts)]

    return predict


def report(mode: str, metrics: Metrics) -> None:
    print(f"mode={mode} items={metrics.items} concepts_linked={metrics.predicted_total}")
    print(f"precision                   {metrics.precision:.3f}")
    print(f"recall                      {metrics.recall:.3f}")
    print(f"f1                          {metrics.f1:.3f}")
    print(f"ancestor-tolerant precision {metrics.tolerant_precision:.3f}")
    print(f"unlinked rate               {metrics.unlinked_rate:.3f}")
    if metrics.misses:
        print(f"misses ({len(metrics.misses)}):")
        for miss in metrics.misses:
            print(f"  [{miss.position}] {miss.item.text!r}")
            print(f"      expected:  {sorted(miss.item.expected)}")
            print(f"      predicted: {sorted(miss.predicted)}")
            if miss.tolerant_correct:
                print(f"      ({miss.tolerant_correct} extra prediction(s) ancestor-tolerant)")


def run(mode: str, gold_path: str | Path | None = None) -> Metrics:
    from app.search import read_concepts

    items = load_gold(gold_path)
    concepts = read_concepts()
    predictor = live_predictor(concepts) if mode == "live" else offline_predictor(concepts)
    predictions = [predictor(item.text) for item in items]
    metrics = score(items, predictions, concepts)
    report(mode, metrics)
    return metrics


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="score link_concepts with a real Elasticsearch client"
    )
    parser.add_argument("--gold", default=None, help="path to gold.jsonl (default: alongside)")
    args = parser.parse_args(argv)
    try:
        run("live" if args.live else "offline", args.gold)
    except Exception as exc:  # an eval run must never fail the build
        print(f"EVAL ERROR: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
