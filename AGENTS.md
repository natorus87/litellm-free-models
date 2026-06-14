# AGENTS.md — LiteLLM Free-Models Proxy

> **Stand: 2026-06-14** — Template-Pipeline (`config.template.yaml` → `config.yaml`),
> 13. Provider (OVHcloud), Kosten-Report via LiteLLM-Referenz-DB,
> `find-shared-models.py` mit Auto-Apply.

## Kurzbeschreibung

LiteLLM-Proxy, der **ausschließlich kostenlose LLM-APIs** von 13 Providern aggregiert, mit automatischem Load-Balancing, 24h-Cooldown und Fallback-Chains. Gleiche Modelle (z.B. `gpt-oss-120b`) sind über mehrere Anbieter gedeckt, um Rate-Limits zu umgehen.

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
              ├─► Google AI Studio (2 RPM)
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

Jeder Slave:
  ──► OpenRouter, Cerebras, Groq, ..., OpenCode Zen (mit SLAVE-eigenen Keys)
```

Der Master hat **118 Deployments** (70 direkte + 48 Slave-Backends).  
Slaves nutzen die base `config.yaml` per Docker-Volume-Mount.

---

## 2. Provider & API-Keys

| # | Provider | API-Format | Env-Var | RPM (Free) |
|---|---|---|---|---|
| 1 | [OpenRouter](https://openrouter.ai) | openrouter/ | `OPENROUTER_API_KEY` | 1 |
| 2 | [Cerebras](https://cerebras.ai) | cerebras/ | `CEREBRAS_API_KEY` | 30 |
| 3 | [Groq](https://groq.com) | groq/ | `GROQ_API_KEY` | 2-30 |
| 4 | [Cloudflare Workers AI](https://workers.ai) | cloudflare/ | `CLOUDFLARE_API_KEY` + `CLOUDFLARE_API_BASE` | 10 |
| 5 | [Google AI Studio](https://aistudio.google.com) | gemini/ | `GEMINI_API_KEY` | 2 |
| 6 | [NVIDIA NIM](https://build.nvidia.com) | openai/ (api_base) | `NVIDIA_API_KEY` | 40 |
| 7 | [Mistral La Plateforme](https://console.mistral.ai) | mistral/ | `MISTRAL_API_KEY` | 2 |
| 8 | [Cohere](https://cohere.com) | cohere/ | `COHERE_API_KEY` | 20 |
| 9 | [GitHub Models](https://github.com/marketplace/models) | openai/ (api_base) | `GITHUB_TOKEN` | 15 |
| 10 | [OpenCode Zen](https://opencode.ai/zen) | openai/ (api_base) | `OPENCODE_ZEN_API_KEY` | 10 |
| 11 | [LLM7.io](https://llm7.io/) | openai/ (api_base) | `LLM7IO_API_KEY` | 40 |
| 12 | [HuggingFace Inference API](https://huggingface.co/) | huggingface/ | `HF_TOKEN` | 30 |
| 13 | [OVHcloud AI Endpoints](https://www.ovhcloud.com/en/public-cloud/ai-endpoints/) | openai/ (api_base) | (kein Key, anonymer Free-Tier) | 2 |

### Provider-Besonderheiten

- **NVIDIA**: Deployment-Name = `openai/openai/<model>` → sendet `openai/<model>` an NVIDIA. Kimi läuft unter `moonshotai/kimi-k2-instruct` (anders als `kimi-k2.6` auf OpenRouter/Cloudflare).
- **GitHub Models**: Endpoint `https://models.inference.ai.azure.com`, Modelle: `Meta-Llama-3.3-70B-Instruct`, `Mistral-large-2411`, `Cohere-command-r-plus-08-2024`.
- **OpenCode Zen**: Endpoint `https://opencode.ai/zen/v1`, Modelle: `deepseek-v4-flash-free`, `nemotron-3-ultra-free`, `big-pickle`, `north-mini-code-free`.
- **Cloudflare**: Model-Suffix `-fp8-fast` statt `-fp8` (getestet gegen API-Doku). `deepseek-v4-flash` existiert nicht bei Cloudflare.
- **Cerebras**: `llama3.1-8b` wurde am 27.05.2026 deprecated.
- **LLM7.io**: OpenAI-kompatibel an `https://api.llm7.io/v1`. Free-Tier: 2 RPM (40 RPM mit kostenlosem Token von token.llm7.io). `api_key: "unused"` für den Basis-Tier.
- **HuggingFace**: Nutzt das `huggingface/`-Prefix von LiteLLM → routed zur HF Inference API (`https://api-inference.huggingface.co/models/`). 150K+ Modelle verfügbar, rate-limited, kein Credit Card nötig.
- **OVHcloud**: OpenAI-kompatibel an `https://oai.endpoints.kepler.ai.cloud.ovh.net/v1`. **Anonymer Free-Tier** ohne API-Key (2 RPM/IP/Modell). LiteLLM-Routing verwendet `api_key: ""`. Optional API-Key für höhere Limits. Modelle: `gpt-oss-120b`, `gpt-oss-20b`, `Meta-Llama-3_3-70B-Instruct`, `Llama-3.1-8B-Instruct`, `Mistral-Small-3.2-24B-Instruct-2506`, u.a.

