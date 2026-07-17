---
name: Config Question
about: Get help configuring the proxy
title: "[question] "
labels: question
assignees: ""
---

## Question

What do you want to configure? What have you already tried?

## Setup

- [ ] Single instance (Docker Compose)
- [ ] Single instance (Kubernetes)
- [ ] Multi-instance (Docker Compose)
- [ ] Multi-instance (Kubernetes)
- [ ] Bare metal (`python3 render-config.py && litellm --config config.yaml`)

## `.env` State

Which API keys are set? (names are enough — **never post values!**)

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

## Render Output

Output of `python3 render-config.py 2>&1 | head -50`:

```
(paste here)
```

## Error Message

If applicable, the exact error message (logs, traceback, etc.).
