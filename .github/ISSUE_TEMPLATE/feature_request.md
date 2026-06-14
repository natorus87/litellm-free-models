---
name: Feature Request
about: Suggest a new provider, model, or feature
title: "[feat] "
labels: enhancement
assignees: ""
---

## Problem

Welches Problem löst dieser Vorschlag? Wer ist betroffen?

Beispiel: "Cerebras ist heute immer ausgelastet, ein zweiter Anbieter
für `gpt-oss-120b` würde Resilienz bringen."

## Idee

Beschreibe den vorgeschlagenen Lösungsansatz so konkret wie möglich:

- Welcher Provider / welches Modell?
- API-Format: `openrouter/`, `openai/` mit eigener `api_base`, `gemini/`, …?
- Free-Tier-Link + RPM/RPD-Limits?
- Auth-Verfahren: API-Key, OAuth, anonymer Free-Tier?
- LiteLLM-Provider-Mapping vorhanden? (siehe
  [LiteLLM Providers](https://docs.litellm.ai/docs/providers))

### Provider-Liste (falls neuer Provider)

| Feld            | Wert                                                |
| --------------- | --------------------------------------------------- |
| Anzeigename     |                                                     |
| API-Key Env-Var | (z.B. `MYPROVIDER_API_KEY`)                         |
| API-Base        | (z.B. `https://api.myprovider.com/v1`)              |
| RPM (Free)      |                                                     |
| Auth            | API-Key / OAuth / anonymer Free-Tier                |
| LiteLLM-Prefix  | (z.B. `myprovider/`)                                |
| Free-Tier-Link  |                                                     |
| Modelle         | (Liste der model_name → upstream-name Mappings)    |

## Alternativen

Welche Alternativen hast du erwogen? Warum sind sie nicht ideal?

## Zusätzlicher Kontext

Mockups, Beispiel-Requests, verwandte PRs / Issues, etc.