---

## 3. Modelle & Deployment-Matrix

Stand: **24 model_names, 70 Deployments, base config.yaml (850+ Zeilen)**

| model_name | Deployments | Provider |
|---|---|---|
| `gpt-oss-120b` | 7 | OpenRouter, Cerebras, Groq, Cloudflare, NVIDIA, OVHcloud, HuggingFace |
| `llama-3.3-70b-instruct` | 6 | OpenRouter, Groq, Cloudflare, GitHub Models, OVHcloud, HuggingFace |
| `gpt-oss-20b` | 6 | OpenRouter, Cerebras, Groq, Cloudflare, OVHcloud, HuggingFace |
| `llama-3.1-8b` | 5 | Groq, Cloudflare, NVIDIA, GitHub Models, HuggingFace |
| `llama-4-scout` | 4 | Groq, Cloudflare, GitHub Models, HuggingFace |
| `deepseek-v4-flash` | 4 | OpenRouter, NVIDIA, OpenCode Zen, HuggingFace |
| `gemma-3-12b-it` | 4 | Google AI, Cloudflare, OpenRouter, HuggingFace |
| `gemma-4-26b-a4b-it` | 3 | OpenRouter, Cloudflare, HuggingFace |
| `kimi-k2.6` | 3 | OpenRouter, Cloudflare, NVIDIA |
| `nemotron-3-120b` | 3 | OpenRouter, Groq, NVIDIA |
| `nemotron-3-nano-30b` | 3 | OpenRouter, NVIDIA, HuggingFace |
| `llama-4-maverick` | 4 | Groq, OpenRouter, NVIDIA, HuggingFace |
| `gemma-4-31b-it` | 3 | OpenRouter, NVIDIA, HuggingFace |
| `nemotron-3-ultra` | 3 | OpenRouter, OpenCode Zen, NVIDIA |
| `mistral-large` | 2 | Mistral, GitHub Models |
| `command-r-plus` | 2 | Cohere, GitHub Models |
| `qwen3-next-80b-a3b` | 1 | OpenRouter |
| `big-pickle` | 1 | OpenCode Zen |
| `north-mini-code` | 1 | OpenCode Zen |
| `openrouter-free` | 1 | OpenRouter |
| *LLM7.io-Modelle:* | | |
| `deepseek-r1-0528` | 1 | LLM7.io |
| `qwen3-235b` | 1 | LLM7.io |
| `mistral-small-3.2` | 1 | LLM7.io |
| `codestral-latest` | 1 | LLM7.io |

### Multi-Instance (zusätzlich)

