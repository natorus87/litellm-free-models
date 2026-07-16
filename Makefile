# =============================================================================
# LiteLLM Free-Models Proxy – Makefile
# =============================================================================

.PHONY: help onboard docker-build docker-run docker-stop k8s-apply k8s-delete \
        k8s-secret k8s-logs k8s-pods check-config render-config \
        render-config-no-redis test test-quiet clean validate-manifests \
        backup-db restore-db lint format lint-fix pre-commit-run install-dev

# Gepinnte LiteLLM-Version (statt wanderndem main-latest Tag).
# Muss mit docker-compose.yaml, Dockerfile und den K8s-Deployments
# uebereinstimmen; Updates via Renovate/Dependabot oder manuell.
LITELLM_IMAGE ?= ghcr.io/berriai/litellm:main-v1.83.14-stable

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ─── Onboarding ─────────────────────────────────────────────────────────────

onboard: ## Interaktives Setup: .env, API-Keys, Key-Check, Render, Compose-Start
	@python3 onboard.py

# ─── Config-Render-Pipeline ─────────────────────────────────────────────────

render-config: ## Render config.template.yaml -> config.yaml
	@python3 render-config.py

render-config-dry: ## Dry-run render (no writes)
	@python3 render-config.py --dry-run

render-config-no-redis: ## Render config.yaml WITHOUT Redis (standalone runs ohne Redis-Container)
	@python3 render-config.py --no-redis

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

# Standalone-Run ohne Compose-Stack: es gibt kein erreichbares Redis, daher
# wird die Config bewusst OHNE Redis-Bloecke gerendert (und REDIS_HOST aus
# .env neutralisiert). Fuer den vollen Stack: make docker-compose-up.
docker-run: render-config-no-redis docker-build ## Run standalone with Docker (ohne Redis)
	docker run -d \
		--name litellm-free-models \
		-p 4000:4000 \
		--env-file .env \
		-e REDIS_HOST= \
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

# Explizite Allowlist der Keys, die in das litellm-secrets K8s-Secret
# gehoeren. Verhindert, dass lokale Zusatzvariablen aus .env im
# Cluster-Secret landen. REDIS_* ist bewusst NICHT enthalten:
# REDIS_HOST/PORT werden im Deployment statisch gesetzt, REDIS_PASSWORD
# fliesst ausschliesslich ueber litellm-redis-secret (Single Source).
K8S_SECRET_KEYS := LITELLM_MASTER_KEY OPENROUTER_API_KEY CEREBRAS_API_KEY \
	GROQ_API_KEY CLOUDFLARE_API_KEY CLOUDFLARE_API_BASE NVIDIA_API_KEY \
	GEMINI_API_KEY MISTRAL_API_KEY COHERE_API_KEY GITHUB_TOKEN \
	OPENCODE_ZEN_API_KEY OVHCLOUD_API_KEY LLM7IO_API_KEY HF_TOKEN

k8s-secret: env-check k8s-namespace ## Create K8s secrets from .env (litellm-secrets + litellm-redis-secret)
	@echo "Creating litellm-secrets from .env (allowlisted keys only)..."
	@grep -E "^($(shell echo $(K8S_SECRET_KEYS) | tr ' ' '|'))=" .env > .env.k8s.tmp; \
	kubectl create secret generic litellm-secrets \
		--namespace litellm-free-models \
		--from-env-file=.env.k8s.tmp \
		--dry-run=client -o yaml | kubectl apply -f -; \
	rc=$$?; rm -f .env.k8s.tmp; test $$rc -eq 0
	@echo "Creating litellm-redis-secret from .env (REDIS_PASSWORD)..."
	@REDIS_PASSWORD=$$(grep -E '^REDIS_PASSWORD=' .env | head -1 | cut -d= -f2-); \
	if [ -z "$$REDIS_PASSWORD" ]; then \
		echo "ERROR: REDIS_PASSWORD fehlt/leer in .env (openssl rand -hex 16)"; \
		exit 1; \
	fi; \
	kubectl create secret generic litellm-redis-secret \
		--namespace litellm-free-models \
		--from-literal=redis-password="$$REDIS_PASSWORD" \
		--dry-run=client -o yaml | kubectl apply -f -
	@echo "Creating litellm-postgres-secret from .env (POSTGRES_PASSWORD)..."
	@POSTGRES_PASSWORD=$$(grep -E '^POSTGRES_PASSWORD=' .env | head -1 | cut -d= -f2-); \
	if [ -z "$$POSTGRES_PASSWORD" ]; then \
		echo "ERROR: POSTGRES_PASSWORD fehlt/leer in .env (openssl rand -hex 16)"; \
		exit 1; \
	fi; \
	kubectl create secret generic litellm-postgres-secret \
		--namespace litellm-free-models \
		--from-literal=postgres-password="$$POSTGRES_PASSWORD" \
		--dry-run=client -o yaml | kubectl apply -f -

