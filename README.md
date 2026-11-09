# Conference Friction Desk

A conference feedback-to-fix demo. Attendee reports are anonymous; organizers review reports grouped into existing issue buckets or proposed as new buckets.

## Infrastructure ownership and safety

- `deploy/terraform` owns AWS resources only: dedicated ECR repository (`kei/kubecon-hackathon-friction-desk`) and metadata for two AWS Secrets Manager secrets.
- Helm owns all Kubernetes resources, including the app release and ExternalSecret mappings. The existing `kubecon-hackathon` namespace is neither managed nor imported by Terraform; deploy into it without creating or deleting it.
- The existing `aws-secrets-manager` `ClusterSecretStore` and ExternalSecrets CRD are referenced by chart resources and are not owned by this project.
- Hosted Elasticsearch and all its indices/data remain external; Terraform/Helm never create, modify, or delete them.
- Terraform declares secret metadata only. Populate the exact secrets `kubecon-hackathon/friction-desk-elasticsearch` (JSON property `api-key`) and `kubecon-hackathon/friction-desk-kea-runtime` (JSON property `KEI_RUNTIME_TOKEN`) through the approved secret-management process. Do not pass secret values to Terraform or Helm; values must never enter Terraform state. ExternalSecrets materialize Kubernetes Secrets in `kubecon-hackathon`.
- The Terraform backend uses the existing team bucket `kei-terraform-state-726299224953`, unique key `kubecon-hackathon/friction-desk/terraform.tfstate`, encryption, and S3 native locking. Initialize only after confirming access to this existing bucket.

## Prerequisites

Terraform 1.15.8, AWS credentials for the selected account/region, Helm 3, Docker Buildx, `kubectl` access to the existing cluster, Python 3.11+, `uv`, and access to the team's S3 state backend. The cluster must already have the healthy `aws-secrets-manager` ClusterSecretStore and ExternalSecrets CRD. Supply the hosted Elasticsearch HTTPS URL; its API key is managed out-of-band in Secrets Manager.

## Review before deployment

```sh
make test
make lint
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

`make deploy` only builds/pushes the image and installs/upgrades Helm; it does not run Terraform. Confirm the active Kubernetes context and that the ExternalSecrets have produced the expected Kubernetes Secrets before deploying. Terraform/Helm do not create secret values.

## Teardown

```sh
make destroy
```

This uninstalls the Helm release and its ExternalSecret resources. The namespace is preserved. Terraform destroy is a separate AWS-only operation; see [docs/teardown.md](docs/teardown.md) for the reviewed destroy-plan workflow and data-safety boundaries.

AWS teardown is separate and deliberate; see [docs/teardown.md](docs/teardown.md) for the explicit saved destroy-plan, review, and interactive apply steps. Terraform force-deletes ECR images only in that reviewed AWS teardown workflow. Hosted Elasticsearch and its data are never part of teardown. Secret values/rotation are controlled through the approved Secrets Manager process, not Terraform.

## Local access

```sh
make status
make port-forward
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