Master-Config: 70 base + 48 Slave = **118 Deployments** (24 model_names × 2 Slaves zusätzlich)

Jeder Slave hat eigene 70 Deployments (andere API-Keys).  
→ Effektiv 3× Rate-Limit pro Provider (Master + Slave1 + Slave2).

---

## 4. Routing & Fallback

### Router Settings (config.yaml)

```yaml
router_settings:
  routing_strategy: simple-shuffle   # Zufällige Verteilung
  num_retries: 2
  retry_after: 5                     # Sekunden vor Retry
  allowed_fails: 3                   # Fehlschläge vor Cooldown
  cooldown_time: 30                  # 30s Cooldown (vom Benutzer geändert)
```

### Fallback-Chain

```yaml
fallbacks:
  - {"gpt-oss-120b":            ["gpt-oss-20b", "llama-3.3-70b-instruct", "nemotron-3-120b", "mistral-large"]}
  - {"llama-3.3-70b-instruct":  ["llama-3.1-8b", "mistral-large", "gpt-oss-20b", "gemma-3-12b-it"]}
  - {"gpt-oss-20b":             ["llama-3.1-8b", "gemma-3-12b-it", "deepseek-v4-flash", "mistral-large"]}
  - {"llama-3.1-8b":            ["gemma-3-12b-it", "deepseek-v4-flash", "qwen3-next-80b-a3b", "llama-4-scout"]}
  - {"qwen3-next-80b-a3b":      ["mistral-large", "llama-3.3-70b-instruct", "gpt-oss-120b", "deepseek-v4-flash"]}
  - {"kimi-k2.6":               ["gpt-oss-120b", "llama-3.3-70b-instruct", "nemotron-3-120b", "mistral-large"]}
  - {"mistral-large":           ["llama-3.3-70b-instruct", "command-r-plus", "gpt-oss-120b", "nemotron-3-ultra"]}
  - {"command-r-plus":          ["mistral-large", "llama-3.3-70b-instruct", "nemotron-3-ultra"]}
  - {"llama-4-maverick":        ["gpt-oss-120b", "llama-3.3-70b-instruct", "nemotron-3-120b", "mistral-large"]}
  - {"gemma-4-31b-it":          ["gemma-3-12b-it", "gpt-oss-20b", "llama-3.3-70b-instruct", "mistral-large"]}
  - {"*":                       ["llama-3.1-8b", "gpt-oss-20b", "gemma-3-12b-it", "deepseek-v4-flash", "openrouter-free"]}
```

### Context-Window-Fallback

```yaml
context_window_fallbacks:
  - {"llama-3.1-8b":        ["llama-3.3-70b-instruct", "gpt-oss-120b", "mistral-large", "nemotron-3-120b"]}
  - {"qwen3-next-80b-a3b":  ["mistral-large", "llama-3.3-70b-instruct", "gpt-oss-120b"]}
  - {"gemma-3-12b-it":      ["mistral-large", "llama-3.3-70b-instruct", "gpt-oss-120b"]}
  - {"deepseek-v4-flash":   ["mistral-large", "llama-3.3-70b-instruct", "nemotron-3-ultra"]}
  - {"north-mini-code":     ["deepseek-v4-flash", "mistral-large", "llama-3.3-70b-instruct"]}
```

---

## 5. Dateistruktur

