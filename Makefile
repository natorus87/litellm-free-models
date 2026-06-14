# =============================================================================
# LiteLLM Free-Models Proxy – Makefile
# =============================================================================

.PHONY: help docker-build docker-run docker-stop k8s-apply k8s-delete \
        k8s-secret k8s-logs k8s-pods check-config render-config test \
        lint format lint-fix pre-commit-run install-dev

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ─── Config-Render-Pipeline ─────────────────────────────────────────────────

render-config: ## Render config.template.yaml -> config.yaml
	@python3 render-config.py

render-config-dry: ## Dry-run render (no writes)
	@python3 render-config.py --dry-run

k8s-configmap: render-config ## Regenerate k8s/configmap.yaml from rendered config.yaml
	@python3 -c "\
import sys; \
c = open('config.yaml').read(); \
indented = '    ' + c.replace(chr(10), chr(10) + '    ').rstrip('    ') + chr(10); \
out = 'apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: litellm-config\n  namespace: litellm-free-models\n  labels:\n    app.kubernetes.io/name: litellm-free-models\n    app.kubernetes.io/component: proxy\ndata:\n  config.yaml: |\n' + indented; \
open('k8s/configmap.yaml', 'w').write(out)" 
	@echo "k8s/configmap.yaml aktualisiert ($$(wc -l < k8s/configmap.yaml) Zeilen)"

# ─── Docker ─────────────────────────────────────────────────────────────────

docker-build: ## Build the custom Docker image
	docker build -t litellm-free-models .

docker-run: docker-build render-config ## Run with Docker using local .env file
	docker run -d \
		--name litellm-free-models \
		-p 4000:4000 \
		--env-file .env \
		litellm-free-models

docker-compose-up: render-config ## Start with docker-compose
	docker compose --env-file .env up -d

docker-compose-down: ## Stop docker-compose
	docker compose down

docker-stop: ## Stop and remove the container
	docker rm -f litellm-free-models 2>/dev/null || true

docker-logs: ## Follow logs
	docker logs -f litellm-free-models

# ─── Kubernetes ─────────────────────────────────────────────────────────────

k8s-namespace: ## Create namespace
	kubectl apply -f k8s/namespace.yaml

k8s-secret: ## Create K8s secret from .env file
	@echo "Creating secret from .env file..."
	kubectl create secret generic litellm-secrets \
		--namespace litellm-free-models \
		--from-env-file=.env \
		--dry-run=client -o yaml | kubectl apply -f -

k8s-apply: k8s-namespace k8s-secret render-config ## Deploy everything to K8s
	kubectl apply -f k8s/configmap.yaml
	kubectl apply -f k8s/deployment.yaml
	kubectl apply -f k8s/service.yaml
	kubectl apply -f k8s/postgres-pvc.yaml
	kubectl apply -f k8s/postgres-deployment.yaml
	kubectl apply -f k8s/postgres-service.yaml
	# kubectl apply -f k8s/ingress.yaml  # Uncomment when domain is configured
	@echo ""
	@echo "Deployment complete! Check status:"
	@echo "  kubectl get pods -n litellm-free-models"

k8s-delete: ## Remove everything from K8s
	kubectl delete -f k8s/ingress.yaml 2>/dev/null || true
	kubectl delete -f k8s/service.yaml
	kubectl delete -f k8s/postgres-service.yaml
	kubectl delete -f k8s/postgres-deployment.yaml 2>/dev/null || true
	kubectl delete -f k8s/deployment.yaml 2>/dev/null || true
	kubectl delete -f k8s/configmap.yaml 2>/dev/null || true
	kubectl delete -f k8s/postgres-pvc.yaml 2>/dev/null || true
	kubectl delete secret litellm-secrets -n litellm-free-models 2>/dev/null || true
	kubectl delete namespace litellm-free-models 2>/dev/null || true

k8s-pods: ## List pods
	kubectl get pods -n litellm-free-models -o wide

k8s-logs: ## Follow pod logs
	@kubectl logs -n litellm-free-models -l app=litellm-proxy -f

k8s-restart: ## Rollout restart
	kubectl rollout restart deployment litellm-proxy -n litellm-free-models

# ─── Utilities ──────────────────────────────────────────────────────────────

check-config: render-config ## Validate the config.yaml (dry-run with litellm)
	@echo "Starting litellm in dry-run to validate config..."
	docker run --rm -v $(PWD)/config.yaml:/app/config.yaml \
		ghcr.io/berriai/litellm:main-latest \
		--config /app/config.yaml --port 4000 &
	@sleep 3
	@curl -s http://localhost:4000/health/readiness | head -1
	@kill %1 2>/dev/null || true

env-check: ## Check if .env file exists
	@test -f .env || (echo "ERROR: .env file not found! Copy .env.example to .env and fill in your keys." && exit 1)
	@echo ".env file found."

# ─── Code-Qualität ──────────────────────────────────────────────────────────

RUFF ?= $(shell command -v ruff 2>/dev/null || echo "python3 -m ruff")

lint: ## Run ruff linter
	@$(RUFF) check .

format: ## Run ruff formatter
	@$(RUFF) format .

lint-fix: ## Run ruff linter with --fix
	@$(RUFF) check --fix .

pre-commit-run: ## Run all pre-commit hooks on all files
	@pre-commit run --all-files

install-dev: ## Install dev dependencies and pre-commit hooks
	pip install -r requirements-dev.txt
	pre-commit install

# ─── Tests ──────────────────────────────────────────────────────────────────

test: ## Run unit tests (render-config, find-shared-models, providers_config, multi-instance)
	@python3 -m unittest discover -s tests -v 2>&1 | tail -5

test-quiet: ## Run unit tests, minimal output
	@python3 -m unittest discover -s tests 2>&1 | tail -5
