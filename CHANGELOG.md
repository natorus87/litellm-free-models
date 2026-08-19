# Changelog

All notable changes to this project are documented here. The project follows
Semantic Versioning.

## [Unreleased]

### Added

- Added the current free LLM7 `gemini-3.1-flash-lite` and `minimax-m2.7`
  routes after live authenticated tests.
- Hetzner Experiments Inference as the sixteenth free provider, with
  `qwen3.6-35b-a3b` and multimodal `qwen3.8-27b`, OpenAI-compatible catalog
  discovery, onboarding/env/Kubernetes/multi-instance wiring, conservative
  unpublished-limit budgets, fallbacks, and estimated savings documentation.

### Fixed

- Restricted LLM7 discovery and routing to live `turbo` models with
  `usage_based_only: false`; removed ten stale or paid LLM7 deployments and
  updated anonymous/free-token limits and dashboard URLs.
- Made OpenRouter `embedding-liquid` fail fast (`timeout: 5`, no retry) so a
  free-tier `Retry-After: 60` response cannot hide a one-minute stall behind
  the successful retry's sub-second provider duration.
- Prevented slow `gpt-oss-120b` providers from consuming the former 120-second
  per-attempt timeout under concurrent uncached load. Both GPT-OSS pools now
  use a 20-second deployment timeout and one retry; router defaults use a
  one-second retry delay, cooldown after one failure for 60 seconds, and a
  30-second ceiling for other deployments.
- Documented that routing/load tests must use unique prompts and explicitly
  bypass the five-minute Redis response cache.
- Verified the fix with 24 unique requests at concurrency four: 24/24
  succeeded, maximum latency fell from over 135 seconds to 41.33 seconds,
  and the complete run fell from 315.07 seconds to 43.67 seconds.
- Extended the timeout policy by workload: live-tested Llama 3.3 70B and
  Gemma 4 31B pools now fail over after 20 seconds, embeddings after 15
  seconds, while speech (60s) and transcription (120s) retain media-safe
  limits. Other chat deployments inherit the 30-second global ceiling.

## [0.2.0] - 2026-08-19

### Added

- Z.AI with the zero-price `glm-4.5-flash`, `glm-4.7-flash`, and
  vision-capable `glm-4.6v-flash` aliases.
- ElevenLabs Scribe v2 as a second backend for `audio-transcription`, plus the
  provider-specific `elevenlabs-scribe-v2` alias.
- Poolside Laguna S 2.1 through Poolside, OpenCode Zen, and OpenRouter.
- Free embedding aliases for Gemini, Cohere, Mistral, OpenRouter/NVIDIA
  Nemotron text and vision models, and Liquid LFM2.5 Embedding.
- Groq speech/transcription aliases and an authenticated native Cloudflare
  image-generation route.
- Two newly verified OpenRouter chat aliases: `dots-3-note-preview` and
  `lfm-2.5-2.6b`.
- Generated `MODEL_PRICING.md` covering every alias with an official,
  LiteLLM-database, or clearly marked estimated reference price and saving.
- Live provider catalog synchronization for Poolside and Z.AI, plus the
  separate OpenRouter embedding catalog with modality-aware chat exclusion.
- Guided key setup for all current providers, GitHub Actions sync secrets,
  Kubernetes secret templates, and multi-instance key propagation.
- Research report on additional free providers under
  `research/free-model-providers-2026/`.
- Project banner and generated provider/deployment matrices.

### Changed

- Updated the pinned LiteLLM image from `v1.92.0` to `v1.97.0` in Docker,
  Compose, Kubernetes, and multi-instance manifests.
- Expanded the effective configuration to 15 providers, 69 aliases, and 155
  direct deployments; the generated master/slave setup contains 293 routes.
- Improved provider discrimination for OpenAI-compatible backends so a model
  vendor in the path cannot override the authoritative API base.
- Expanded catalog retries, stale-deployment reporting, paid-model filtering,
  pricing estimates, generated documentation, and invariant coverage.
- Increased the test suite from 109 to 122 passing tests.

### Removed

- GitHub Models after the service retired on 2026-07-30 and live catalog/API
  checks returned HTTP 404/410.
- Six OpenRouter `:free` deployments that now return HTTP 404. Their paid
  replacements were deliberately not adopted; affected aliases continue via
  other free providers where available.
- Retired or unavailable model routes discovered by the live catalog audit.

### Verified

- Live HTTP 200 inference through the LiteLLM proxy for Z.AI GLM Flash,
  ElevenLabs Scribe v2, Poolside Laguna S 2.1, both new OpenRouter chat models,
  and all three new OpenRouter embedding aliases.
- Docker readiness/health, Compose validation, 23 Kubernetes resources,
  generated documentation drift, lint, and all 122 tests.

## [0.1.0]

- Initial public release.

[0.2.0]: https://github.com/natorus87/litellm-free-models/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/natorus87/litellm-free-models/releases/tag/v0.1.0