```
/home/sb/github/litellm-free-models/
├── config.template.yaml         # Single Source of Truth (24 Modelle, 70 Deployments, 13 Provider) mit {{ENV_VAR}}
├── config.yaml                  # Generiert aus config.template.yaml via render-config.py
├── render-config.py             # Template-Renderer (Substitution + Provider-Filter + OR-Free-Fallback)
├── find-shared-models.py        # Live-Provider-Abfrage + Overlap-Report + Auto-Apply
├── .env.example                 # Vorlage für API-Keys (14 Variablen)
├── docker-compose.yaml          # Docker-Compose für Single-Instance
├── Dockerfile                   # Optionales Custom Image
├── Makefile                     # Helper-Kommandos (render-config, docker-compose-up, k8s-apply, …)
├── AGENTS.md                    # Diese Datei
├── README.md                    # Projekt-Dokumentation
├── PRICING.md                   # Kosteninformationen pro Provider
│
├── k8s/                         # Kubernetes (Single-Instance)
│   ├── configmap.yaml           # ConfigMap (regenerierbar via make k8s-configmap)
│   ├── deployment.yaml          # Deployment (1 Replica, 500m CPU / 512Mi RAM)
│   ├── service.yaml             # ClusterIP Service (Port 4000)
│   ├── ingress.yaml             # Optionaler Ingress
│   ├── secret.yaml.template     # Secret-Template (alle 14 Keys)
│   └── namespace.yaml           # Namespace: litellm-free-models
│
├── .opencode/skill/sync-free-models/SKILL.md  # Agent-Skill für Auto-Sync
├── .cache/                      # Lokaler Cache (z.B. litellm-prices.json)
│
└── multi-instance/              # Master + 2 Slaves
    ├── master/
    │   ├── config.yaml          # Generiert (1198+ Z., 118 Deployments)
    │   └── .env.example
    ├── slave1/.env.example
    ├── slave2/.env.example
    ├── generate-config.py       # Generator-Script
    ├── docker-compose.yaml      # Orchestriert Master + 2 Slaves
    ├── k8s/                     # Kubernetes-Manifeste
    │   ├── namespace.yaml
    │   ├── kustomization.yaml
    │   ├── master/  (configmap, deployment, service)
    │   ├── slave/   (configmap, deployment, service)
    │   └── secret.yaml.template
    └── README.md                # Multi-Instance-Doku
```

---

## 6. Deployment

### Single-Instance

```bash
# Docker Compose
docker compose --env-file .env up -d

# Kubernetes
make k8s-apply
```

### Multi-Instance

```bash
cd multi-instance
python3 generate-config.py
# .env-Dateien befüllen (master/, slave1/, slave2/)
docker compose up -d
```

---

## 7. Status & Bekannte Einschränkungen

### Abgeschlossen
- ✅ 13 Provider recherchiert und integriert (12 + OVHcloud)
- ✅ 24 Modelle mit Overlap-Matrix optimiert
- ✅ 4 Config-Bugs gefixt (Cloudflare Suffix, Cerebras Deprecation, Cloudflare Deepseek)
- ✅ 6 neue Provider hinzugefügt (Mistral, Cohere, GitHub Models, OpenCode Zen, LLM7.io, HuggingFace)
- ✅ 13. Provider OVHcloud (anonymer Free-Tier ohne API-Key)
- ✅ 3 Provider abgelehnt (Vercel AI Gateway — zu wenig Free-Kontingent; Pollinations.ai, UncloseAI, G4F.dev — Reverse-Proxy mit fragwürdiger Legalität/Reliabilität)
- ✅ K8s-Manifeste aktualisiert (configmap, secret template)
- ✅ docker-compose.yaml aktualisiert (+6 Env-Vars für neue Provider)
- ✅ Multi-Instance-Setup (Master + 2 Slaves) in `multi-instance/`
- ✅ Multi-Instance-K8s-Manifeste (ConfigMap, Deployment, Service, Secret-Template, Kustomize)
- ✅ Configmap.yaml mit aktuellem Config-Stand
- ✅ **Template-Pipeline** (`config.template.yaml` → `config.yaml` via `render-config.py`)
  mit `{{ENV_VAR}}`-Substitution, Provider-Filter, OpenRouter-Free-Fallback
- ✅ **Kosten-Report** via LiteLLM-Referenz-DB
  (`https://models.litellm.ai/`-Datenquelle, 24h-Cache)
- ✅ **Auto-Apply** via `find-shared-models.py --apply`
  (schreibt ins Template, ruft render-config.py, regeneriert multi-instance)
