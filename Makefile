SHELL := /bin/bash

TERRAFORM_DIR := deploy/terraform
CHART := deploy/helm/friction-desk
RELEASE := friction-desk
NAMESPACE := kubecon-hackathon
IMAGE_TAG ?= $(shell git rev-parse --short HEAD)
AWS_REGION ?= us-east-1
ELASTICSEARCH_URL ?=

.PHONY: help test lint build provision release deploy destroy plan-destroy-aws status logs port-forward render tf-init tf-fmt tf-validate tf-plan

help:
	@echo "Conference Friction Desk - AWS Terraform and Kubernetes Helm workflow"
	@echo "  make test / lint / render"
	@echo "  make tf-init tf-fmt tf-validate tf-plan"
	@echo "  make provision                       Create AWS ECR/secret metadata"
	@echo "  make build                           Build/push after ECR exists"
	@echo "  make release ELASTICSEARCH_URL=...   Install/upgrade the Helm release"
	@echo "  make deploy ELASTICSEARCH_URL=...    Run provision, build, then release"
	@echo "  make destroy                         Uninstall the Helm release"
	@echo "  make plan-destroy-aws               Plan destruction of AWS resources"
	@echo "  make status / logs / port-forward"
	@echo "Terraform owns AWS resources only; Helm owns all Kubernetes resources."

test:
	cd backend && uv run --extra dev pytest tests

lint:
	cd backend && uv run --extra dev ruff check .

build:
	@test -n "$(IMAGE_REPOSITORY)" || (echo "Set IMAGE_REPOSITORY to the ECR repository URI" >&2; exit 2)
	docker buildx build --platform linux/amd64 --push --tag $(IMAGE_REPOSITORY):$(IMAGE_TAG) --file backend/Dockerfile backend

tf-init:
	terraform -chdir=$(TERRAFORM_DIR) init

tf-fmt:
	terraform -chdir=$(TERRAFORM_DIR) fmt -check -recursive

tf-validate:
	terraform -chdir=$(TERRAFORM_DIR) validate

tf-plan:
	terraform -chdir=$(TERRAFORM_DIR) plan -var="aws_region=$(AWS_REGION)"

provision:
	terraform -chdir=$(TERRAFORM_DIR) apply -var="aws_region=$(AWS_REGION)"

release:
	@test -n "$(ELASTICSEARCH_URL)" || (echo "Set ELASTICSEARCH_URL to the hosted HTTPS endpoint" >&2; exit 2)
	helm upgrade --install $(RELEASE) $(CHART) --namespace $(NAMESPACE) \
		--set-string image.repository=$$(terraform -chdir=$(TERRAFORM_DIR) output -raw image_repository) \
		--set-string image.tag=$(IMAGE_TAG) \
		--set-string elasticsearch.url=$(ELASTICSEARCH_URL)

deploy:
	@test -n "$(ELASTICSEARCH_URL)" || (echo "Set ELASTICSEARCH_URL to the hosted HTTPS endpoint" >&2; exit 2)
	$(MAKE) provision AWS_REGION=$(AWS_REGION)
	$(MAKE) build IMAGE_REPOSITORY=$$(terraform -chdir=$(TERRAFORM_DIR) output -raw image_repository) IMAGE_TAG=$(IMAGE_TAG)
	$(MAKE) release ELASTICSEARCH_URL=$(ELASTICSEARCH_URL) IMAGE_TAG=$(IMAGE_TAG)

destroy:
	helm uninstall $(RELEASE) --namespace $(NAMESPACE)

plan-destroy-aws:
	terraform -chdir=$(TERRAFORM_DIR) plan -destroy -out=destroy-aws.tfplan -var="allow_ecr_force_delete=true"

status:
	kubectl get all -n $(NAMESPACE)

logs:
	kubectl logs -n $(NAMESPACE) deployment/$(RELEASE)-api --follow

port-forward:
	kubectl port-forward -n $(NAMESPACE) service/$(RELEASE)-api 8080:8080

render:
	helm template $(RELEASE) $(CHART) --namespace $(NAMESPACE) \
		--set-string image.repository=example.invalid/friction-desk \
		--set-string elasticsearch.url=https://example.invalid
