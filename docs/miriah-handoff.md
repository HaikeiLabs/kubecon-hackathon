# Miriah handoff

## Current integration and runtime status

T202 source integration is not gated on deployment. Backend source is available locally on this branch from base commit `0863048`; this branch includes the backend API scaffold and the IaC/Helm deployment declarations. The React frontend (attendee report and organizer inbox, commit `e26a572`) is now in source, and T206 adds its production hosting: a static nginx image and a Helm-managed frontend Deployment/Service that proxies same-origin `/api/*` and `/health/*` to the API Service. Hosting is declared only; no frontend image has been pushed or deployed.

The `kubecon-hackathon` namespace exists but has no pods/resources; the application is **not deployed**. Hosted Elasticsearch is external. The Kei installation record is pending/unverified; no runtime deployment/bootstrap/heartbeat/bind is confirmed, and agent creation remains gated on that runtime lifecycle. Do not claim a working runtime or deployed app.

The prior demo handoff reports synthetic data of 3 buckets and 5 reports, with no `semantic_content` inference and no credentials in documentation. Verify that dataset directly before relying on it; this branch has no seed/reset command. Backend tests use an in-process `FakeElasticsearch`; that is a test double, not a deployed API mock mode. The frontend has a typed mock store (`frontend/src/mock.ts`) used only by `npm run dev:mock`; the production image is built with `VITE_USE_MOCK=false`.

## UI/API contract status

Partial. Submit report, list reports, list buckets, and bucket search use the live API. Organizer triage is computed in the browser from lexical bucket search plus local heuristics; it is not agent/semantic triage. Confirming an organizer assignment is unsupported by the API: the live UI shows an explicit error, and only mock mode demonstrates it. Do not present triage or assignment as backend features.

## Setup, test, and build commands

Backend checks:

```sh
cd backend
uv run --extra dev pytest tests
uv run --extra dev ruff check .
```

Frontend checks (from the repo root):

```sh
make frontend-build          # npm ci, tsc, vite build
make frontend-proxy-check    # local Docker: SPA fallback + /api, /health proxy to a stub API; no push
make render                  # Helm render with placeholder values
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

`make deploy` builds/pushes the API image (`<sha>`) and frontend image (`frontend-<sha>`) to the same ECR repository and installs/upgrades the Helm release; it does not run Terraform. After deployment, demo the UI privately with `make port-forward-ui` (http://localhost:8081); the frontend Service is ClusterIP with no Ingress/DNS. Check README and [the teardown guide](teardown.md) for ownership and safe removal. Secret values must never be passed in Terraform arguments or Helm values.

## Reviewable T199 follow-ups

- Add/review retry handling for triage failures.
- Validate organizer corrections before persisting them.
- Add organizer announcements/feedback for relevant state changes.
- Test the core flow with assistive technology, in addition to keyboard/accessibility checks.

These remain follow-up work; they are not completed by the IaC changes. Backend endpoints for organizer assignment and server-side triage are also open; until they exist the UI contract stays partial as described above. Deployment remains a separate operational decision.
