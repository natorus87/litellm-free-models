---
name: Bug Report
about: Report a bug or unexpected behavior in the LiteLLM free-models proxy
title: "[bug] "
labels: bug
assignees: ""
---

## Description

What happened? What did you expect?

## Reproduction

Minimal steps to reproduce the bug:

1. `git checkout <commit>`
2. `cp .env.example .env` (keys set: …)
3. `make docker-compose-up`
4. `curl -X POST http://localhost:4000/v1/chat/completions -d '…'`
5. See error: …

## Expected Behavior

What should happen?

## Actual Behavior

What actually happens? (error message, stack trace, HTTP status, etc.)

## Logs

```
docker logs litellm-free-models 2>&1 | tail -100
```

or

```
kubectl logs -n litellm-free-models deploy/litellm-free-models
```

> **IMPORTANT: Never post API keys!** Sanitize before posting with
> `sed -E 's/(KEY=).+/\1***REDACTED***/' .env` or similar.

## Environment

- **Python version:** (output of `python3 --version`)
- **OS:** (Ubuntu 22.04, macOS 15, …)
- **Deployment type:** single instance (Docker Compose / Kubernetes) or
  multi-instance (master + slaves)
- **LiteLLM version:** (output of `docker exec litellm-free-models pip show litellm | grep Version`)
- **Affected provider:** (OpenRouter, Cerebras, …)
- **Affected model:** (gpt-oss-120b, llama-3.3-70b-instruct, …)

## Additional Context

Other notes, screenshots, related issues, etc.
