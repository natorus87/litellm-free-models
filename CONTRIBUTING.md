# Contributing zu `litellm-free-models`

Danke für dein Interesse, zum Projekt beizutragen! Dieses Dokument
beschreibt den Workflow für Issues, Pull Requests und lokale Tests.

---

## 1. Issue-Workflow

Bevor du Code änderst, **öffne immer zuerst ein Issue** (außer bei
Tippfehlern in Doku/Kommentaren).

### Bug-Reports

Verwende das Template `.github/ISSUE_TEMPLATE/bug_report.md`. Ein guter
Bug-Report enthält:

- Klare Beschreibung des Problems
- Reproduktion (Befehle, `.env`-Status, Docker/K8s-Setup)
- Erwartetes vs. tatsächliches Verhalten
- Relevante Log-Auszüge (`docker logs`, `kubectl logs`, `python3 …`)
- Umgebung (Python-Version, OS, LiteLLM-Version)

> **Wichtig:** **Keine API-Keys posten!** Vor dem Posten Logs mit
> `sed 's/\(KEY=\).*/\1***REDACTED***/' .env` oder ähnlich bereinigen.

### Feature-Requests

Verwende `.github/ISSUE_TEMPLATE/feature_request.md`. Beschreibe:

- Welches Problem gelöst wird
- Konkrete Idee / Mock-API
- Alternativen, die du erwogen hast
- Bei neuen Providern: Free-Tier-Link, RPM, Auth-Verfahren

### Konfigurationsfragen

Für "Wie konfiguriere ich X?" → `.github/ISSUE_TEMPLATE/config_question.md`.

---

## 2. Pull-Request-Workflow

```text
1.  Fork   das Repo
2.  Clone  deinen Fork
3.  Branch feat/<kurzname>  oder  fix/<kurzname>
4.  Code   schreiben + Tests schreiben
5.  make test              # alle Tests grün
6.  make render-config     # Pipeline läuft fehlerfrei
7.  Commit mit Conventional-Commits-Prefix
8.  Push   → Pull Request öffnen → CI muss grün sein
```

### Branch-Naming

- `feat/<name>` — neues Feature
- `fix/<name>` — Bug-Fix
- `docs/<name>` — Doku-only
- `chore/<name>` — Refactoring, Tooling
- `test/<name>` — nur Tests

### Commit-Messages (Englisch)

Verwende [Conventional Commits](https://www.conventionalcommits.org/):

```text
feat: add OVHcloud as 13th provider
fix: cloudflare deepseek-v4-flash does not exist
docs: clarify OVHcloud anonymous free tier
test: add render-config orphan-cleanup test
chore: bump litellm version in dockerfile
```

Breaking Changes markieren mit `!`:

```text
feat!: rename openrouter-free to openrouter-default
```

---

## 3. Code-Style

### Python

- **Version:** Python 3.10+ (CI testet 3.10, 3.11, 3.12, 3.13)
- **Dependencies:** **Nur Standard-Library** (`json`, `os`, `re`, `urllib`,
  `pathlib`, `argparse`, `dataclasses`, …). **Kein PyYAML, kein requests,
  kein httpx.** Das Projekt läuft überall ohne `pip install`.
- **Style:** PEP 8, 4 Spaces, `snake_case`, Type-Hints
  (`from __future__ import annotations`).
- **Docstrings:** Deutsch oder Englisch — pro Datei konsistent.
- **Keine Kommentare**, die offensichtlichen Code wiederholen. Nur
  Begründungen für nicht-offensichtliche Entscheidungen.
- **Print statt Logging:** CLI-Scripts dürfen `print()` benutzen.

### YAML (`config.template.yaml`)

- 2-Space-Indent
- Provider-Header als `# === Provider: <Name> ===` Kommentar
- Modelle alphabetisch sortiert nach `model_name`
- `rpm:` / `api_key:` immer explizit setzen
- Kommentare in Englisch

### Tests

- `pytest` mit Dateinamen `test_<modul>.py` in `tests/`
- Tests für **neue Features sind verpflichtend**
- Bestehende Tests dürfen nicht entfernt werden — nur erweitern
- `make test` muss grün bleiben

---

## 4. Lokale Verifikation

Bevor du einen PR öffnest:

```bash
# 1. Alle Tests grün
make test

# 2. Render-Pipeline läuft
make render-config

# 3. Dry-Run zeigt keinen ungewollten Diff
git diff config.yaml
```

CI auf GitHub Actions läuft **identisch** (Python 3.10–3.13,
`make test` + `python3 render-config.py --dry-run`). Wenn CI rot ist,
wird der PR nicht gemergt.

---

## 5. Naming-Konventionen

### Provider

- Schlüssel in `providers_config.py`: `lowercase`, keine Sonderzeichen
  (z.B. `"openrouter"`, `"ovhcloud"`, `"huggingface"`).
- Anzeigename: offizieller Markenname (z.B. `"OpenRouter"`, `"OVHcloud"`).
- API-Prefix in LiteLLM: `openrouter/`, `cerebras/`, `groq/`,
  `cloudflare/`, `gemini/`, `mistral/`, `cohere/`, `huggingface/`.
  Für OpenAI-kompatible Provider (`openai/`) wird der Prefix durch
  `api_base` ersetzt (NVIDIA, GitHub Models, OpenCode Zen, LLM7.io,
  OVHcloud).

### Modelle

- `model_name` (LiteLLM-public): `lowercase`, Bindestriche
  (z.B. `gpt-oss-120b`, `llama-3.3-70b-instruct`).
- Versions-Suffixe: `-it`, `-instruct`, `-fp8`, `-fp8-fast`.
- Kein Provider-Name im `model_name` (Provider wird über
  `litellm_params.model` abgebildet).

### Deployments

- Pro Provider genau **ein** Deployment pro `model_name`
  (Load-Balancing läuft über `simple-shuffle`).
- Pro Provider unterschiedliche `model_name`-Werte erlaubt
  (z.B. `gpt-oss-120b` von OpenRouter und `gpt-oss-120b` von OVHcloud
  → 2 Deployments, 1 `model_name`).

### Fallback-Chains

- Reihenfolge: ähnliche Qualität zuerst, leichtere Modelle zuletzt
- Maximal 4–5 Einträge pro Chain
- Catch-All `*` als letzte Chain

---

## 6. Was NICHT gemergt wird

- Provider ohne echten Free-Tier (z.B. reines Paid-Only mit Trial)
- Reverse-Proxies mit fragwürdiger Legalität/Reliabilität
  (z.B. Pollinations.ai, UncloseAI, G4F.dev)
- Code, der neue externe Dependencies einführt
- Änderungen an `config.yaml` direkt (immer `config.template.yaml`
  bearbeiten und `make render-config` laufen lassen)

---

## 7. Lizenz

Mit deinem Beitrag stimmst du zu, dass dein Beitrag unter der
[MIT-Lizenz](./LICENSE) des Projekts lizenziert wird.
