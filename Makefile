SHELL := /bin/bash

RELEASE ?= friction-desk
NAMESPACE ?= kubecon-hackathon
CHART := deploy/helm/friction-desk
IMAGE_REPOSITORY ?=
IMAGE_TAG ?= $(shell git rev-parse --short HEAD)
PLATFORMS ?= linux/amd64
ELASTICSEARCH_URL ?=
ELASTICSEARCH_SECRET_NAME ?= friction-desk-elasticsearch
KUBE_CONTEXT ?=

KUBECTL_CONTEXT_ARGS = $(if $(KUBE_CONTEXT),--context $(KUBE_CONTEXT),)
HELM_CONTEXT_ARGS = $(if $(KUBE_CONTEXT),--kube-context $(KUBE_CONTEXT),)

.PHONY: help test lint build deploy status logs port-forward destroy render

help:
	@echo "Conference Friction Desk - local Kubernetes workflow"
	@echo ""
	@echo "Required for deploy: IMAGE_REPOSITORY, ELASTICSEARCH_URL, and a Kubernetes Secret"
	@echo "named ELASTICSEARCH_SECRET_NAME with key 'api-key' (unless using an unauthenticated endpoint)."
	@echo ""
	@echo "  make test                                      Run backend unit tests"
	@echo "  make lint                                      Run Ruff"
	@echo "  make build IMAGE_REPOSITORY=...                Build and push API image"
	@echo "  make deploy IMAGE_REPOSITORY=... ELASTICSEARCH_URL=https://..."
	@echo "  make status                                    Show release and pods"
	@echo "  make logs                                      Follow API logs"
	@echo "  make port-forward                              Forward API to localhost:8080"
	@echo "  make render                                    Render Helm templates locally"
	@echo "  make destroy                                   Remove release and its dedicated namespace"
	@echo ""
	@echo "Set KUBE_CONTEXT=... to target a specific cluster; defaults to current context."

.PHONY: test
test:
	cd backend && uv run --extra dev pytest tests

.PHONY: lint
lint:
	cd backend && uv run --extra dev ruff check .

.PHONY: build
build:
	@test -n "$(IMAGE_REPOSITORY)" || (echo "Set IMAGE_REPOSITORY" >&2; exit 2)
	docker buildx build --platform $(PLATFORMS) --push \
		--tag $(IMAGE_REPOSITORY):$(IMAGE_TAG) \
		--file backend/Dockerfile backend

.PHONY: deploy
deploy: build
	@test -n "$(ELASTICSEARCH_URL)" || (echo "Set ELASTICSEARCH_URL to the hosted HTTPS endpoint" >&2; exit 2)
	helm upgrade --install $(RELEASE) $(CHART) \
		$(HELM_CONTEXT_ARGS) \
		--namespace $(NAMESPACE) --create-namespace \
		--set-string image.repository=$(IMAGE_REPOSITORY) \
		--set-string image.tag=$(IMAGE_TAG) \
		--set-string elasticsearch.url=$(ELASTICSEARCH_URL) \
		--set-string elasticsearch.apiKeySecretName=$(ELASTICSEARCH_SECRET_NAME) \
		--wait --timeout 5m

.PHONY: status
status:
	kubectl $(KUBECTL_CONTEXT_ARGS) get all,pvc -n $(NAMESPACE)

.PHONY: logs
logs:
	kubectl $(KUBECTL_CONTEXT_ARGS) logs -n $(NAMESPACE) deployment/$(RELEASE)-api --follow

.PHONY: port-forward
port-forward:
	kubectl $(KUBECTL_CONTEXT_ARGS) port-forward -n $(NAMESPACE) service/$(RELEASE)-api 8080:8080

.PHONY: render
render:
	helm template $(RELEASE) $(CHART) \
		--namespace $(NAMESPACE) \
		--set-string image.repository=example.invalid/friction-desk \
		--set-string elasticsearch.url=https://example.invalid

.PHONY: destroy
destroy:
	@echo "Removing Helm release and dedicated namespace $(NAMESPACE); external Elasticsearch is NOT deleted."
	helm uninstall $(RELEASE) $(HELM_CONTEXT_ARGS) --namespace $(NAMESPACE) || true
	kubectl $(KUBECTL_CONTEXT_ARGS) delete namespace $(NAMESPACE) --ignore-not-found=true --wait=true