- ✅ **Agent-Skill** `sync-free-models` für OpenCode

### Offen / Einschränkungen
- ❌ Keine API-Keys vorhanden → keine Live-Tests möglich
- ❌ Kein CI/CD (Lint/Test-Pipeline)
- ❌ Kein automatisches Config-Validieren in der Pipeline (`make check-config` manuell)
- ❌ OVHcloud Free-Tier ist anonymer Single-IP-Limit (2 RPM/IP/Modell) — in
  Multi-Instance-Setups eventuell problematisch

---

## 8. Wichtige Entscheidungen

1. **Provider-Präfixe**: `openrouter/`, `cerebras/`, `groq/`, `cloudflare/`, `gemini/` — von LiteLLM automatisch ans API-Routing weitergeleitet. `openai/` für NVIDIA, GitHub Models, OpenCode Zen, LLM7.io und OVHcloud mit je eigener `api_base`.
2. **Kein PyYAML im Generator**: `render-config.py`, `generate-config.py` und `find-shared-models.py` machen zeilenbasiertes YAML-Parsing, weil PyYAML in der Umgebung nicht installiert ist.
3. **Slave-Config per Volume-Mount**: Slaves referenzieren `../config.yaml` (base config) — kein separates Generieren nötig. Nur Master-Config muss bei Änderungen neu generiert werden.
4. **Multi-Instance K8s-Manifeste**: ConfigMap, Deployment, Service und Secret-Template in `multi-instance/k8s/`. Master- und Slave-ConfigMaps werden per `generate-config.py` erzeugt.
5. **Reverse-Proxy abgelehnt**: Pollinations.ai, UncloseAI, G4F.dev sind Reverse-Proxies ohne eigene Modelle — aus rechtlichen/Reliabilitätsgründen nicht aufgenommen.
6. **LLM7.io Free-Tier**: Funktioniert mit `api_key: "unused"` (bzw. `os.environ/LLM7IO_API_KEY` mit Default `unused`). Für höhere Limits kostenloses Token von token.llm7.io.
7. **HuggingFace via native-Prefix**: Nutzt `huggingface/<org>/<model>` (LiteLLM-native), nicht das OpenAI-kompatible Format — weil LiteLLM das automatisch zur HF Inference API routet.
8. **OVHcloud anonymer Free-Tier**: Anonymer Zugriff auf `oai.endpoints.kepler.ai.cloud.ovh.net/v1` ohne API-Key (2 RPM/IP/Modell). `api_key: ""` in `config.yaml` (bzw. `{{OVHCLOUD_API_KEY}}` im Template). `render-config.py` ersetzt den Platzhalter durch `""` wenn die Variable fehlt.
9. **Template als Single Source of Truth**: `config.template.yaml` enthält `{{ENV_VAR}}`-Platzhalter. `render-config.py` rendert daraus `config.yaml`. Direkte Edits an `config.yaml` werden beim nächsten Render überschrieben. `find-shared-models.py --apply` schreibt ins Template und ruft `render-config.py` auf.
10. **OpenRouter-Free-Fallback an/aus**: Wenn `OPENROUTER_API_KEY` gesetzt ist → `openrouter-free` an alle Fallback-Chains + Catch-All. Wenn der Key fehlt → `openrouter-free` wird aus allen Chains entfernt (sonst 401 ohne Key).

---

## 9. Commands

