# AGENTS.md — LiteLLM Free-Models Proxy

> **Stand: 2026-07-16** — Komplett-Abarbeitung des Code-Reviews vom 06.07.
> (PLAN.md): Passwort-Flow (Compose + K8s-Secrets aus .env), konditionaler
> Redis-Render, `usage-based-routing-v2` mit Redis-Tracking, Manifest-Dedup
> (`k8s/redis/`-Base), CI mit blockierendem Lint + Invarianten-Tests +
> Manifest-Validierung, Sync-Workflow als PR-Pipeline, generierte
> Deployment-Matrix, Postgres-Backup, Image-Pinning, securityContext +
> NetworkPolicy.

## Kurzbeschreibung

LiteLLM-Proxy, der **ausschließlich kostenlose LLM-APIs** von 13 Providern aggregiert, mit rate-limit-bewusstem Load-Balancing (`usage-based-routing-v2`), Cooldowns und Fallback-Chains. Gleiche Modelle (z.B. `gpt-oss-120b`) sind über mehrere Anbieter gedeckt, um Rate-Limits zu umgehen.

**Repo**: `/home/sb/github/litellm-free-models`

---

## 1. Architektur

### Single-Instance (Hauptsetup)

```
Client ──► LiteLLM Proxy (:4000)
              │
              ├─► OpenRouter (1 RPM)
              ├─► Cerebras (30 RPM)
              ├─► Groq (2-30 RPM)
              ├─► Cloudflare Workers AI (10 RPM)
              ├─► Google AI Studio (2 RPM, derzeit ohne aktives Deployment)
              ├─► NVIDIA NIM (40 RPM)
              ├─► Mistral La Plateforme (2 RPM)
              ├─► Cohere (20 RPM)
              ├─► GitHub Models (15 RPM)
              ├─► OpenCode Zen (10 RPM)
              ├─► LLM7.io (40 RPM)
              ├─► HuggingFace Inference API (30 RPM)
              └─► OVHcloud (2 RPM, **kein Key nötig**)
```

### Multi-Instance (Erweiterung in `multi-instance/`)

```
Client ──► MASTER (:4000, eigene Keys + Slave-Routing)
              │
              ├─► Direkte Provider (eigene API-Keys)
              ├─► Slave 1 (:4001, andere API-Keys)
              └─► Slave 2 (:4002, andere API-Keys)
```

Master: 99 direkte + 72 Slave-Deployments = **171 Deployments** (36 model_names × 2 Slaves zusätzlich). Slaves nutzen die base `config.yaml` per Docker-Volume-Mount.

**Positionierung (bewusste Entscheidung):** Multi-Key-Deployments in EINER Instanz haben denselben 3×-Effekt ohne den Overhead. Das Master/Slave-Setup ist nur für **getrennte Hosts/Egress-IPs** positioniert (IP-basierte Limits wie OVHcloud) — siehe README-Abschnitt "Multi-Instance".

---

## 2. Provider & API-Keys

