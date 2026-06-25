"""Post-generation safety gate for InsightSet (FR-014, FR-015, FR-019, SC-004).

Enforces three non-negotiable rules (Constitution Principle II):

1. **Disclaimer present** — InsightSet.disclaimer must be a non-empty string.
2. **Exactly one action** — each Insight.action must be a single directive with no
   enumerated or bulleted multi-step lists.
3. **No diagnostic / causal phrasing** — the summary must not contain terms from
   the banned lexicon (e.g. "diagnose", "disease", "you have", "causes", "due to").
4. **Source signal provenance** — when a ComparisonObject is supplied, every signal
   in Insight.source_signals must be a known metric or association signal in that
   comparison (no fabricated provenance).

Usage::

    from wearable_insights.safety import check_insight_set, SafetyError

    try:
        validated = check_insight_set(insight_set, comparison=comparison)
    except SafetyError as exc:
        # exc.violations lists every specific failure
        handle_or_retry(exc)

``check_insight_set`` returns the unchanged InsightSet on success so it can be
used inline in a pipeline assignment.
"""

from __future__ import annotations

import re

from .models import ComparisonObject, InsightSet


# ── Banned-term lexicon ───────────────────────────────────────────────────────
# Regex patterns tested (case-insensitive) against Insight.summary.
# These guard FR-014: no medical diagnosis, no causation claims.

_BANNED_DIAGNOSTIC: list[str] = [
    r"\bdiagnos\w*",          # diagnose, diagnosis, diagnosed
    r"\bdisease\b",
    r"\bdisorder\b",
    r"\bclinical\b",
    r"\bpatholog\w*",         # pathology, pathological
    r"\bsymptom\w*",
    r"\byou have\b",
    r"\byou are suffering\b",
    r"\bseek\s+(?:immediate\s+)?(?:medical|emergency)",
    r"\bcall\s+(?:911|999|112|emergency)",
]

_BANNED_CAUSAL: list[str] = [
    r"\bcauses?\b",           # "causes", "cause" as a verb ("this causes...")
    r"\bcaused\s+by\b",
    r"\bdue\s+to\b",
    r"\bresults?\s+in\b",
    r"\bleads?\s+to\b",
    r"\bbecause\s+of\b",
    r"\bis\s+the\s+(?:cause|reason)\b",
]

_BANNED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE) for p in (_BANNED_DIAGNOSTIC + _BANNED_CAUSAL)
]


# ── Multi-step action detection ───────────────────────────────────────────────
# A single action must be one directive; numbered / bulleted lists are not allowed.

_MULTI_STEP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b[2-9]\.\s+\w"),                         # "2. Do this"
    re.compile(r"\b[2-9]\)\s+\w"),                         # "2) Do this"
    re.compile(r"(?m)^\s*[-•*]\s+\S.+\n\s*[-•*]\s+\S"),  # two or more bullets
    re.compile(r"\bfirst\b.{1,80}\bthen\b", re.DOTALL | re.IGNORECASE),
    re.compile(r"\bstep\s+[1-9]\b", re.IGNORECASE),
]


# ── Error type ────────────────────────────────────────────────────────────────


class SafetyError(Exception):
    """Raised when an InsightSet fails the safety gate.

    Attributes:
        violations: ordered list of human-readable violation descriptions.
    """

    def __init__(self, violations: list[str]) -> None:
        self.violations = violations
        super().__init__(
            f"Safety check failed ({len(violations)} violation(s)): "
            + "; ".join(violations)
        )


# ── Internal checks ───────────────────────────────────────────────────────────


def _check_disclaimer(insight_set: InsightSet) -> list[str]:
    if not insight_set.disclaimer or not insight_set.disclaimer.strip():
        return ["disclaimer is absent or empty"]
    return []


def _check_single_action(action: str, idx: int) -> list[str]:
    for pattern in _MULTI_STEP_PATTERNS:
        if pattern.search(action):
            return [f"insight[{idx}].action appears to contain multiple steps"]
    return []


def _check_banned_terms(summary: str, idx: int) -> list[str]:
    violations: list[str] = []
    for pattern in _BANNED_PATTERNS:
        match = pattern.search(summary)
        if match:
            violations.append(
                f"insight[{idx}].summary contains banned term '{match.group()}'"
            )
    return violations


def _known_signals(comparison: ComparisonObject) -> frozenset[str]:
    signals: set[str] = set()
    signals.update(comparison.sleep.keys())
    signals.update(comparison.heart_health.keys())
    signals.update(comparison.activity.keys())
    for assoc in comparison.candidate_associations:
        signals.update(assoc.signals)
        signals.add(assoc.relation)  # prompt lists relation names as valid signal refs
    return frozenset(signals)


def _check_source_signals(
    source_signals: list[str],
    comparison: ComparisonObject,
    idx: int,
) -> list[str]:
    known = _known_signals(comparison)
    unknown = [s for s in source_signals if s not in known]
    if unknown:
        return [
            f"insight[{idx}].source_signals contains unknown signals: {unknown}"
        ]
    return []


# ── Public API ────────────────────────────────────────────────────────────────


def check_insight_set(
    insight_set: InsightSet,
    comparison: ComparisonObject | None = None,
) -> InsightSet:
    """Validate *insight_set* against all safety rules.

    Args:
        insight_set: The LLM-generated payload to validate.
        comparison:  Optional — when provided, source_signals provenance is also
                     checked against the metric keys in the comparison object.

    Returns:
        The unchanged *insight_set* on success.

    Raises:
        SafetyError: with a populated ``violations`` list if any rule fails.
    """
    violations: list[str] = []

    violations.extend(_check_disclaimer(insight_set))

    for idx, insight in enumerate(insight_set.insights):
        violations.extend(_check_single_action(insight.action, idx))
        violations.extend(_check_banned_terms(insight.summary, idx))
        if comparison is not None:
            violations.extend(_check_source_signals(insight.source_signals, comparison, idx))

    if violations:
        raise SafetyError(violations)

    return insight_set


def violations(
    insight_set: InsightSet,
    comparison: ComparisonObject | None = None,
) -> list[str]:
    """Return all safety violations without raising.  Empty list means clean."""
    try:
        check_insight_set(insight_set, comparison)
        return []
    except SafetyError as exc:
        return exc.violations
