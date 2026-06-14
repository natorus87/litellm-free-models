---
name: Config Question
about: Get help configuring the proxy
title: "[question] "
labels: question
assignees: ""
---

## Frage

Was möchtest du konfigurieren? Was hast du bereits versucht?

## Setup

- [ ] Single-Instance (Docker Compose)
- [ ] Single-Instance (Kubernetes)
- [ ] Multi-Instance (Docker Compose)
- [ ] Multi-Instance (Kubernetes)
- [ ] Bare-Metal (`python3 render-config.py && litellm --config config.yaml`)

## `.env`-Status

Welche API-Keys sind gesetzt? (Namen reichen — **keine Werte posten!**)

- [ ] `OPENROUTER_API_KEY`
- [ ] `CEREBRAS_API_KEY`
- [ ] `GROQ_API_KEY`
- [ ] `CLOUDFLARE_API_KEY` + `CLOUDFLARE_API_BASE`
- [ ] `GEMINI_API_KEY`
- [ ] `NVIDIA_API_KEY`
- [ ] `MISTRAL_API_KEY`
- [ ] `COHERE_API_KEY`
- [ ] `GITHUB_TOKEN`
- [ ] `OPENCODE_ZEN_API_KEY`
- [ ] `LLM7IO_API_KEY`
- [ ] `HF_TOKEN`
- [ ] `OVHCLOUD_API_KEY` (optional)

## Render-Output

Output von `python3 render-config.py 2>&1 | head -50`:

```
(hier einfügen)
```

## Fehlermeldung

Falls vorhanden, die exakte Fehlermeldung (Logs, Traceback, etc.).
