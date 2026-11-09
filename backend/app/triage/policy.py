"""Local deny-by-default policy for the triage agent's tools.

Everything here fails closed: an unknown tool, a missing caller identity, a role
that is not on the tool's allow list, malformed arguments, an absent evaluator,
or an evaluator that raises all produce a DENY decision. The local evaluator
implements agentware's ``PolicyEvaluator`` protocol, so a ``KeiProxyEvaluator``
can be dropped into ``FailClosedEvaluator`` later without touching callers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from haikeilabs.agentware.middleware.audit import AuditFilter, Auditor, AuditRecord
from haikeilabs.agentware.middleware.policy import PolicyEvaluator
from haikeilabs.agentware.middleware.types import Action, CallerContext, Decision
from pydantic import BaseModel, ValidationError

ROLE_TRIAGE_AGENT = "triage-agent"
ROLE_ORGANIZER = "organizer"


@dataclass(frozen=True)
class ToolRule:
    """Who may call a tool and what its arguments must look like."""

    allowed_roles: frozenset[str]
    args_model: type[BaseModel]


def deny(rule: str, reason: str) -> Decision:
    return Decision(action=Action.DENY, rule=rule, reason=reason)


class LocalPolicyEvaluator:
    """Role-based, deny-by-default evaluator over an explicit tool table."""

    def __init__(self, rules: dict[str, ToolRule]) -> None:
        self._rules = dict(rules)

    def evaluate(self, tool_name: str, args: dict[str, Any], caller: CallerContext) -> Decision:
        if not isinstance(caller, CallerContext) or not caller.user_id or not caller.role:
            return deny("identity-missing", "caller identity or role is missing")
        rule = self._rules.get(tool_name)
        if rule is None:
            return deny("tool-unknown", f"tool {tool_name!r} is not governed")
        if caller.role not in rule.allowed_roles:
            return deny("role-not-allowed", f"role {caller.role!r} may not call {tool_name}")
        if not isinstance(args, dict):
            return deny("args-invalid", "tool arguments must be an object")
        try:
            rule.args_model.model_validate(args)
        except ValidationError as exc:
            return deny("args-invalid", f"{exc.error_count()} invalid argument(s)")
        return Decision(
            action=Action.ALLOW,
            rule=f"role:{caller.role}",
            reason=f"role {caller.role!r} is allowed to call {tool_name}",
        )


class FailClosedEvaluator:
    """Wraps any PolicyEvaluator so that only an explicit ALLOW lets a call through.

    ``AuditedToolClient`` allows every call when it has no evaluator and lets an
    evaluator exception escape before auditing; this wrapper closes both gaps.
    """

    def __init__(self, inner: PolicyEvaluator | None) -> None:
        self._inner = inner

    def evaluate(self, tool_name: str, args: dict[str, Any], caller: CallerContext) -> Decision:
        if self._inner is None:
            return deny("evaluator-unavailable", "no policy evaluator is configured")
        try:
            decision = self._inner.evaluate(tool_name, args, caller)
        except Exception as exc:  # noqa: BLE001 - any evaluator failure must deny
            return deny("evaluator-error", f"policy evaluator failed: {type(exc).__name__}")
        if not isinstance(decision, Decision):
            return deny("evaluator-error", "policy evaluator returned no decision")
        if decision.action != Action.ALLOW:
            return replace(
                decision,
                action=Action.DENY,
                rule=decision.rule or "denied",
                reason=decision.reason or "denied by policy",
            )
        return decision


def sanitize_args(args: Any) -> dict[str, Any]:
    """Keep identifiers, replace free text with its length. Never store report text."""
    if not isinstance(args, dict):
        return {"_type": type(args).__name__}
    clean: dict[str, Any] = {}
    for key, value in args.items():
        key = str(key)[:64]
        if key.endswith("_id") and isinstance(value, str):
            clean[key] = value[:128]
        elif key.endswith("_ids") and isinstance(value, list):
            clean[key] = [str(v)[:128] for v in value[:50]]
        elif isinstance(value, str):
            clean[key] = {"len": len(value)}
        elif isinstance(value, bool | int | float) or value is None:
            clean[key] = value
        else:
            clean[key] = {"_type": type(value).__name__}
    return clean


class SanitizingAuditor:
    """Auditor decorator: records sanitized arguments, never the raw ones."""

    def __init__(self, inner: Auditor) -> None:
        self._inner = inner

    def record(self, record: AuditRecord) -> None:
        self._inner.record(replace(record, args=sanitize_args(record.args)))

    def query(self, filter: AuditFilter) -> list[AuditRecord]:
        return self._inner.query(filter)