| # | Provider | API-Format | Env-Var | RPM (Free) |
|---|---|---|---|---|
| 1 | [OpenRouter](https://openrouter.ai) | openrouter/ | `OPENROUTER_API_KEY` | 1 |
| 2 | [Cerebras](https://cerebras.ai) | cerebras/ | `CEREBRAS_API_KEY` | 30 |
| 3 | [Groq](https://groq.com) | groq/ | `GROQ_API_KEY` | 2-30 |
| 4 | [Cloudflare Workers AI](https://workers.ai) | cloudflare/ | `CLOUDFLARE_API_KEY` + `CLOUDFLARE_API_BASE` | 10 |
| 5 | [Google AI Studio](https://aistudio.google.com) | gemini/ | `GEMINI_API_KEY` (derzeit ungenutzt, für künftige Syncs) | 2 |
| 6 | [NVIDIA NIM](https://build.nvidia.com) | openai/ (api_base) | `NVIDIA_API_KEY` | 40 |
| 7 | [Mistral La Plateforme](https://console.mistral.ai) | mistral/ | `MISTRAL_API_KEY` | 2 |
| 8 | [Cohere](https://cohere.com) | cohere/ | `COHERE_API_KEY` | 20 |
| 9 | [GitHub Models](https://github.com/marketplace/models) | openai/ (api_base) | `GITHUB_TOKEN` | 15 |
| 10 | [OpenCode Zen](https://opencode.ai/zen) | openai/ (api_base) | `OPENCODE_ZEN_API_KEY` | 10 |
| 11 | [LLM7.io](https://llm7.io/) | openai/ (api_base) | `LLM7IO_API_KEY` | 40 |
| 12 | [HuggingFace Inference API](https://huggingface.co/) | huggingface/ | `HF_TOKEN` | 30 |
| 13 | [OVHcloud AI Endpoints](https://www.ovhcloud.com/en/public-cloud/ai-endpoints/) | openai/ (api_base) | (kein Key, anonymer Free-Tier) | 2 |

Vollständige Env-Var-Liste inkl. `REDIS_*`/`POSTGRES_*`: siehe `.env.example` (die Datei ist die Referenz, Zahlen hier werden nicht mehr von Hand gepflegt).

### Provider-Besonderheiten

- **NVIDIA**: Deployment-Name = `openai/openai/<model>` → sendet `openai/<model>` an NVIDIA. Kimi läuft unter `moonshotai/kimi-k2-instruct` (anders als `kimi-k2.6` auf OpenRouter/Cloudflare).
- **GitHub Models**: Endpoint `https://models.inference.ai.azure.com`, Modelle: `Meta-Llama-3.3-70B-Instruct`, `Mistral-large-2411`, `Cohere-command-r-plus-08-2024`.
- **OpenCode Zen**: Endpoint `https://opencode.ai/zen/v1`, Modelle: `deepseek-v4-flash-free`, `nemotron-3-ultra-free`, `big-pickle`, `north-mini-code-free`.
- **Cloudflare**: Model-Suffix `-fp8-fast` statt `-fp8` (getestet gegen API-Doku). `deepseek-v4-flash` existiert nicht bei Cloudflare.
- **Cerebras**: `llama3.1-8b` wurde am 27.05.2026 deprecated.
- **LLM7.io**: OpenAI-kompatibel an `https://api.llm7.io/v1`. Free-Tier: 2 RPM (40 RPM mit kostenlosem Token von token.llm7.io). `api_key: "unused"` für den Basis-Tier.
- **HuggingFace**: Nutzt das `huggingface/`-Prefix von LiteLLM → routed zur HF Inference API. Rate-limited, keine Credit Card nötig.
- **OVHcloud**: OpenAI-kompatibel an `https://oai.endpoints.kepler.ai.cloud.ovh.net/v1`. **Anonymer Free-Tier** ohne API-Key (2 RPM/IP/Modell). `api_key: ""` in `config.yaml`.
- **Google AI Studio**: Derzeit **kein aktives Deployment** (gemma-3-Serie von Google eingestellt, Juni 2026). `GEMINI_API_KEY` bleibt für künftige Katalog-Syncs dokumentiert.

---

## 3. Modelle & Deployment-Matrix

Die Matrix wird **generiert** (`python3 find-shared-models.py --write-docs`), nicht von Hand gepflegt — CI prüft auf Drift:

<!-- BEGIN GENERATED MODEL MATRIX (python3 find-shared-models.py --write-docs) -->
Stand (aus `config.template.yaml` generiert): **36 model_names, 109 base-Deployments**. `render-config.py` entfernt Deployments von Providern ohne API-Key in `.env` – die effektive Anzahl kann daher kleiner sein.

| model_name | Deployments | Provider |
|---|---|---|
| `gpt-oss-120b` | 7 | OpenRouter, Cerebras, Groq, Cloudflare, NVIDIA, OVHcloud, HuggingFace |
| `gpt-oss-20b` | 7 | OpenRouter, Groq, Cloudflare, NVIDIA, OVHcloud, HuggingFace, LLM7.io |
| `deepseek-v4-flash` | 6 | OpenRouter, NVIDIA, OpenCode Zen, HuggingFace, LLM7.io |
| `kimi-k2.6` | 6 | OpenRouter, Cloudflare, NVIDIA, OpenCode Zen, LLM7.io, HuggingFace |
| `llama-3.3-70b-instruct` | 6 | OpenRouter, Groq, Cloudflare, GitHub Models, OVHcloud, HuggingFace |
| `gemma-4-31b-it` | 5 | OpenRouter, NVIDIA, HuggingFace, Cerebras, Google AI Studio |
| `llama-3.1-8b` | 5 | Groq, Cloudflare, NVIDIA, GitHub Models, HuggingFace |
| `gemma-4-26b-a4b-it` | 4 | OpenRouter, Cloudflare, HuggingFace, Google AI Studio |
| `llama-4-maverick` | 4 | Groq, OpenRouter, NVIDIA, HuggingFace |
| `llama-4-scout` | 4 | Groq, Cloudflare, GitHub Models, HuggingFace |
| `nemotron-3-120b` | 3 | OpenRouter, Cloudflare, NVIDIA |
| `nemotron-3-nano-30b` | 3 | OpenRouter, NVIDIA, HuggingFace |
| `nemotron-3-ultra` | 3 | OpenRouter, OpenCode Zen, NVIDIA |
| `qwen3-32b` | 3 | Groq, HuggingFace, OVHcloud |
| `qwen3.6-27b` | 3 | Groq, HuggingFace, OVHcloud |
| `codestral-latest` | 2 | LLM7.io, Mistral |
| `command-r-plus` | 2 | Cohere, GitHub Models |
| `deepseek-r1-0528` | 2 | LLM7.io, HuggingFace |
| `deepseek-v4-pro` | 2 | OpenCode Zen, HuggingFace |
| `gpt-oss-safeguard-20b` | 2 | Groq, HuggingFace |
| `kimi-k2.5` | 2 | OpenCode Zen, HuggingFace |
| `kimi-k2.7-code` | 2 | OpenCode Zen, HuggingFace |
| `lyria-3-clip` | 2 | OpenRouter, Google AI Studio |
| `lyria-3-pro` | 2 | OpenRouter, Google AI Studio |
| `mistral-large` | 2 | Mistral, GitHub Models |
| `mistral-small-3.2` | 2 | LLM7.io, Mistral |
| `north-mini-code` | 2 | OpenCode Zen, OpenRouter |
| `qwen3-235b` | 2 | LLM7.io, HuggingFace |
| `qwen3-coder-30b-a3b` | 2 | HuggingFace, OVHcloud |
| `qwen3-next-80b-a3b` | 2 | OpenRouter, HuggingFace |
| `qwen3.5-397b-a17b` | 2 | HuggingFace, OVHcloud |
| `qwen3.5-9b` | 2 | HuggingFace, OVHcloud |
| `whisper-large-v3` | 2 | Groq, OVHcloud |
| `whisper-large-v3-turbo` | 2 | Groq, OVHcloud |
| `big-pickle` | 1 | OpenCode Zen |
| `openrouter-free` | 1 | OpenRouter |
<!-- END GENERATED MODEL MATRIX -->

**Hinweis zu `gemma-3-12b-it`**: Im Juni 2026 entfernt (Google hat die gemma-3-Serie eingestellt; kein Free-Provider bietet es mehr an). Ersatz: `gemma-4-26b-a4b-it` und `gemma-4-31b-it`.

**Hinweis zu `qwen3-next-80b-a3b`**: Entfernt, weil kein 2. Free-Provider verfügbar war (Regel: alle Modelle ≥ 2 Provider außer den dokumentierten Ausnahmen `big-pickle`, `north-mini-code`, `openrouter-free`). Diese Regel wird jetzt von `tests/test_config_invariants.py` erzwungen.

### Multi-Instance (zusätzlich)

Master-Config: 99 base + 72 Slave = **171 Deployments**. Jeder Slave hat eigene 99 base Deployments (andere API-Keys) → effektiv 3× Rate-Limit pro Provider.

---

## 4. Routing & Fallback

### Router Settings (config.template.yaml)

```yaml
router_settings:
  routing_strategy: usage-based-routing-v2   # rpm/tpm-Budget-bewusst
  # redis_host/port/password (os.environ/REDIS_*) — nur gerendert, wenn
  # REDIS_HOST gesetzt ist; dann instanzuebergreifendes Tracking + Cooldowns
  num_retries: 2
  retry_after: 5
  allowed_fails: 3
  cooldown_time: 30
```

`tpm`/`rpm` liegen pro Deployment in **`litellm_params`** (nicht Top-Level!), damit der Router sie auswertet. Invarianten-Test erzwingt das.

### Fallback-Chains

Maßgeblich ist `config.template.yaml` (`router_settings.fallbacks` / `context_window_fallbacks`) — Beispiele hier absichtlich entfernt, weil kopierte Snippets in der Vergangenheit entfernte Modelle wieder eingeschleppt haben. Regeln:

- Jedes Chain-Ziel muss ein existierendes model_name sein (Invarianten-Test + `render-config.py` filtert beim Rendern zusätzlich).
- `openrouter-free` wird beim Rendern automatisch an-/abgehängt, abhängig von `OPENROUTER_API_KEY`.
- Catch-All `*` fängt unbekannte Modellnamen.

---

## 5. Dateistruktur

```
/home/sb/github/litellm-free-models/
├── onboard.py                   # Interaktives Setup (wiederholbar): .env, Key-Eingabe mit
│                                #   Signup-URLs, Live-Key-Check, Render, Compose-Start
├── config.template.yaml         # Single Source of Truth mit {{ENV_VAR}} + # BEGIN/END REDIS-Markern
├── config.yaml                  # Generiert (gitignored, enthält echte Keys)
├── render-config.py             # Renderer: Substitution, Provider-Filter, Redis-Bloecke
│                                #   konditional, Fallback-Key+Ziel-Validierung, --no-redis,
│                                #   Backup der Vorversion + Auto-Prune (letzte 5)
├── find-shared-models.py        # Katalog-Abfrage, Overlap-Report, --apply, --emit-matrix/--write-docs
├── providers_config.py          # Zentrale Provider-Definitionen
├── .env.example                 # Vorlage (Passwörter PFLICHT, leer ausgeliefert)
├── docker-compose.yaml          # Single-Instance (Proxy + Redis + Postgres, :?-Pflicht-Passwörter)
├── Dockerfile                   # Optionales Custom Image (⚠️ bündelt config.yaml mit echten Keys)
├── Makefile                     # render/check/validate/k8s/backup/clean-Targets, LITELLM_IMAGE-Pin
├── PLAN.md                      # Review-Befunde 2026-07-06 (Basis dieser Abarbeitung)
│
├── k8s/                         # Kubernetes (Single-Instance)
│   ├── configmap.yaml           # Generiert via make k8s-configmap (gitignored)
│   ├── deployment.yaml          # LiteLLM (gepinntes Image, securityContext, DATABASE_URL)
│   ├── service.yaml / ingress.yaml / namespace.yaml
│   ├── networkpolicy.yaml       # Redis+Postgres nur von LiteLLM-Pods erreichbar
│   ├── secret.yaml.template     # litellm-secrets (nur Doku; make k8s-secret erzeugt real)
│   ├── postgres-secret.yaml.template
│   ├── postgres-{pvc,deployment,service}.yaml
│   ├── postgres-backup-{pvc,cronjob}.yaml   # Nightly pg_dump, 7 Dumps Retention
│   └── redis/                   # GEMEINSAME Redis-Base (Single- UND Multi-Instance)
│       ├── kustomization.yaml
│       ├── deployment.yaml      # --save "" (kein PVC), 512Mi-Limit, sh -c Probes mit -e
│       ├── service.yaml
│       └── secret.yaml.template
│
├── tests/                       # 96 Unit-Tests (unittest, stdlib-only)
│   └── test_config_invariants.py  # Fallback-Ziele, ≥2-Provider-Regel, tpm/rpm-Lage, Redis-Marker
│
├── .github/workflows/
│   ├── ci.yml                   # ruff (blockierend), Test-Matrix, Render-Smoke,
│   │                            #   Matrix-Drift-Check, compose config -q, kubeconform
│   └── sync-models.yml          # Wöchentliche PR-Pipeline (SYNC_*-Secrets, Gates, kein Auto-Merge)
│
└── multi-instance/              # Master + 2 Slaves
    ├── .env.example             # Projekt-.env: REDIS_/POSTGRES_-Passwörter (Compose-Interpolation!)
    ├── master/ slave1/ slave2/  # per-Instanz .env.example (NUR Provider-Keys)
    ├── generate-config.py
    ├── docker-compose.yaml
    ├── k8s/                     # kustomization referenziert ../../k8s/redis als Base
    └── README.md
```

---

## 6. Deployment

```bash
# Docker Compose (Single-Instance)
make docker-compose-up          # rendert + startet; REDIS_/POSTGRES_PASSWORD in .env PFLICHT

# Kubernetes (Single-Instance)
make k8s-apply                  # namespace + secrets (aus .env) + configmap + alles

# Multi-Instance
cd multi-instance
python3 generate-config.py
cp .env.example .env            # Redis-/Postgres-Passwörter (Compose liest NUR diese!)
# master/slave .env-Dateien befüllen
docker compose up -d
```

---

## 7. Status & Bekannte Einschränkungen

### Abgeschlossen (Stand 2026-07-16)
- ✅ 13 Provider integriert, 36 model_names / 109 base Deployments (generierte Matrix in §3)
- ✅ Redis-Cache + Auth-Cache, **konditional gerendert** (ohne REDIS_HOST → Redis-frei)
- ✅ `usage-based-routing-v2` mit Redis-Tracking; tpm/rpm in litellm_params
- ✅ Passwort-Flow: keine committeten Defaults mehr; Compose erzwingt Passwörter (`:?`),
  `make k8s-secret` erzeugt litellm-secrets (Allowlist) + Redis-/Postgres-Secrets aus .env
- ✅ Redis: keine Persistenz (`--save ""`), kein PVC, Limits mit Headroom, Probes via `sh -c` + `-e`
- ✅ Manifest-Dedup: gemeinsame `k8s/redis/`-Base für beide Setups
- ✅ CI: ruff blockierend, `make test` propagiert Exit-Codes, Invarianten-Tests,
  `docker compose config -q`, kubeconform, Kustomize-Builds, Matrix-Drift-Check
- ✅ Sync-Workflow → wöchentliche PR-Pipeline mit Gates (kein Auto-Merge, Fail ohne Secrets)
- ✅ Image auf `v1.92.0` gepinnt (Makefile `LITELLM_IMAGE`, Compose, K8s, Dockerfile)
- ✅ securityContext überall, NetworkPolicies für Redis/Postgres
- ✅ Postgres-Backup: K8s-CronJob (nightly, 7 Dumps) + `make backup-db`/`restore-db` für Compose
- ✅ `make check-config` bootet LiteLLM real gegen einen Redis-freien Render (Port 4010)

### Offen / Einschränkungen
- ❌ Keine API-Keys vorhanden → keine Live-LLM-Tests möglich
- ❌ `SYNC_*`-GitHub-Secrets für die Sync-PR-Pipeline müssen noch angelegt werden
- ❌ Redis als Single-Pod ohne Sentinel/Cluster (für Free-Tier-Proxy OK)
- ❌ Multi-Instance-K8s hat kein eigenes Postgres/DATABASE_URL (Instanzen laufen dort DB-los;
  bewusst nicht nachgerüstet — bei Bedarf analog Single-Instance verdrahten)
- ⚠️ K8s-Postgres wurde von 15-alpine auf 16-alpine angehoben (Konsistenz mit Compose).
  Ein bereits mit PG15 initialisiertes PVC startet mit PG16 nicht — vorher dumpen/restoren.

---

## 8. Wichtige Entscheidungen

1. **Provider-Präfixe**: `openrouter/`, `cerebras/`, `groq/`, `cloudflare/`, `gemini/` — von LiteLLM automatisch geroutet. `openai/` für NVIDIA, GitHub Models, OpenCode Zen, LLM7.io und OVHcloud mit je eigener `api_base`.
2. **Kein PyYAML**: Alle Generatoren/Tests parsen YAML zeilenbasiert (stdlib-only).
3. **Slave-Config per Volume-Mount**: Slaves referenzieren `../config.yaml`; nur die Master-Config wird generiert.
4. **Reverse-Proxy-Provider abgelehnt**: Pollinations.ai, UncloseAI, G4F.dev (Legalität/Reliabilität).
5. **Template als Single Source of Truth**: Edits nur in `config.template.yaml`; `config.yaml` wird überschrieben.
6. **OpenRouter-Free-Fallback an/aus** je nach `OPENROUTER_API_KEY` (Renderer).
7. **Redis konditional** (`# BEGIN/END REDIS`-Marker): ohne `REDIS_HOST` (oder mit `--no-redis`) werden Cache- UND Router-Redis-Block entfernt — kein Degradieren gegen unerreichbares Redis. `make docker-run`/`check-config` nutzen `--no-redis`.
8. **Response-Cache bewusst mit TTL 300 s**: identische Requests liefern binnen 5 min die identische Antwort (auch bei temperature > 0); Opt-out `{"cache": {"no-cache": true}}`. Dokumentiert in README "Response Cache".
9. **Secret-Konvention**: committet werden nur `*.template`-Dateien; reale Secrets erzeugt `make k8s-secret` aus `.env` (litellm-secrets mit expliziter Key-Allowlist, litellm-redis-secret, litellm-postgres-secret). `k8s-apply` wendet NIE ein Secret-File an.
10. **Passwörter ohne Defaults**: Compose nutzt `${VAR:?}`-Interpolation; `.env.example` liefert leere Pflichtfelder. In Multi-Instance liest Compose Passwörter NUR aus `multi-instance/.env` (per-Service `env_file` wird für Interpolation nie benutzt).
11. **Redis ist reiner Cache**: `--save ""`, kein PVC/emptyDir-Persistenz — Cache wärmt sich selbst wieder auf; Memory-Limit 512Mi = 2× maxmemory (Fragmentierungs-Headroom).
12. **Image-Pinning**: `ghcr.io/berriai/litellm:v1.92.0` überall statt `main-latest`; zentrale Variable `LITELLM_IMAGE` im Makefile; Dependabot (docker) bumpt das Dockerfile, Compose/K8s dann manuell nachziehen. Seit v1.9x taggt BerriAI stabile Releases als nacktes `vX.Y.Z` statt `main-vX.Y.Z-stable`.
13. **usage-based-routing-v2 statt simple-shuffle**: simple-shuffle ignorierte die gepflegten rpm/tpm-Werte komplett (rpm:1-OpenRouter bekam gleich viel Traffic wie rpm:40-NVIDIA). Dafür mussten tpm/rpm nach `litellm_params` wandern.
14. **Doku-Matrix wird generiert** (`--write-docs` zwischen HTML-Marker); CI failt bei Drift. Handgepflegte Deployment-Zahlen sind abgeschafft.
15. **Sync-PR-Pipeline konservativ**: `--apply` fügt nur hinzu/aktualisiert Kosten; Modell-Entfernungen bleiben manuell (Katalog-Flapping). Ohne `SYNC_*`-Secrets failt der Run laut.

---

## 9. Commands

```bash
# Onboarding (Erst-Setup UND Aenderungen: Keys, Passwoerter, Restart)
make onboard                    # interaktiv; --non-interactive fuer Skripte

# Rendern & Validieren
make render-config              # Template -> config.yaml (Redis je nach REDIS_HOST)
                                # warnt, wenn model_names nur noch 1 Deployment haben
make render-config-no-redis     # explizit ohne Redis-Bloecke
make check-config               # bootet LiteLLM gegen Redis-freien Render (Port 4010)
make validate-manifests         # compose config -q + kubeconform (falls installiert)
make test                       # 96 Unit-Tests inkl. Invarianten
make lint / make format         # ruff
make clean                      # Backups/Reports/Caches aufräumen

# Provider-Overlap & Kosten
python3 find-shared-models.py                   # Report (Dry-Run)
python3 find-shared-models.py --apply           # ins Template schreiben + rendern
python3 find-shared-models.py --apply --regen-multi-instance
python3 find-shared-models.py --emit-matrix     # Deployment-Matrix nach stdout
python3 find-shared-models.py --write-docs      # Matrix in AGENTS.md/README.md schreiben

# Docker / K8s
make docker-compose-up / docker-compose-down
make docker-run                 # Standalone ohne Redis (rendert --no-redis, baut Image)
make k8s-apply / k8s-delete / k8s-secret / k8s-configmap / k8s-restart
make backup-db / restore-db     # Compose-Postgres nach/aus ./backups/

# Multi-Instance
cd multi-instance && python3 generate-config.py
docker compose up -d            # (vorher .env + per-Instanz .envs anlegen)
kubectl apply -k k8s/           # K8s-Variante (nutzt ../../k8s/redis als Base)
```

---

## 10. Provider-Overlap & Kosten-Check (Modell-Discovery)

`find-shared-models.py`:

1. **Live-Abfrage** aller Provider via `.env`-Keys (`providers-overlap.txt`) — **parallel** (ThreadPool, <2 s statt sequenziell) mit **Retry/Backoff** bei 429/5xx/Netzfehlern. OVHcloud/LLM7/HF laufen auch ohne Key.
2. **Free-Tier-Filter**: OpenRouter liefert nur noch `:free`-/0-Preis-Modelle (sonst könnte `--apply` ein Paid-Modell einschleusen); Google AI nur `generateContent`-fähige Modelle; Cohere nur chat-fähige Modellnamen; HuggingFace kommt live vom Inference-Router (`router.huggingface.co/v1/models`) statt aus einer hartkodierten Liste (Fallback-Liste → Provider wird als „partial" markiert und vom Stale-Check ausgenommen). Cloudflare wird über `/ai/models/search` (paginiert) abgefragt, GitHub Models versteht Liste- und Dict-Antworten.
3. **Gruppierung** nach normalisierten Modellnamen, Filter auf ≥ 2 Provider.
4. **Kosten-Vergleich** (hypothetischer Paid-Tier-Preis) aus der LiteLLM-Referenz-DB, 24h-Cache unter `.cache/litellm-prices.json`.
5. **Apply-Plan-Mapping**: normalisierte Gruppennamen werden auf die sprechenden Template-`model_names` gemappt (plus globales Dedupe) — bestehende Deployments werden zuverlässig als `skip` erkannt statt als Duplikat geplant. Provider-Erkennung im Template nutzt die api_base-Diskrimination aus `render-config.py` (NVIDIA/GitHub/Zen/LLM7/OVH teilen sich das `openai/`-Präfix).
6. **Stale-Deployment-Erkennung** (Gegenrichtung zum Apply-Plan): Template-Deployments, deren Modell im Live-Katalog fehlt, landen als eigener Report-Abschnitt („Verwaiste Template-Deployments") — **report-only**, Entfernungen bleiben manuell. Geprüft nur gegen erfolgreich UND vollständig abgefragte Kataloge. Fund-Beispiel: die OVHcloud-ID `Meta-Llama-3_3-...` (Unterstrich) war im Template falsch mit Punkt geschrieben.
7. `--apply` schreibt neue Deployments ins Template (tpm/rpm in litellm_params!) und rendert.
8. `--emit-matrix`/`--write-docs` generieren die Doku-Matrix (§3).

**Wichtige Insight:** `input_cost_per_token`/`output_cost_per_token` im Report zeigen den _Paid-Tier_-Preis; in `config.yaml` bleiben die model_info-Kosten dokumentarisch, das Routing bleibt Free-Tier.

**Automatisiert:** `.github/workflows/sync-models.yml` führt denselben Sync wöchentlich mit `SYNC_*`-Secrets aus und öffnet einen PR (Gates: ruff, Tests, Render, kubeconform; nie Auto-Merge).

---

## 11. Template-Pipeline (`config.template.yaml` → `config.yaml`)

```
config.template.yaml    im Repo eingecheckt, {{ENV_VAR}}-Platzhalter + Redis-Marker
        │
        │  python3 render-config.py [--no-redis] [--dry-run] [--output <pfad>]
        ▼
config.yaml             bei jedem Render neu geschrieben (gitignored)
        │
        ├─► LiteLLM-Container
        └─► multi-instance/generate-config.py
```

**Verhalten von `render-config.py`:**

1. **Platzhalter-Substitution**: `{{OPENROUTER_API_KEY}}` → Wert aus `.env`.
2. **Provider-Filter**: fehlt ein required Key, fliegt der Provider-Block (inkl. Kommentar-Header) raus. OVHcloud akzeptiert leeren Key.
3. **Redis-Bloecke**: `# BEGIN REDIS ...`/`# END REDIS ...`-Bereiche (Cache in litellm_settings, redis_* in router_settings) werden nur behalten, wenn `REDIS_HOST` gesetzt ist und kein `--no-redis` übergeben wurde; die Marker-Zeilen selbst werden immer entfernt.
4. **OpenRouter-Free-Fallback**: an/aus je nach Key.
5. **Fallback-Validierung**: verwaiste Keys UND verwaiste Chain-Ziele werden entfernt (fallbacks + context_window_fallbacks).
6. **Atomare Writes**: Backup der VORHERIGEN Version als `config.yaml.bak.<timestamp>`, Auto-Prune auf die letzten 5.
7. **Single-Deployment-Warnung**: Nach dem Provider-Filter wird gewarnt, wenn ein model_name nur noch 1 Deployment hat (Ausnahmen: `SINGLE_PROVIDER_ALLOWED`) — die ≥ 2-Provider-Regel gilt nur fürs Template, fehlende Keys können die Redundanz zur Laufzeit aufheben.

**Auslöser:** manuell, via Makefile-Dependencies (`docker-compose-up`, `k8s-apply`, `k8s-configmap`), nach `find-shared-models.py --apply`, in CI.
