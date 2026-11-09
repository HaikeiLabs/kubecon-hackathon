"""Governed friction-desk tools, their policy table and the tool-call governor.

Tools are agentware ``GovernedTool``s. Every call goes through ``Governor.call``,
which runs agentware's ``AuditedToolClient`` with a fail-closed evaluator and a
sanitizing auditor, and turns the decision into a ``GovernanceEvent``.
"""

from __future__ import annotations

from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from haikeilabs.agentware.middleware.audit import AuditFilter, AuditRecord, InMemoryAuditor
from haikeilabs.agentware.middleware.policy import PolicyEvaluator
from haikeilabs.agentware.middleware.tool_client import AuditedToolClient
from haikeilabs.agentware.middleware.types import Action, CallerContext, Decision
from haikeilabs.agentware.tools import KeiScope, KeiToolRegistration, Result, ToolRegistry
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import GovernanceEvent
from app.triage.policy import (
    ROLE_ORGANIZER,
    ROLE_TRIAGE_AGENT,
    FailClosedEvaluator,
    LocalPolicyEvaluator,
    SanitizingAuditor,
    ToolRule,
)

SERVICE = "friction-desk"
AUDIT_SOURCE = "friction-desk-triage"

LINK_CONCEPTS = "friction.link_concepts"
SEARCH_BUCKETS = "friction.search_buckets"
PROPOSE_BUCKET = "friction.propose_bucket"
ASSIGN_REPORT = "friction.assign_report"

_ID = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9:_.\-]+$")


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LinkConceptsArgs(_Args):
    text: str = Field(min_length=1, max_length=4000)


class SearchBucketsArgs(_Args):
    text: str = Field(min_length=1, max_length=4000)
    concept_ids: list[str] = Field(default_factory=list, max_length=50)
    k: int = Field(default=5, ge=1, le=20)


class ProposeBucketArgs(_Args):
    report_id: str = _ID
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=4000)
    concept_ids: list[str] = Field(default_factory=list, max_length=50)


class AssignReportArgs(_Args):
    """Assign to an existing bucket, or create one and assign (exactly one target)."""

    report_id: str = _ID
    bucket_id: str | None = Field(default=None, min_length=1, max_length=128)
    new_bucket_title: str | None = Field(default=None, min_length=1, max_length=200)
    new_bucket_summary: str = Field(default="", max_length=4000)
    concept_ids: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _one_target(self) -> AssignReportArgs:
        if (self.bucket_id is None) == (self.new_bucket_title is None):
            raise ValueError("exactly one of bucket_id or new_bucket_title is required")
        return self


class FrictionBackend(Protocol):
    """The subset of ``app.search`` the tools use (injected; fakes in tests)."""

    def link_concepts(self, client: Any, text: str) -> list[Any]: ...

    def search_candidate_buckets(
        self, client: Any, text: str, concept_ids: list[str], k: int = 5
    ) -> list[Any]: ...

    def create_bucket(
        self, client: Any, title: str, summary: str, concept_ids: list[str]
    ) -> Any: ...

    def assign_report(self, client: Any, report_id: str, bucket_id: str) -> Any: ...


class _FrictionTool:
    name: str
    description: str
    operation_class: str
    args_model: type[_Args]

    def __init__(self, backend: FrictionBackend, client: Any) -> None:
        self._backend = backend
        self._client = client

    def kei_scope(self) -> KeiScope:
        return KeiScope(
            source=SERVICE,
            service=SERVICE,
            operation_class=self.operation_class,
            required_capabilities=[f"{SERVICE}:{self.operation_class}"],
        )

    def execute(self, args: dict[str, Any]) -> Result:
        return Result(success=True, data=self.run(self.args_model.model_validate(args)))

    def run(self, args: Any) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError


class LinkConceptsTool(_FrictionTool):
    name = LINK_CONCEPTS
    description = "Link report text to friction ontology concepts (read-only)."
    operation_class = "read"
    args_model = LinkConceptsArgs

    def run(self, args: LinkConceptsArgs) -> Any:
        return self._backend.link_concepts(self._client, args.text)


class SearchBucketsTool(_FrictionTool):
    name = SEARCH_BUCKETS
    description = "Retrieve candidate issue buckets for report text (read-only)."
    operation_class = "read"
    args_model = SearchBucketsArgs

    def run(self, args: SearchBucketsArgs) -> Any:
        return self._backend.search_candidate_buckets(
            self._client, args.text, args.concept_ids, k=args.k
        )


class ProposeBucketTool(_FrictionTool):
    name = PROPOSE_BUCKET
    description = "Record a proposal for a new issue bucket. Does not create or assign."
    operation_class = "write"
    args_model = ProposeBucketArgs

    def run(self, args: ProposeBucketArgs) -> Any:
        return args.model_dump()


