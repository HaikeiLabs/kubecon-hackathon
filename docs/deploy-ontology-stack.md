# Deploy guide: Conference Friction Desk ontology stack

This is a verbatim runbook for deploying the full ontology stack (ontology
artifacts + seed + concept search + governed triage + UI) to Kubernetes.
Follow it top to bottom. Do not skip the secrets step.

## Prerequisites

This runbook layers on Colin's AWS/Helm workflow (PR #7, `docs/miriah-handoff.md`).
Terraform (ECR, Secrets Manager wiring) must already be planned and applied
there as its own approved step; this runbook never runs Terraform.

- Docker with `docker buildx`, `kubectl`, `helm` v3, `terraform`, and
  [`uv`](https://docs.astral.sh/uv/).
- `kubectl` pointed at the cluster that has the `kubecon-hackathon` namespace.
- The Elasticsearch Cloud Serverless endpoint. The app writes to and reads
  `friction-desk-concepts-v1`, `friction-desk-reports-v2` and
  `friction-desk-buckets-v2` only; Colin's `friction-desk-reports-v1` and
  `friction-desk-buckets-v1` are never touched.
- Optional: an OpenAI API key for LLM triage. Without it triage uses its
  deterministic concept-overlap fallback, which is the demo default.

## 1. Secrets

The API keys come from **your own environment**. Never paste them into chat,
tickets, commits, Terraform arguments, or Helm values.

- Elasticsearch: populate Secrets Manager `kubecon-hackathon/friction-desk-elasticsearch`
  (key `api-key`) out-of-band, as in Colin's handoff. The chart's ExternalSecret
  syncs it into the `friction-desk-elasticsearch` Secret.
- OpenAI (optional): create a plain Kubernetes Secret and pass its name at release time:

```sh
kubectl -n kubecon-hackathon create secret generic friction-desk-openai \
  --from-literal=api-key="$OPENAI_API_KEY"
```

## 2. Run the tests

```sh
make test
```

Unit tests do not require Elasticsearch or an OpenAI key.

## 3. Build and deploy

`make deploy` builds the API image with the repository root as build context
(so the image contains `ontology/build/` and `backend/seed/`), builds the UI
image, and upgrades the Helm release. The image repository comes from
Terraform output.

```sh
make deploy ELASTICSEARCH_URL=https://<hosted-elasticsearch-endpoint> IMAGE_TAG=$(git rev-parse --short HEAD)
```

To enable LLM triage, re-run the release with the OpenAI secret:

```sh
helm upgrade friction-desk deploy/helm/friction-desk -n kubecon-hackathon --reuse-values \
  --set-string openai.apiKeySecretName=friction-desk-openai
```

Wait for status: `make status`. To follow logs: `make logs`.

## 4. Port-forward

```sh
make port-forward      # API on http://localhost:8080
make port-forward-ui   # UI (proxies /api) on http://localhost:8081
```

Leave them running.

## 5. Reset and seed the indices

On first deploy (and whenever you want to wipe app state), reseed the v2
indices from `backend/seed/`:

```sh
curl -X POST localhost:8080/api/admin/reset
```

## 6. Smoke test the API

Create a report (concept tagging + triage run synchronously):

```sh
curl -s -X POST localhost:8080/api/reports \
  -H 'Content-Type: application/json' \
  -d '{"description": "The wifi on the second floor of the venue keeps dropping out.", "location": "Level 2"}' | jq
```

List reports:

```sh
curl -s localhost:8080/api/reports | jq
```

Grab a report `id` from the list, then confirm the triage decision
(organizer-only governance):

```sh
# Allowed (organizer role) — expect 200
curl -s -X POST localhost:8080/api/reports/<id>/confirm \
  -H 'Content-Type: application/json' \
  -H 'X-Role: organizer' \
  -d '{"new_bucket_title": "Venue WiFi instability"}' | jq

# Without the role header — expect 403 with a governance deny
curl -s -X POST localhost:8080/api/reports/<id>/confirm \
  -H 'Content-Type: application/json' \
  -d '{}' | jq
```

## 7. Open the UI

Open http://localhost:8081 (from `make port-forward-ui`). For local frontend
development instead: `cd frontend && npm ci && VITE_API_BASE=http://localhost:8080 npm run dev`.

## 8. Teardown

```sh
make destroy
```

This uninstalls the Helm release only; see `docs/teardown.md` for AWS
resources. **External Elasticsearch is never deleted**: the v2 indices
survive a re-deploy and are only reseeded by the `/api/admin/reset` call in step 5.

## Merge order

1. #1 `fd/ontology` → #2 `fd/search` → #3 `fd/triage` → #4 `fd/frontend`
2. #5 `fd/eval-gold` (on #3) and the seed-data PR (on #2) any time after their parents
3. #7 `t206-ui-hosting` (Colin), then #6 `fd/helm-env` (this runbook, stacked on #7)

Merge bottom-up, re-targeting each child to `main` as its parent merges.
