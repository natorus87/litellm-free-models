---
name: Feature Request
about: Suggest a new provider, model, or feature
title: "[feat] "
labels: enhancement
assignees: ""
---

## Problem

What problem does this proposal solve? Who is affected?

Example: "Cerebras is always saturated these days, a second provider
for `gpt-oss-120b` would add resilience."

## Idea

Describe the proposed approach as concretely as possible:

- Which provider / which model?
- API format: `openrouter/`, `openai/` with its own `api_base`, `gemini/`, …?
- Free-tier link + RPM/RPD limits?
- Auth method: API key, OAuth, anonymous free tier?
- Existing LiteLLM provider mapping? (see
  [LiteLLM Providers](https://docs.litellm.ai/docs/providers))

### Provider Info (if a new provider)

| Field           | Value                                                |
| --------------- | --------------------------------------------------- |
| Display name    |                                                     |
| API key env var | (e.g. `MYPROVIDER_API_KEY`)                         |
| API base        | (e.g. `https://api.myprovider.com/v1`)              |
| RPM (free)      |                                                     |
| Auth            | API key / OAuth / anonymous free tier               |
| LiteLLM prefix  | (e.g. `myprovider/`)                                |
| Free-tier link  |                                                     |
| Models          | (list of model_name → upstream-name mappings)      |

## Alternatives

What alternatives did you consider? Why aren't they ideal?

## Additional Context

Mockups, example requests, related PRs / issues, etc.
