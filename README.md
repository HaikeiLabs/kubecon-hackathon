# Conference Friction Desk

A conference feedback-to-fix demo. Attendee reports are anonymous; organizers review reports grouped into existing issue buckets or proposed as new buckets.

## Current foundation

- Python 3.11+ / FastAPI backend.
- Hosted Elasticsearch is the canonical report and bucket store; the app's Kubernetes deployment does not provision or delete Elasticsearch.
- A Helm release deploys the API into a dedicated `kubecon-hackathon` namespace on the existing Kubernetes cluster.
- The API currently provides anonymous report submission, report/bucket listing, lexical bucket search, and health probes. Model triage and the Kei runtime integration are the next backend milestone.
- No CI pipeline is introduced; `make` targets support local build, deploy, inspection, and teardown.

## Kubernetes prerequisites

- `kubectl`, Helm 3, Docker Buildx, Python 3.11+, `pytest`, and Ruff.
- Access to the existing cluster and a container registry it can pull from.
- A hosted Elasticsearch HTTPS endpoint and an API key scoped to `friction-desk-*` with index creation, read, and write privileges.
- A Kubernetes Secret named `friction-desk-elasticsearch` (or override `ELASTICSEARCH_SECRET_NAME`) in namespace `kubecon-hackathon`, with the API key under key `api-key`.

Do not put the API key in Helm values, command-line flags, git, or chat. Create/populate the Kubernetes Secret through the team's approved secret manager workflow. The chart expects the secret to exist before the API pod starts; it passes the key to the backend as `ELASTICSEARCH_API_KEY`.

## Deploy from a workstation

```sh
make test
make render
make deploy \
  IMAGE_REPOSITORY=registry.example.com/team/conference-friction-desk \
  ELASTICSEARCH_URL=https://your-deployment.example.es.io
```

`make deploy` builds and pushes the backend image, then installs/upgrades the Helm release. It uses the current Kubernetes context by default; specify `KUBE_CONTEXT=...` to target another context. The hosted cluster is accessed over HTTPS; Elasticsearch is not exposed through a Kubernetes Service.

Access the API locally:

```sh
make port-forward
curl http://localhost:8080/health/ready
curl -X POST http://localhost:8080/api/reports \
  -H 'content-type: application/json' \
  -d '{"description":"The accessible entrance near Hall B is blocked","location":"Hall B"}'
curl 'http://localhost:8080/api/buckets/search?q=accessible%20entrance'
```

## Tear down

```sh
make destroy
```

This removes the Helm release and deletes the dedicated `kubecon-hackathon` namespace. It does **not** delete the hosted Elasticsearch deployment or its data. The namespace is reserved for this project; do not point `NAMESPACE` at a shared namespace when using `make destroy`.

## API endpoints

- `GET /health/live` — process liveness.
- `GET /health/ready` — readiness, including Elasticsearch connectivity.
- `POST /api/reports` — submit an anonymous report. Identity/contact fields are rejected.
- `GET /api/reports` — list recent reports.
- `GET /api/buckets` — list issue buckets.
- `GET /api/buckets/search?q=...` — retrieve open candidate buckets with Elasticsearch lexical relevance. Agent triage and hybrid/vector search are not implemented yet.

The attendee UI and organizer UI will be added after the core backend and infrastructure boundary is established.
