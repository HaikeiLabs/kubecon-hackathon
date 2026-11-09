# Conference Friction Desk teardown

Ownership is split deliberately: Terraform owns AWS resources only (the dedicated ECR repository and Secrets Manager secret metadata); Helm owns every Kubernetes object in the `kubecon-hackathon` namespace. The namespace already exists and is not managed, imported, created, or deleted by this stack.

## Remove the Kubernetes application

First remove the Helm release:

```sh
make destroy
```

This uninstalls the `friction-desk` release, including its Deployment, Service, and ExternalSecret mappings. The existing namespace is preserved. Namespace cleanup is not part of this project teardown: do not delete/recreate `kubecon-hackathon`. If a future owner explicitly requests namespace removal, handle it as a separate cluster-owner operation after confirming it is empty and no other workloads depend on it.

The ClusterSecretStore `aws-secrets-manager` and ExternalSecrets CRD are shared cluster prerequisites and are not removed. Hosted Elasticsearch and its indices/data are external and are never modified or deleted by Helm or Terraform.

## Remove the AWS resources

Only after reviewing the effect on other consumers, produce and inspect a saved destroy plan:

```sh
make plan-destroy-aws
make show-destroy-aws
```

If and only if that exact saved plan is approved, apply it interactively:

```sh
make apply-destroy-aws
```

The target requires the saved plan file and does not use `-auto-approve`.

The plan deletes the ECR repository (including its images) and schedules deletion of the two Secrets Manager secret metadata records. ECR force deletion is enabled only in this explicit destroy plan; do not apply it if repository images must be retained. Secrets Manager's configured recovery window is seven days. Secret values are never stored in Terraform state; coordinate any value retention/rotation needs with the approved secret owner before deleting metadata.

Neither the destroy plan nor any preceding Helm action manages the hosted Elasticsearch service or its indices/data.
