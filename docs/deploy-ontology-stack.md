# Deploy guide: Conference Friction Desk ontology stack

This is a verbatim runbook for deploying the full ontology stack (ontology
artifacts + seed + concept search + governed triage + UI) to Kubernetes.
Follow it top to bottom. Do not skip the secrets step.

## Prerequisites

- Docker with `docker buildx` available (Docker Desktop works).
- `kubectl` installed and pointed at your cluster (set `KUBE_CONTEXT=...` if
  you do not want the default context).
- `helm` v3 installed.
- [`uv`](https://docs.astral.sh/uv/) installed (Python package runner).
- A container registry push image (`IMAGE_REPOSITORY`, e.g.
  `ghcr.io/<you>/friction-desk`).
- An Elasticsearch Cloud Serverless endpoint and API key. The app writes to
  and reads **v2 indices only**; any existing `friction-desk-*-v1` indices
  (Colin's data) are never touched.
- An OpenAI API key (triage uses `gpt-4.1-mini` by default).

## 1. Create the Kubernetes Secrets

The API keys come from **your own environment**. Never paste them into chat,
tickets, or commits.

```sh
kubectl -n kubecon-hackathon create secret generic friction-desk-elasticsearch \
  --from-literal=api-key="$ELASTICSEARCH_API_KEY"

kubectl -n kubecon-hackathon create secret generic friction-desk-openai \
  --from-literal=api-key="$OPENAI_API_KEY"
```

Both secrets must have a literal key named `api-key`. Re-run the commands
(with `--dry-run=client -o yaml | kubectl apply -f -`) to rotate keys.

## 2. Run the tests

```sh
make test
```

Unit tests do not require Elasticsearch or an OpenAI key.

## 3. Build and deploy

`make deploy` builds the API image with the repository root as build context
(so the image contains `ontology/build/` and `backend/seed/`) and upgrades the
Helm release.

```sh
make deploy \
  IMAGE_REPOSITORY=<registry>/friction-desk \
  ELASTICSEARCH_URL=https://my-vectordb-project-e7833d.es.us-east-1.aws.elastic.cloud:443
```

Wait for status: `make status`. To follow logs: `make logs`.

## 4. Create the app port-forward

```sh
make port-forward
```

This forwards `localhost:8080` to the API service. Leave it running.

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
  -d '{"text": "The wifi on the second floor of the venue keeps dropping out."}' | jq
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

## 7. Run the frontend locally

In a second terminal:

```sh
cd frontend
npm ci
VITE_API_BASE=http://localhost:8080 npm run dev
```

Open the printed local URL (usually http://localhost:5173).

## 8. Teardown

```sh
make destroy
```

This removes the Helm release and its namespace only. **External
Elasticsearch is never deleted**: your v1 indices stay untouched and the v2
indices survive a re-deploy (a fresh deploy reseeds only via the
`/api/admin/reset` call in step 5).

## Merge order for the stack

Branches stack bottom-up:

1. `fd/ontology`
2. `fd/search`
3. `fd/triage`
4. `fd/frontend`
5. `fd/helm-env` (this one)

Merge with `gh stack merge`, or merge via the GitHub UI starting at the
bottom of the stack and re-targeting the once-merged parents upward until
the last PR targets `main`.
