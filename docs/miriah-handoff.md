# Miriah handoff

## Current integration and runtime status

T202 source integration is not gated on deployment. Backend source is available locally on this branch from base commit `0863048`; this branch includes the backend API scaffold and the IaC/Helm deployment declarations. The frontend source was reported as untracked in the shared `kubecon-hackathon` worktree and is not integrated here. Do not treat this IaC commit as a frontend source merge.

The `kubecon-hackathon` namespace exists but has no pods/resources; the application is **not deployed**. Hosted Elasticsearch is external. The Kei installation record is pending/unverified; no runtime deployment/bootstrap/heartbeat/bind is confirmed, and agent creation remains gated on that runtime lifecycle. Do not claim a working runtime or deployed app.

The prior demo handoff reports synthetic data of 3 buckets and 5 reports, with no `semantic_content` inference and no credentials in documentation. Verify that dataset directly before relying on it; this branch has no seed/reset command. Backend tests use an in-process `FakeElasticsearch`; that is a test double, not a deployed API mock mode. A typed frontend mock fixture is part of the frontend plan, but no frontend/mock implementation is present in this branch.

## Setup, test, and build commands

Backend checks:

```sh
cd backend
uv run --extra dev pytest tests
uv run --extra dev ruff check .
```

For the AWS/Helm path, first review Terraform's AWS-only plan and apply it as a separate approved step. Then populate the two Secrets Manager values out-of-band, and build/deploy:

```sh
make tf-init tf-fmt tf-validate
make plan-aws AWS_REGION=us-east-1
make show-aws-plan
# Only after review/authorization: make apply-aws
# Populate the approved Secrets Manager values outside Terraform:
# kubecon-hackathon/friction-desk-elasticsearch (api-key)
# kubecon-hackathon/friction-desk-kei-runtime (KEI_RUNTIME_TOKEN)
make deploy ELASTICSEARCH_URL=https://<hosted-elasticsearch-endpoint> IMAGE_TAG=$(git rev-parse --short HEAD)
```

`make deploy` builds/pushes the API image and installs/upgrades the Helm release; it does not run Terraform. Check README and [the teardown guide](teardown.md) for ownership and safe removal. Secret values must never be passed in Terraform arguments or Helm values.

## Reviewable T199 follow-ups

- Add/review retry handling for triage failures.
- Validate organizer corrections before persisting them.
- Add organizer announcements/feedback for relevant state changes.
- Test the core flow with assistive technology, in addition to keyboard/accessibility checks.

These remain follow-up work; they are not completed by the IaC changes. Coordinate frontend transfer and API-contract review with the source owner, then run the combined UI/backend checks before source merge. Deployment remains a separate operational decision.
