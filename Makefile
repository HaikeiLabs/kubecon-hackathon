SHELL := /bin/bash

TERRAFORM_DIR := deploy/terraform
CHART := deploy/helm/friction-desk
RELEASE := friction-desk
NAMESPACE := kubecon-hackathon
IMAGE_TAG ?= $(shell git rev-parse --short HEAD)
# Frontend shares the API's ECR repository; the tag prefix keeps images distinct.
FRONTEND_IMAGE_TAG ?= frontend-$(IMAGE_TAG)
AWS_REGION ?= us-east-1
ELASTICSEARCH_URL ?=
# Kei runtime ExternalSecret stays off until T201 populates its token.
KEI_RUNTIME_ENABLED ?= false

.PHONY: help test lint frontend-build frontend-proxy-check build build-api build-frontend release deploy destroy plan-aws show-aws-plan apply-aws plan-destroy-aws show-destroy-aws apply-destroy-aws status logs port-forward port-forward-ui render tf-init tf-fmt tf-validate

help:
	@echo "Conference Friction Desk - AWS Terraform and Kubernetes Helm workflow"
	@echo "  make test / lint / render"
	@echo "  make frontend-build                  Type-check and build the UI"
	@echo "  make frontend-proxy-check            Local Docker check of UI same-origin proxy"
	@echo "  make tf-init tf-fmt tf-validate"
	@echo "  make plan-aws AWS_REGION=...         Save AWS provision plan"
	@echo "  make show-aws-plan                   Review saved provision plan"
	@echo "  make apply-aws                       Interactively approve saved plan"
	@echo "  make build                           Build/push API and UI images after ECR exists"
	@echo "  make release ELASTICSEARCH_URL=...   Install/upgrade the Helm release"
	@echo "  make deploy ELASTICSEARCH_URL=...    Build and install; no Terraform apply"
	@echo "  make port-forward-ui                 UI (and proxied API) on http://localhost:8081"
	@echo "  make destroy                         Uninstall the Helm release"
	@echo "  make plan-destroy-aws                Save AWS destroy plan"
	@echo "  make show-destroy-aws / apply-destroy-aws"
	@echo "Terraform owns AWS resources only; Helm owns all Kubernetes resources."

test:
	cd backend && uv run --extra dev pytest tests

lint:
	cd backend && uv run --extra dev ruff check .

frontend-build:
	cd frontend && npm ci && npm run build

# Builds the production UI image locally (no push) and verifies nginx serves the
# SPA and proxies /api/* and /health/* to a stub upstream. Requires Docker.
frontend-proxy-check:
	scripts/check-frontend-proxy.sh

build: build-api build-frontend

build-api:
	@test -n "$(IMAGE_REPOSITORY)" || (echo "Set IMAGE_REPOSITORY to the ECR repository URI" >&2; exit 2)
	docker buildx build --platform linux/amd64 --push --tag $(IMAGE_REPOSITORY):$(IMAGE_TAG) --file backend/Dockerfile backend

build-frontend:
	@test -n "$(IMAGE_REPOSITORY)" || (echo "Set IMAGE_REPOSITORY to the ECR repository URI" >&2; exit 2)
	docker buildx build --platform linux/amd64 --push --tag $(IMAGE_REPOSITORY):$(FRONTEND_IMAGE_TAG) --file frontend/Dockerfile frontend

tf-init:
	terraform -chdir=$(TERRAFORM_DIR) init

tf-fmt:
	terraform -chdir=$(TERRAFORM_DIR) fmt -check -recursive

tf-validate:
	terraform -chdir=$(TERRAFORM_DIR) validate

plan-aws:
	terraform -chdir=$(TERRAFORM_DIR) plan -out=friction-desk.tfplan -var="aws_region=$(AWS_REGION)"

show-aws-plan:
	terraform -chdir=$(TERRAFORM_DIR) show friction-desk.tfplan

apply-aws:
	@test -f $(TERRAFORM_DIR)/friction-desk.tfplan || (echo "Run make plan-aws and review it first" >&2; exit 2)
	terraform -chdir=$(TERRAFORM_DIR) apply friction-desk.tfplan

release:
	@test -n "$(ELASTICSEARCH_URL)" || (echo "Set ELASTICSEARCH_URL to the hosted HTTPS endpoint" >&2; exit 2)
	helm upgrade --install $(RELEASE) $(CHART) --namespace $(NAMESPACE) \
		--set-string image.repository=$$(terraform -chdir=$(TERRAFORM_DIR) output -raw image_repository) \
		--set-string image.tag=$(IMAGE_TAG) \
		--set-string frontend.image.tag=$(FRONTEND_IMAGE_TAG) \
		--set keiRuntime.enabled=$(KEI_RUNTIME_ENABLED) \
		--set-string elasticsearch.url=$(ELASTICSEARCH_URL)

deploy:
	@test -n "$(ELASTICSEARCH_URL)" || (echo "Set ELASTICSEARCH_URL to the hosted HTTPS endpoint" >&2; exit 2)
	$(MAKE) build IMAGE_REPOSITORY=$$(terraform -chdir=$(TERRAFORM_DIR) output -raw image_repository) IMAGE_TAG=$(IMAGE_TAG)
	$(MAKE) release ELASTICSEARCH_URL=$(ELASTICSEARCH_URL) IMAGE_TAG=$(IMAGE_TAG) FRONTEND_IMAGE_TAG=$(FRONTEND_IMAGE_TAG) KEI_RUNTIME_ENABLED=$(KEI_RUNTIME_ENABLED)

destroy:
	helm uninstall $(RELEASE) --namespace $(NAMESPACE)

plan-destroy-aws:
	terraform -chdir=$(TERRAFORM_DIR) plan -destroy -out=destroy-aws.tfplan -var="allow_ecr_force_delete=true"

show-destroy-aws:
	terraform -chdir=$(TERRAFORM_DIR) show destroy-aws.tfplan

apply-destroy-aws:
	@test -f $(TERRAFORM_DIR)/destroy-aws.tfplan || (echo "Run make plan-destroy-aws and review it first" >&2; exit 2)
	terraform -chdir=$(TERRAFORM_DIR) apply destroy-aws.tfplan

status:
	kubectl get all -n $(NAMESPACE)

logs:
	kubectl logs -n $(NAMESPACE) deployment/$(RELEASE)-api --follow

port-forward:
	kubectl port-forward -n $(NAMESPACE) service/$(RELEASE)-api 8080:8080

port-forward-ui:
	kubectl port-forward -n $(NAMESPACE) service/$(RELEASE)-frontend 8081:80

render:
	helm template $(RELEASE) $(CHART) --namespace $(NAMESPACE) \
		--set-string image.repository=example.invalid/friction-desk \
		--set-string frontend.image.tag=frontend-example \
		--set keiRuntime.enabled=$(KEI_RUNTIME_ENABLED) \
		--set-string elasticsearch.url=https://example.invalid