class AssignReportTool(_FrictionTool):
    name = ASSIGN_REPORT
    description = "Assign a report to a bucket, optionally creating the bucket first."
    operation_class = "write"
    args_model = AssignReportArgs

    def run(self, args: AssignReportArgs) -> Any:
        bucket_id = args.bucket_id
        if bucket_id is None:
            bucket = self._backend.create_bucket(
                self._client, args.new_bucket_title, args.new_bucket_summary, args.concept_ids
            )
            bucket_id = bucket.id
        return self._backend.assign_report(self._client, args.report_id, bucket_id)


TOOL_CLASSES: tuple[type[_FrictionTool], ...] = (
    LinkConceptsTool,
    SearchBucketsTool,
    ProposeBucketTool,
    AssignReportTool,
)

POLICY_RULES: dict[str, ToolRule] = {
    LINK_CONCEPTS: ToolRule(frozenset({ROLE_TRIAGE_AGENT, ROLE_ORGANIZER}), LinkConceptsArgs),
    SEARCH_BUCKETS: ToolRule(frozenset({ROLE_TRIAGE_AGENT, ROLE_ORGANIZER}), SearchBucketsArgs),
    PROPOSE_BUCKET: ToolRule(frozenset({ROLE_TRIAGE_AGENT, ROLE_ORGANIZER}), ProposeBucketArgs),
    ASSIGN_REPORT: ToolRule(frozenset({ROLE_ORGANIZER}), AssignReportArgs),
}


def build_registry(backend: FrictionBackend | None = None, client: Any = None) -> ToolRegistry:
    registry = ToolRegistry()
    for cls in TOOL_CLASSES:
        tool = cls(backend, client)  # type: ignore[arg-type]
        scope = tool.kei_scope()
        registration: KeiToolRegistration = {
            "service": SERVICE,
            "source": scope.source,
            "operation_class": scope.operation_class,
            "route": {"harness_executor": {"executor": AUDIT_SOURCE, "registration": tool.name}},
        }
        registry.register(tool, registration)
    return registry


def export_tool_manifest() -> str:
    """Deterministic Kei v3 tool manifest (written to backend/kei/tool-manifest.json)."""
    return build_registry().export_kei_tool_manifest() + "\n"


def _run_sync(coro: Coroutine[Any, Any, Any]) -> Any:
    """Drive ``AuditedToolClient.Execute`` to completion without an event loop.

    Our evaluator and tool functions are synchronous, so ``Execute`` never
    suspends; running it this way works from sync and async callers alike.
    """
    try:
        coro.send(None)
    except StopIteration as stop:
        return stop.value
    coro.close()
    raise RuntimeError("governed tool call suspended unexpectedly")


class _RecordingEvaluator:
    """Per-call evaluator that remembers the decision for the GovernanceEvent."""

    def __init__(self, inner: PolicyEvaluator) -> None:
        self._inner = inner
        self.decision: Decision | None = None

    def evaluate(self, tool_name: str, args: dict[str, Any], caller: CallerContext) -> Decision:
        self.decision = self._inner.evaluate(tool_name, args, caller)
        return self.decision


@dataclass
class GovernedCall:
    allowed: bool
    data: Any
    event: GovernanceEvent


class Governor:
    """Runs governed tool calls: fail-closed policy, sanitized audit, no call on deny."""

    def __init__(
        self,
        evaluator: PolicyEvaluator | None = None,
        auditor: InMemoryAuditor | None = None,
    ) -> None:
        self._evaluator = FailClosedEvaluator(evaluator)
        self._raw_auditor = auditor if auditor is not None else InMemoryAuditor()
        self._auditor = SanitizingAuditor(self._raw_auditor)

    def call(
        self,
        registry: ToolRegistry,
        tool_name: str,
        args: dict[str, Any],
        caller: CallerContext,
    ) -> GovernedCall:
        tool, found = registry.get(tool_name)
        recorder = _RecordingEvaluator(self._evaluator)
        client = AuditedToolClient(source=AUDIT_SOURCE, evaluator=recorder, auditor=self._auditor)

        def invoke(**_: Any) -> Any:
            if not found:
                raise LookupError(f"tool {tool_name!r} is not registered")
            result = tool.execute(args)
            if not result.success:
                raise RuntimeError(result.error or f"{tool_name} failed")
            return result.data

        try:
            data = _run_sync(
                client.Execute(
                    tool_name, args, caller.user_id, caller.session_id, None, invoke, caller
                )
            )
            allowed = True
        except PermissionError:
            data, allowed = None, False
        decision = recorder.decision
        assert decision is not None  # FailClosedEvaluator always returns a Decision
        event = GovernanceEvent(
            tool=tool_name,
            decision="allow" if allowed and decision.action == Action.ALLOW else "deny",
            rule=decision.rule,
            reason=decision.reason,
            at=datetime.now(UTC),
        )
        return GovernedCall(allowed=allowed, data=data, event=event)

    def audit_records(self, limit: int = 100) -> list[AuditRecord]:
        records = self._auditor.query(AuditFilter())
        return records[-limit:][::-1] if limit > 0 else []


def default_governor() -> Governor:
    return Governor(evaluator=LocalPolicyEvaluator(POLICY_RULES))