k8s-apply: k8s-namespace k8s-secret render-config k8s-configmap ## Deploy everything to K8s
	kubectl apply -f k8s/configmap.yaml
	kubectl apply -f k8s/deployment.yaml
	kubectl apply -f k8s/service.yaml
	kubectl apply -f k8s/postgres-pvc.yaml
	kubectl apply -f k8s/postgres-deployment.yaml
	kubectl apply -f k8s/postgres-service.yaml
	kubectl apply -f k8s/postgres-backup-pvc.yaml
	kubectl apply -f k8s/postgres-backup-cronjob.yaml
	kubectl apply -k k8s/redis/
	kubectl apply -f k8s/networkpolicy.yaml
	# kubectl apply -f k8s/ingress.yaml  # Uncomment when domain is configured
	@echo ""
	@echo "Deployment complete! Check status:"
	@echo "  kubectl get pods -n litellm-free-models"

k8s-delete: ## Remove everything from K8s
	kubectl delete -f k8s/ingress.yaml 2>/dev/null || true
	kubectl delete -f k8s/networkpolicy.yaml 2>/dev/null || true
	kubectl delete -f k8s/service.yaml
	kubectl delete -f k8s/postgres-service.yaml
	kubectl delete -f k8s/postgres-deployment.yaml 2>/dev/null || true
	kubectl delete -f k8s/deployment.yaml 2>/dev/null || true
	kubectl delete -f k8s/configmap.yaml 2>/dev/null || true
	kubectl delete -f k8s/postgres-backup-cronjob.yaml 2>/dev/null || true
	kubectl delete -f k8s/postgres-backup-pvc.yaml 2>/dev/null || true
	kubectl delete -f k8s/postgres-pvc.yaml 2>/dev/null || true
	kubectl delete -k k8s/redis/ 2>/dev/null || true
	kubectl delete secret litellm-secrets -n litellm-free-models 2>/dev/null || true
	kubectl delete secret litellm-redis-secret -n litellm-free-models 2>/dev/null || true
	kubectl delete secret litellm-postgres-secret -n litellm-free-models 2>/dev/null || true
	kubectl delete namespace litellm-free-models 2>/dev/null || true

k8s-pods: ## List pods
	kubectl get pods -n litellm-free-models -o wide

k8s-logs: ## Follow pod logs
	@kubectl logs -n litellm-free-models -l app=litellm-proxy -f

k8s-restart: ## Rollout restart
	kubectl rollout restart deployment litellm-proxy -n litellm-free-models

# ─── Utilities ──────────────────────────────────────────────────────────────

