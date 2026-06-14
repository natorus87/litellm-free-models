---
name: Bug Report
about: Report a bug or unexpected behavior in the LiteLLM free-models proxy
title: "[bug] "
labels: bug
assignees: ""
---

## Beschreibung

Was ist passiert? Was hast du erwartet?

## Reproduktion

Minimale Schritte, um den Bug zu reproduzieren:

1. `git checkout <commit>`
2. `cp .env.example .env` (Keys gesetzt: …)
3. `make docker-compose-up`
4. `curl -X POST http://localhost:4000/v1/chat/completions -d '…'`
5. Siehe Fehler: …

## Erwartetes Verhalten

Was sollte passieren?

## Tatsächliches Verhalten

Was passiert tatsächlich? (Fehlermeldung, Stacktrace, HTTP-Status, etc.)

## Logs

```
docker logs litellm-free-models 2>&1 | tail -100
```

oder

```
kubectl logs -n litellm-free-models deploy/litellm-free-models
```

> **WICHTIG: Keine API-Keys posten!** Vor dem Posten mit
> `sed -E 's/(KEY=).+/\1***REDACTED***/' .env` oder ähnlich bereinigen.

## Umgebung

- **Python-Version:** (Output von `python3 --version`)
- **OS:** (Ubuntu 22.04, macOS 15, …)
- **Deployment-Art:** Single-Instance (Docker Compose / Kubernetes) oder
  Multi-Instance (Master + Slaves)
- **LiteLLM-Version:** (Output von `docker exec litellm-free-models pip show litellm | grep Version`)
- **Betroffener Provider:** (OpenRouter, Cerebras, …)
- **Betroffenes Modell:** (gpt-oss-120b, llama-3.3-70b-instruct, …)

## Zusätzlicher Kontext

Sonstige Hinweise, Screenshots, verwandte Issues, etc.
