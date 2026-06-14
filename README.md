# LiteLLM Free-Models Proxy

Ein [LiteLLM](https://github.com/BerriAI/litellm)-Proxy, der **ausschließlich kostenlose LLM-APIs** von 13 Providern aggregiert — mit automatischem Load-Balancing, Cooldown und Fallback-Chains. Gleiche Modelle (z. B. `gpt-oss-120b`) sind über mehrere Anbieter hinweg abgedeckt, um Rate-Limits einzelner Free-Tiers zu umgehen.

![Tests](https://img.shields.io/badge/tests-56_passing-brightgreen)
![License](https://img.shields.io/badge/license-MIT-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![LiteLLM](https://img.shields.io/badge/litellm-proxy-orange)

---

## Inhaltsverzeichnis

- [Features](#-features)
- [Quickstart](#-quickstart)
- [Architektur](#-architektur)
- [Provider-Übersicht](#-provider-übersicht)
- [Modelle](#-modelle)
- [Konfiguration](#-konfiguration)
- [Tests](#-tests)
- [Development](#-development)
- [Sync-Workflow](#-sync-workflow)
- [Multi-Instance](#-multi-instance)
- [Contributing](#-contributing)
- [License](#-license)
- [Disclaimer](#-disclaimer)

---

## ✨ Features

- **13 Provider, 24+ Modelle** — OpenRouter, Cerebras, Groq, Cloudflare Workers AI, Google AI Studio, NVIDIA NIM, Mistral, Cohere, GitHub Models, OpenCode Zen, LLM7.io, HuggingFace Inference API, OVHcloud.
- **Automatisches Load-Balancing** — LiteLLM-Router verteilt Requests per `simple-shuffle` auf alle Deployments des gewünschten Modells.
- **Fallback-Chains** — pro Modell eine priorisierte Liste von Ausweichmodellen (z. B. `gpt-oss-120b` → `gpt-oss-20b` → `llama-3.3-70b-instruct`).
- **Anonymer OVHcloud-Tier** — 13. Provider läuft **ohne API-Key** (2 RPM/IP/Modell) und ist sofort einsatzbereit.
- **Live-Pricing-Report** — `find-shared-models.py` zeigt das hypothetische Sparpotenzial gegenüber Paid-Tier-Preisen (LiteLLM-Referenz-DB).
- **Multi-Instance-Setup** — Master + 2 Slaves in `multi-instance/` verdreifachen effektiv die Rate-Limits.
- **Template-Pipeline** — `config.template.yaml` als Single Source of Truth; `render-config.py` rendert daraus `config.yaml` mit `{{ENV_VAR}}`-Substitution und Provider-Filter.
- **56 Unit Tests** — Test-Suite für `render-config`, `find-shared-models`, `providers_config` und `multi-instance` Generator.

---

## 🚀 Quickstart

### 1. Repository klonen

```bash
git clone https://github.com/<your-user>/litellm-free-models.git
cd litellm-free-models
```

### 2. `.env` anlegen

```bash
cp .env.example .env
nano .env
```

**Hinweis zu den API-Keys:** Die meisten Keys sind **optional** — der Proxy läuft auch mit nur einem Teil der Provider. `OPENROUTER_API_KEY` ist die wichtigste Ausnahme: Ohne den Key wird das `openrouter-free`-Modell aus den Fallback-Chains entfernt (sonst gäbe es 401-Fehler). `OVHCLOUD_API_KEY` darf **leer bleiben** für den anonymen Free-Tier.

Eine vollständige Übersicht der Bezugs-URLs findet sich in `.env.example`.

### 3. (Optional) Python-Dependencies

Die Pipeline nutzt ausschließlich die Python-Standardbibliothek — ein `pip install` ist **nicht** erforderlich. Wer den LiteLLM-Server lokal validieren will, braucht allerdings Docker.

### 4. Konfiguration rendern

```bash
make render-config          # oder: python3 render-config.py
```

Dieser Schritt erzeugt `config.yaml` aus `config.template.yaml`, ersetzt `{{ENV_VAR}}`-Platzhalter durch Werte aus `.env` und entfernt Provider-Blöcke ohne gesetzten Key.

### 5. Proxy starten

```bash
make docker-compose-up      # oder: docker compose --env-file .env up -d
```

Der Proxy lauscht auf **Port 4444** (lokal: `http://localhost:4444`) und nutzt intern LiteLLM-Port 4000.

### 6. Test-Request

```bash
curl http://localhost:4444/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-oss-120b",
    "messages": [{"role": "user", "content": "Sag Hallo auf Deutsch."}]
  }'
```

Antwort: JSON-Objekt mit `choices[0].message.content` (OpenAI-kompatibles Format).

---

## 🏗️ Architektur

### Single-Instance (Hauptsetup)

```
                  ┌─────────────────────────────────────────┐
                  │       LiteLLM Proxy (:4000 intern)      │
                  │     Routing: simple-shuffle             │
   Client ──────► │     24 model_names, 70 Deployments      │
   (Port 4444)    │     Cooldown 30s, Retries 2             │
                  └────────────┬────────────────────────────┘
                               │
        ┌──────────┬───────────┼───────────┬──────────┬────────┐
        ▼          ▼           ▼           ▼          ▼        ▼
   OpenRouter  Cerebras     Groq      Cloudflare   NVIDIA  OVHcloud
   (1 RPM)     (30 RPM)  (2-30 RPM)  (10 RPM)   (40 RPM)  (2 RPM)
                                                          (kein Key!)
        +  Google AI, Mistral, Cohere, GitHub Models,
           OpenCode Zen, LLM7.io, HuggingFace
```

### Multi-Instance (3× Rate-Limit)

Im Verzeichnis [`multi-instance/`](multi-instance/README.md) läuft ein zusätzliches Master/Slave-Setup:

```
                  ┌──────────────────────────────────┐
                  │   MASTER (:4000, eigene Keys)    │
   Client ──────► │   70 direkte + 48 Slave-Backends │
                  └──────────────┬───────────────────┘
                                 │
                ┌────────────────┼────────────────┐
                ▼                ▼                ▼
         ┌────────────┐   ┌────────────┐   ┌────────────┐
         │ Direkt     │   │ SLAVE 1    │   │ SLAVE 2    │
         │ (eigene    │   │ :4001      │   │ :4002      │
         │  Keys)     │   │ (andere    │   │ (andere    │
         │            │   │  Keys)     │   │  Keys)     │
         └────────────┘   └────────────┘   └────────────┘
```

Effektiv **3× Rate-Limit pro Provider** (Master + 2 Slaves mit unterschiedlichen Accounts). Detaillierte Anleitung in [`multi-instance/README.md`](multi-instance/README.md).

---

## 📋 Provider-Übersicht

| #  | Provider                | Auth            | RPM (Free)      | Env-Var(s)                                     | Besonderheiten |
|----|-------------------------|-----------------|-----------------|------------------------------------------------|----------------|
| 1  | OpenRouter              | API-Key         | 1               | `OPENROUTER_API_KEY`                           | Catch-All `openrouter-free` |
| 2  | Cerebras                | API-Key         | 30              | `CEREBRAS_API_KEY`                             | `llama3.1-8b` deprecated (27.05.2026) |
| 3  | Groq                    | API-Key         | 2-30            | `GROQ_API_KEY`                                 | Modellabhängig |
| 4  | Cloudflare Workers AI   | API-Token       | 10              | `CLOUDFLARE_API_KEY` + `CLOUDFLARE_API_BASE`    | Suffix `-fp8-fast` |
| 5  | Google AI Studio        | API-Key         | 2               | `GEMINI_API_KEY`                               | Gemini-Modelle |
| 6  | NVIDIA NIM              | API-Key         | 40              | `NVIDIA_API_KEY`                               | OpenAI-kompatibel, Kimi = `moonshotai/kimi-k2-instruct` |
| 7  | Mistral La Plateforme   | API-Key         | 2               | `MISTRAL_API_KEY`                              | Phone-Verification nötig |
| 8  | Cohere                  | API-Key         | 20              | `COHERE_API_KEY`                               | Trial-Key, 1 000 Calls/Monat |
| 9  | GitHub Models           | PAT             | 15              | `GITHUB_TOKEN`                                 | Scope: `models:read`, Azure-Endpoint |
| 10 | OpenCode Zen            | API-Key         | 10              | `OPENCODE_ZEN_API_KEY`                         | Free-Modelle: `deepseek-v4-flash-free`, `big-pickle` |
| 11 | LLM7.io                 | API-Key         | 40 (mit Token)  | `LLM7IO_API_KEY`                               | `unused` reicht für Basis-Tier |
| 12 | HuggingFace Inference   | API-Token       | 30              | `HF_TOKEN`                                     | 150K+ Modelle via `huggingface/<org>/<model>` |
| 13 | OVHcloud AI Endpoints   | **kein Key**    | 2 (anonym)      | `OVHCLOUD_API_KEY` (optional/leer)             | Anonymer Free-Tier, IP-Limit |

Bezugs-URLs für die Keys: siehe Kommentare in [`.env.example`](.env.example).

---

## 🤖 Modelle

Stand: **24 model_names, 70 Deployments** in der Single-Instance-Konfiguration (850+ Zeilen `config.yaml`).

| Modell                       | Provider-Anzahl | Haupt-Provider                              |
|------------------------------|-----------------|---------------------------------------------|
| `gpt-oss-120b`               | 7               | OpenRouter, Cerebras, Groq, Cloudflare, NVIDIA, OVHcloud, HuggingFace |
| `llama-3.3-70b-instruct`     | 6               | OpenRouter, Groq, Cloudflare, GitHub Models, OVHcloud, HuggingFace |
| `gpt-oss-20b`                | 6               | OpenRouter, Cerebras, Groq, Cloudflare, OVHcloud, HuggingFace |
| `llama-3.1-8b`               | 5               | Groq, Cloudflare, NVIDIA, GitHub Models, HuggingFace |
| `llama-4-scout`              | 4               | Groq, Cloudflare, GitHub Models, HuggingFace |
| `deepseek-v4-flash`          | 4               | OpenRouter, NVIDIA, OpenCode Zen, HuggingFace |
| `gemma-3-12b-it`             | 4               | Google AI, Cloudflare, OpenRouter, HuggingFace |
| `llama-4-maverick`           | 4               | Groq, OpenRouter, NVIDIA, HuggingFace |
| `gemma-4-26b-a4b-it`         | 3               | OpenRouter, Cloudflare, HuggingFace |
| `kimi-k2.6`                  | 3               | OpenRouter, Cloudflare, NVIDIA |
| `nemotron-3-120b`            | 3               | OpenRouter, Groq, NVIDIA |
| `nemotron-3-nano-30b`        | 3               | OpenRouter, NVIDIA, HuggingFace |
| `gemma-4-31b-it`             | 3               | OpenRouter, NVIDIA, HuggingFace |
| `nemotron-3-ultra`           | 3               | OpenRouter, OpenCode Zen, NVIDIA |
| `mistral-large`              | 2               | Mistral, GitHub Models |
| `command-r-plus`             | 2               | Cohere, GitHub Models |
| `qwen3-next-80b-a3b`         | 1               | OpenRouter |
| `big-pickle`                 | 1               | OpenCode Zen |
| `north-mini-code`            | 1               | OpenCode Zen |
| `openrouter-free`            | 1               | OpenRouter (Catch-All) |
| `deepseek-r1-0528`           | 1               | LLM7.io |
| `qwen3-235b`                 | 1               | LLM7.io |
| `mistral-small-3.2`          | 1               | LLM7.io |
| `codestral-latest`           | 1               | LLM7.io |

Vollständige Deployment-Matrix und Modellvarianten: siehe [`AGENTS.md`](AGENTS.md) Abschnitt 3.

---

## ⚙️ Konfiguration

Die Konfiguration läuft über eine **Template-Pipeline**:

```
config.template.yaml   (Single Source of Truth, im Repo)
        │
        │  python3 render-config.py
        ▼
config.yaml            (generiert, in .gitignore)
        │
        ├─► LiteLLM-Container (gemountet)
        └─► multi-instance/generate-config.py
```

`config.template.yaml` enthält `{{ENV_VAR}}`-Platzhalter (z. B. `{{OPENROUTER_API_KEY}}`) und Kommentar-Header pro Provider. `render-config.py` führt vier Schritte aus:

1. **Substitution** — `{{ENV_VAR}}` → Wert aus `.env`. Fehlende Keys werden zu leeren Strings.
2. **Block-Filter** — Fehlt ein *required* Key, wird der gesamte Provider-Block (inkl. Kommentar-Header) aus `model_list` entfernt. OVHcloud ist die Ausnahme und akzeptiert einen leeren Key.
3. **OpenRouter-Free-Fallback** — Ist `OPENROUTER_API_KEY` gesetzt, wird `openrouter-free` an jede Fallback-Chain und an den Catch-All `*` angehängt. Fehlt der Key, wird der Eintrag wieder entfernt (sonst 401).
4. **Orphan-Cleanup** — Fallback-Einträge, die auf entfernte `model_names` zeigen, werden gelöscht.

Writes sind atomar mit Timestamp-Backup (`config.yaml.bak.<timestamp>`). Direkte Edits an `config.yaml` werden beim nächsten Render **überschrieben** — Änderungen gehören immer ins Template.

Verwandte Skripte:

- `find-shared-models.py` — Live-Provider-Sync + Pricing-Report (siehe [Sync-Workflow](#-sync-workflow))
- `providers_config.py` — zentrale Provider-Definitionen (Env-Var-Namen, API-Format, RPM, API-URLs)
- `multi-instance/generate-config.py` — Master-/Slave-Config-Generator

---

## 🧪 Tests

```bash
make test                # 56 unit tests, ~1s
```

Die Suite deckt vier Module ab:

- `tests/test_render_config.py` — Substitution, Block-Filter, OpenRouter-Free-Logik
- `tests/test_find_shared_models.py` — Overlap-Gruppierung, Pricing-Cache
- `tests/test_providers_config.py` — Provider-Metadaten-Konsistenz
- `tests/test_multi_instance.py` — Master-/Slave-Generator

Die Tests nutzen ausschließlich die Python-Standardbibliothek (`unittest`).

---

## 🛠️ Development

| Befehl                                                  | Zweck                                                |
|---------------------------------------------------------|------------------------------------------------------|
| `make help`                                             | Alle Targets mit Kurzbeschreibung anzeigen           |
| `make render-config`                                    | `config.template.yaml` → `config.yaml` rendern       |
| `make render-config-dry`                                | Dry-Run (kein Write)                                 |
| `make check-config`                                     | LiteLLM-Dry-Run-Validierung der `config.yaml`        |
| `make k8s-apply`                                        | Alles auf Kubernetes deployen (Namespace, Secret, ConfigMap, Deployment, Postgres) |
| `make k8s-delete`                                       | Alles von Kubernetes entfernen                       |
| `make k8s-logs`                                         | Pod-Logs streamen                                    |
| `make docker-compose-up` / `make docker-compose-down`   | Docker-Compose steuern                               |
| `make docker-build` / `make docker-run`                 | Eigenes Image bauen / starten                        |
| `make test`                                             | 56 Unit-Tests ausführen                              |
| `python3 find-shared-models.py`                         | Provider-Overlap-Report (Dry-Run)                    |
| `python3 find-shared-models.py --apply`                 | Auto-Apply: schreibt ins Template + rendert          |
| `python3 find-shared-models.py --apply --regen-multi-instance` | + Multi-Instance-Configs neu generieren      |
| `python3 find-shared-models.py --refresh-pricing`       | LiteLLM-Pricing-DB neu laden (24h-Cache)             |
| `cd multi-instance && python3 generate-config.py`       | Master-/Slave-Configs generieren                     |

---

## 🔄 Sync-Workflow

Wenn ein Provider neue Modelle hinzufügt oder ein neues Modell über mehrere Provider verfügbar wird:

```bash
# 1. Live-Abfrage aller Provider + Overlap-Report
python3 find-shared-models.py

# 2. Auto-Apply: fehlende Deployments ins Template schreiben,
#    Fallback-Chains aktualisieren, config.yaml rendern
python3 find-shared-models.py --apply

# 3. (Optional) Multi-Instance-Configs neu generieren
python3 find-shared-models.py --apply --regen-multi-instance

# 4. Diff reviewen
git diff

# 5. Tests laufen lassen
make test

# 6. Committen
git add -A
git commit -m "sync: add <model> from <provider>"
```

Das Script `find-shared-models.py`:

1. Fragt **13 Provider live** ab (über die Keys in `.env`; OVHcloud läuft auch ohne Key).
2. Normalisiert Modellnamen und gruppiert nach Overlap (≥ 2 Provider).
3. Vergleicht hypothetische Paid-Tier-Preise aus der LiteLLM-Referenz-DB (`https://models.litellm.ai/`, 24h-Cache unter `.cache/`).
4. Schreibt mit `--apply` neue Deployment-Blöcke ins `config.template.yaml` — bestehende Kommentare, RPMs und Cost-Felder bleiben erhalten.

Ausführlichere Doku zu `find-shared-models.py` und den Ausgabeformaten: [`AGENTS.md`](AGENTS.md) Abschnitt 10.

---

## 📦 Multi-Instance

Im Verzeichnis [`multi-instance/`](multi-instance/README.md) liegt ein vollständiges Master/Slave-Setup:

- **Master** mit 118 Deployments (70 direkte + 48 Slave-Backends)
- **2 Slaves** mit je 70 Deployments unter anderen API-Keys
- Eigene `.env`-Dateien pro Instanz (`master/.env`, `slave1/.env`, `slave2/.env`)
- Eigene Docker-Compose- und Kubernetes-Manifeste (`multi-instance/k8s/`)
- Kustomize-Setup für deklaratives Deployment

Voraussetzung: **3 Sätze API-Keys** (gleiche Provider, unterschiedliche Accounts). Setup-Anleitung in [`multi-instance/README.md`](multi-instance/README.md).

---

## 🤝 Contributing

Beiträge sind willkommen — egal ob neue Provider, neue Modelle, Bug-Fixes oder Doku-Verbesserungen. Bitte:

1. Issue oder Diskussion zuerst, falls die Änderung umfangreich ist.
2. Fork + Feature-Branch.
3. `make test` muss grün sein.
4. `make check-config` muss durchlaufen.
5. PR mit aussagekräftiger Beschreibung öffnen.

Details siehe [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## 📜 License

MIT — siehe [`LICENSE`](LICENSE).

---

## ⚠️ Disclaimer

Dieses Projekt bündelt **Free-Tiers** Dritter. Free-Tiers können jederzeit:

- ihre Rate-Limits ändern,
- Modelle deprecated oder kostenpflichtig machen,
- komplett eingestellt werden.

Es gibt **keine Garantie für Verfügbarkeit, Antwortzeit oder Modell-Qualität**. Der Proxy ist als Bastel-/Entwicklungs-Tool gedacht — nicht für Produktion. Eigene Risikoabschätzung beim Einsatz.