# Validiert die gerenderte Config, indem LiteLLM sie tatsaechlich bootet und
# /health/readiness abgefragt wird. Gerendert wird OHNE Redis-Bloecke in eine
# separate Datei (config.check.yaml), damit die Validierung weder ein
# laufendes Redis braucht noch die echte config.yaml anfasst.
# Port 4010, um nicht mit einem lokal laufenden Proxy zu kollidieren.
check-config: ## Validate config by booting LiteLLM against a Redis-less render
	@echo "Rendering validation config (ohne Redis) ..."
	@python3 render-config.py --no-redis --output config.check.yaml
	@docker rm -f litellm-config-check >/dev/null 2>&1 || true
	@echo "Booting LiteLLM ($(LITELLM_IMAGE)) ..."
	@docker run -d --name litellm-config-check \
		-p 4010:4000 \
		-v $(PWD)/config.check.yaml:/app/config.yaml:ro \
		$(LITELLM_IMAGE) \
		--config /app/config.yaml --port 4000 >/dev/null
	@ok=1; for i in $$(seq 1 30); do \
		if curl -sf http://localhost:4010/health/readiness >/dev/null 2>&1; then \
			ok=0; break; \
		fi; \
		if [ -z "$$(docker ps -q -f name=litellm-config-check)" ]; then break; fi; \
		sleep 2; \
	done; \
	if [ $$ok -eq 0 ]; then \
		echo "OK: config valid (/health/readiness healthy)"; \
	else \
		echo "FEHLER: LiteLLM wurde mit dieser Config nicht ready. Logs:"; \
		docker logs --tail 50 litellm-config-check 2>&1 || true; \
	fi; \
	docker rm -f litellm-config-check >/dev/null 2>&1 || true; \
	rm -f config.check.yaml; \
	exit $$ok

# Validiert beide Compose-Dateien (Interpolation + Syntax) und, falls
# kubeconform installiert ist, alle K8s-Manifeste. Fehlende per-Instanz-
# .env-Dateien werden temporaer aus den Examples erzeugt.
validate-manifests: ## Validate Compose files and K8s manifests
	@echo "── docker-compose.yaml ──"
	@REDIS_PASSWORD=dummy POSTGRES_PASSWORD=dummy \
		docker compose -f docker-compose.yaml config -q && echo "OK"
	@echo "── multi-instance/docker-compose.yaml ──"
	@created=""; \
	for d in master slave1 slave2; do \
		if [ ! -f multi-instance/$$d/.env ]; then \
			cp multi-instance/$$d/.env.example multi-instance/$$d/.env; \
			created="$$created multi-instance/$$d/.env"; \
		fi; \
	done; \
	REDIS_PASSWORD=dummy POSTGRES_PASSWORD=dummy \
		docker compose -f multi-instance/docker-compose.yaml config -q; \
	rc=$$?; \
	for f in $$created; do rm -f $$f; done; \
	test $$rc -eq 0 && echo "OK"
	@echo "── K8s-Manifeste ──"
	@if command -v kubeconform >/dev/null 2>&1; then \
		find k8s multi-instance/k8s -name '*.yaml' \
			! -name '*.template' ! -name 'kustomization.yaml' -print0 \
			| xargs -0 kubeconform -strict -summary; \
	else \
		echo "kubeconform nicht installiert – uebersprungen (CI validiert immer)"; \
	fi

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

# WICHTIG: kein `| tail` hier – die Pipe wuerde den unittest-Exit-Code
# verschlucken und fehlschlagende Tests liessen make/CI gruen durchlaufen.
test: ## Run unit tests (render-config, find-shared-models, providers_config, multi-instance)
	@python3 -m unittest discover -s tests -v

test-quiet: ## Run unit tests, minimal output
	@python3 -m unittest discover -s tests

# ─── Backup ─────────────────────────────────────────────────────────────────

backup-db: ## Dump the Compose Postgres DB (virtual keys, spend logs) to ./backups/
	@mkdir -p backups
	@docker exec litellm-postgres pg_dump -U litellm -d litellm -F c \
		> backups/litellm-$$(date +%Y%m%d-%H%M%S).dump
	@echo "Backup geschrieben:"; ls -lht backups/ | head -3

restore-db: ## Restore the newest dump from ./backups/ into the Compose Postgres
	@latest=$$(ls -1t backups/litellm-*.dump 2>/dev/null | head -1); \
	if [ -z "$$latest" ]; then echo "Kein Dump in ./backups/ gefunden"; exit 1; fi; \
	echo "Restore aus $$latest ..."; \
	docker exec -i litellm-postgres pg_restore -U litellm -d litellm --clean < "$$latest"

# ─── Housekeeping ───────────────────────────────────────────────────────────

clean: ## Remove generated/temporary files (Backups, Reports, Caches)
	rm -f config.yaml.bak.* config.yaml.tmp config.check.yaml .env.k8s.tmp
	rm -f multi-instance/master/config.yaml.bak.* multi-instance/master/config.yaml.tmp
	rm -f providers-overlap.txt
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
