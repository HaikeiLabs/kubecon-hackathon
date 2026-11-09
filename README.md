# Conference Friction Desk

A conference feedback-to-fix demo. Attendee reports are anonymous; organizers review reports grouped into existing issue buckets or proposed as new buckets.

## Infrastructure ownership and safety

- `deploy/terraform` owns AWS resources only: dedicated ECR repository (`kei/kubecon-hackathon-friction-desk`) and metadata for two AWS Secrets Manager secrets. The API and frontend images share that repository and are distinguished by tag (`<sha>` for the API, `frontend-<sha>` for the UI); no extra AWS resources are needed.
- Helm owns all Kubernetes resources, including the API and frontend Deployments/Services and ExternalSecret mappings. The existing `kubecon-hackathon` namespace is neither managed nor imported by Terraform; deploy into it without creating or deleting it.
- The existing `aws-secrets-manager` `ClusterSecretStore` and ExternalSecrets CRD are referenced by chart resources and are not owned by this project.
- Hosted Elasticsearch and all its indices/data remain external; Terraform/Helm never create, modify, or delete them.
- Terraform declares secret metadata only. Populate the exact secrets `kubecon-hackathon/friction-desk-elasticsearch` (JSON property `api-key`) and `kubecon-hackathon/friction-desk-kei-runtime` (JSON property `KEI_RUNTIME_TOKEN`) through the approved secret-management process. Do not pass secret values to Terraform or Helm; values must never enter Terraform state. ExternalSecrets (`external-secrets.io/v1`; the cluster does not serve `v1beta1`) materialize the `friction-desk-elasticsearch` Kubernetes Secret in `kubecon-hackathon`. The `friction-desk-kei-runtime` ExternalSecret is disabled by default (`keiRuntime.enabled: false`) until T201 provisions the runtime token; no workload consumes it yet. Once the token exists, enable it with `make release ... KEI_RUNTIME_ENABLED=true`.
- The Terraform backend uses the existing team bucket `kei-terraform-state-726299224953`, unique key `kubecon-hackathon/friction-desk/terraform.tfstate`, encryption, and S3 native locking. Initialize only after confirming access to this existing bucket.

## Prerequisites

Terraform 1.15.8, AWS credentials for the selected account/region, Helm 3, Docker Buildx, `kubectl` access to the existing cluster, Python 3.11+, `uv`, Node.js 22 with npm (frontend), and access to the team's S3 state backend. The cluster must already have the healthy `aws-secrets-manager` ClusterSecretStore and ExternalSecrets CRD. Supply the hosted Elasticsearch HTTPS URL; its API key is managed out-of-band in Secrets Manager.

## Review before deployment

```sh
make test
make lint
make frontend-build
make frontend-proxy-check   # local Docker only: builds the UI image, never pushes
make render
make tf-init
make tf-fmt
make tf-validate
make plan-aws AWS_REGION=us-east-1
make show-aws-plan
# Only after review and authorization:
make apply-aws
```

Terraform plans only AWS resources. The saved plan must be reviewed before the separate, interactive `make apply-aws`; no command uses `-auto-approve`. No secret values belong in `*.tfvars`, Terraform CLI arguments, Helm values, or source control.

## Deploy

The ECR repository must exist before Docker can push an image. After the reviewed AWS plan has been applied and the metadata-only Secrets Manager secrets populated out-of-band, push the image and install the Helm release:

```sh
# The reviewed make apply-aws step above creates ECR and empty secret metadata.
# Populate both secrets via the approved secret workflow; never pass values to Terraform/Helm.
make deploy ELASTICSEARCH_URL=https://your-deployment.example.es.io IMAGE_TAG=$(git rev-parse --short HEAD)
```

`make deploy` only builds/pushes the API (`$(IMAGE_TAG)`) and frontend (`frontend-$(IMAGE_TAG)`) images and installs/upgrades Helm; it does not run Terraform. Confirm the active Kubernetes context and that the ExternalSecrets have produced the expected Kubernetes Secrets before deploying. Terraform/Helm do not create secret values.

## Teardown

```sh
make destroy
```

This uninstalls the Helm release and its ExternalSecret resources. The namespace is preserved. Terraform destroy is a separate AWS-only operation; see [docs/teardown.md](docs/teardown.md) for the reviewed destroy-plan workflow and data-safety boundaries.

AWS teardown is separate and deliberate; see [docs/teardown.md](docs/teardown.md) for the explicit saved destroy-plan, review, and interactive apply steps. Terraform force-deletes ECR images only in that reviewed AWS teardown workflow. Hosted Elasticsearch and its data are never part of teardown. Secret values/rotation are controlled through the approved Secrets Manager process, not Terraform.

## Frontend hosting

The React UI ships as a static image (`frontend/Dockerfile`: Vite build served by unprivileged nginx). It is same-origin with the API: the browser only calls relative `/api/*` and `/health/*`, and nginx (`frontend/nginx/default.conf.template`) proxies those paths unchanged to `API_UPSTREAM`, which Helm sets to `http://<release>-api:8080` (`http://friction-desk-api:8080` by default). Every other path serves the built assets, falling back to `index.html`; `/frontend-healthz` is the frontend's own probe. Production builds force `VITE_USE_MOCK=false`. No CORS configuration is needed or present.

The frontend Service is `ClusterIP` only. There is no Ingress, LoadBalancer, or DNS; public exposure needs separate approval. Demo access is via port-forward:

```sh
make port-forward-ui   # UI on http://localhost:8081, with /api and /health proxied to the API
```

`make frontend-proxy-check` verifies the proxy contract locally: it builds the frontend image, runs it read-only beside a stub API on a private Docker network, and asserts SPA fallback, asset 404s, and that `/api/*` and `/health/*` reach the upstream with method, path, query, and body intact. It does not test the real API, Elasticsearch, or the cluster.

### UI/API contract status

The static contract is partial; the UI does not claim more than the API supports:

- Supported by the live API: submit report, list reports, list buckets, bucket search.
- Triage in the organizer view is computed in the browser: lexical `GET /api/buckets/search` candidates plus local heuristics (`frontend/src/triage.ts`). It is not agent or semantic triage.
- Confirming/correcting an organizer assignment is **not** supported by the API. Against the live API the UI shows an explicit error; it works only in mock mode (`npm run dev:mock`), which the production image never uses.

## Local access

```sh
make status
make port-forward-ui   # UI: http://localhost:8081
make port-forward      # API directly: http://localhost:8080
curl http://localhost:8080/health/ready
curl -X POST http://localhost:8080/api/reports \
  -H 'content-type: application/json' \
  -d '{"description":"The accessible entrance near Hall B is blocked","location":"Hall B"}'
curl 'http://localhost:8080/api/buckets/search?q=accessible%20entrance'
```

## API endpoints

- `GET /health/live` — process liveness.
- `GET /health/ready` — readiness, including Elasticsearch connectivity.
- `POST /api/reports` — submit an anonymous report. Identity/contact fields are rejected.
- `GET /api/reports` — list recent reports.
- `GET /api/buckets` — list issue buckets.
- `GET /api/buckets/search?q=...` — retrieve open candidate buckets with Elasticsearch lexical relevance. Agent triage and hybrid/vector search are not implemented yet.