```bash
# Single-Instance
make docker-compose-up     # Starten
make docker-compose-down   # Stoppen
make k8s-apply             # Auf K8s deployen
make k8s-delete            # Von K8s entfernen
make check-config          # Config validieren

# Provider-Overlap & Kosten-Check
python3 find-shared-models.py              # Standard-Lauf (Dry-Run + Report)
python3 find-shared-models.py --refresh-pricing  # Preise neu laden
python3 find-shared-models.py --no-pricing      # ohne Preis-DB
python3 find-shared-models.py --apply           # Aenderungen in config.template.yaml schreiben + rendern
python3 find-shared-models.py --apply --regen-multi-instance  # + multi-instance regenerieren

# Template -> config.yaml
python3 render-config.py                   # Standard-Render
python3 render-config.py --dry-run         # nur Preview
make k8s-configmap                         # k8s/configmap.yaml aus config.yaml regenerieren

# Multi-Instance (Docker)
cd multi-instance
python3 generate-config.py # Master-Config generieren
docker compose up -d       # Starten
docker compose down        # Stoppen

# Multi-Instance (Kubernetes)
cd multi-instance
python3 generate-config.py # ConfigMaps generieren
kubectl apply -k k8s/      # Deployen (Kustomize)
```

---

## 10. Provider-Overlap & Kosten-Check

Das Script `find-shared-models.py` macht drei Dinge:

1. **Live-Abfrage** aller 13 Provider via `.env`-Keys (`providers-overlap.txt`).
   OVHcloud läuft auch ohne API-Key (anonymer Free-Tier, 2 RPM/IP/Modell).
2. **Gruppierung** nach normalisierten Modellnamen, Filter auf ≥ 2 Provider.
3. **Kosten-Vergleich** (hypothetischer Paid-Tier-Preis pro 1M Tokens) aus
   `model_prices_and_context_window.json` (LiteLLM-Referenz-DB, identisch
   mit `https://models.litellm.ai/`). 24h-Cache unter `.cache/litellm-prices.json`.

Mit dem Skill `sync-free-models` kann der Agent daraus automatisch
Deployment-Eintraege, Fallback-Chains und Multi-Instance-Configs generieren.

**Wichtige Insight:** Die `input_cost_per_token` / `output_cost_per_token`
im Report zeigen den _Paid-Tier_-Preis. Im Free-Tier-Proxy bleiben die
Felder in `config.yaml` weiterhin auf `0`, damit das interne LiteLLM-Cost-
Tracking nicht zuschlaegt. Der Report ist nur ein Sparpotenzial-Vergleich.

---

## 11. Template-Pipeline (`config.template.yaml` → `config.yaml`)

`config.template.yaml` ist die **Single Source of Truth** für die
Proxy-Konfiguration. Sie enthält `{{ENV_VAR}}`-Platzhalter die bei
jedem Render durch Werte aus `.env` ersetzt werden.

```
config.template.yaml    im Repo eingecheckt, hartkodierte Defaults
        │
        │  python3 render-config.py
        ▼
config.yaml             bei jedem Render neu geschrieben
        │
        ├─► LiteLLM-Container
        └─► multi-instance/generate-config.py
```

**Verhalten von `render-config.py`:**

1. **Platzhalter-Substitution**: `{{OPENROUTER_API_KEY}}` → Wert aus `.env`
2. **Provider-Filter**: Wenn ein required Key fehlt, wird der
   Provider-Block (inkl. Kommentar-Header) komplett aus `model_list`
   entfernt. OVHcloud ist die Ausnahme (anonymer Free-Tier, akzeptiert
   leeren Key).
3. **OpenRouter-Free-Fallback**: Wenn `OPENROUTER_API_KEY` gesetzt ist,
   wird `openrouter-free` automatisch an jede Fallback-Chain und an
   den Catch-All `*` angehaengt. Wenn der Key fehlt, wird es wieder
   aus allen Chains entfernt.
4. **Orphan-Cleanup**: Fallback-Eintraege die auf entfernte
   `model_names` zeigen werden automatisch geloescht.
5. **Atomare Writes** mit `config.yaml.bak.<timestamp>`-Backup.

**Auslöser** (Wann wird gerendert?):

- Manuell: `make render-config` oder `python3 render-config.py`
- Vor `docker-compose-up` / `k8s-apply`: Makefile-Dependencies
- Nach `find-shared-models.py --apply`: automatisch
- Vor K8s-ConfigMap: `make k8s-configmap`
