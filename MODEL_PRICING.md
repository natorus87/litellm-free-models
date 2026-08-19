# Reference prices and estimated savings

> Snapshot: 2026-08-19 · 71 configured aliases plus the native image route · operational proxy price: **$0** within provider free-tier limits.

These are comparison prices, not billing values. Official public list prices have priority, then the cheapest positive equivalent in LiteLLM's pricing database. Missing values use a conservative, clearly labelled size-band estimate. They are intentionally **not** written to `model_info`, so LiteLLM spend tracking continues to reflect the real free-tier cost.

Coverage: **13 official**, **29 LiteLLM DB**, **30 estimated**.

## Token-priced models

Savings assume 1M total tokens split 50% input / 50% output. Multiply the `Saving / 1M mix` column by your monthly millions of mixed tokens.

| Alias | Mode | Input / 1M | Output / 1M | Saving / 1M mix | Basis |
|---|---:|---:|---:|---:|---|
| `command-r-plus` | chat | $2.500 | $10.000 | **$6.250** | official: Cohere |
| `kimi-k2.7-code` | chat | $0.950 | $4.000 | **$2.475** | LiteLLM DB: `dashscope/kimi-k2.7-code` |
| `qwen3.5-397b-a17b` | chat | $0.600 | $3.600 | **$2.100** | LiteLLM DB: `openrouter/qwen/qwen3.5-397b-a17b` |
| `codestral-latest` | chat | $1.000 | $3.000 | **$2.000** | LiteLLM DB: `mistral/codestral-latest` |
| `qwen3.6-27b` | chat | $0.600 | $3.000 | **$1.800** | official: Groq |
| `kimi-k2.5` | chat | $0.500 | $2.800 | **$1.650** | LiteLLM DB: `together_ai/moonshotai/Kimi-K2.5` |
| `kimi-k2.6` | chat | $0.500 | $2.000 | **$1.250** | LiteLLM DB: `deepinfra/moonshotai/Kimi-K2-Instruct` |
| `mistral-large` | chat | $0.500 | $1.500 | **$1.000** | LiteLLM DB: `mistral/mistral-large-latest` |
| `nemotron-3-120b` | chat | $0.500 | $1.500 | **$1.000** | LiteLLM DB: `cloudflare/@cf/nvidia/nemotron-3-120b-a12b` |
| `qwen3-next-80b-a3b` | chat | $0.140 | $1.400 | **$0.770** | LiteLLM DB: `deepinfra/Qwen/Qwen3-Next-80B-A3B-Instruct` |
| `big-pickle` | chat | $0.300 | $1.200 | **$0.750** | estimate: unknown-size open-model benchmark |
| `dots-3-note-preview` | chat | $0.300 | $1.200 | **$0.750** | estimate: unknown-size open-model benchmark |
| `elevenlabs-scribe-v2` | audio_transcription | $0.300 | $1.200 | **$0.750** | estimate: unknown-size open-model benchmark |
| `glm-4.5-flash` | chat | $0.300 | $1.200 | **$0.750** | estimate: unknown-size open-model benchmark |
| `glm-4.6v-flash` | chat | $0.300 | $1.200 | **$0.750** | estimate: unknown-size open-model benchmark |
| `glm-4.7-flash` | chat | $0.300 | $1.200 | **$0.750** | estimate: unknown-size open-model benchmark |
| `glm-5.2` | chat | $0.300 | $1.200 | **$0.750** | estimate: unknown-size open-model benchmark |
| `inkling` | chat | $0.300 | $1.200 | **$0.750** | estimate: unknown-size open-model benchmark |
| `kimi-k3` | chat | $0.300 | $1.200 | **$0.750** | estimate: unknown-size open-model benchmark |
| `mimo-v2.5` | chat | $0.300 | $1.200 | **$0.750** | estimate: unknown-size open-model benchmark |
| `minimax-m3` | chat | $0.300 | $1.200 | **$0.750** | estimate: unknown-size open-model benchmark |
| `nemotron-3-ultra` | chat | $0.300 | $1.200 | **$0.750** | estimate: unknown-size open-model benchmark |
| `nemotron-3.5-content-safety` | chat | $0.300 | $1.200 | **$0.750** | estimate: unknown-size open-model benchmark |
| `north-mini-code` | chat | $0.300 | $1.200 | **$0.750** | estimate: unknown-size open-model benchmark |
| `openrouter-free` | chat | $0.300 | $1.200 | **$0.750** | estimate: unknown-size open-model benchmark |
| `step-3.7-flash` | chat | $0.300 | $1.200 | **$0.750** | estimate: unknown-size open-model benchmark |
| `deepseek-v4-pro` | chat | $0.435 | $0.870 | **$0.652** | LiteLLM DB: `deepseek/deepseek-v4-pro` |
| `nemotron-3-nano-30b` | chat | $0.200 | $0.800 | **$0.500** | estimate: 30B hosted open-model band |
| `nemotron-nano-12b-v2-vl` | chat | $0.200 | $0.800 | **$0.500** | estimate: 12B hosted open-model band |
| `qwen3.8-27b` | chat | $0.200 | $0.800 | **$0.500** | estimate: 27B hosted open-model band |
| `llama-4-maverick` | chat | $0.200 | $0.600 | **$0.400** | LiteLLM DB: `groq/meta-llama/llama-4-maverick-17b-128e-instruct` |
| `gpt-oss-120b` | chat | $0.150 | $0.600 | **$0.375** | official: Groq |
| `qwen3-235b` | chat | $0.180 | $0.540 | **$0.360** | LiteLLM DB: `deepinfra/Qwen/Qwen3-235B-A22B` |
| `deepseek-v4-flash-0731` | chat | $0.200 | $0.400 | **$0.300** | LiteLLM DB: `dashscope/deepseek-v4-flash-0731` |
| `gemma-4-31b-it` | chat | $0.150 | $0.400 | **$0.275** | LiteLLM DB: `libertai/gemma-4-31b-it` |
| `qwen2.5-vl-72b-instruct` | chat | $0.130 | $0.400 | **$0.265** | LiteLLM DB: `nebius/Qwen/Qwen2.5-VL-72B-Instruct` |
| `deepseek-r1-0528` | chat | $0.250 | $0.250 | **$0.250** | LiteLLM DB: `hyperbolic/deepseek-ai/DeepSeek-R1-0528` |
| `deepseek-v4-flash` | chat | $0.140 | $0.280 | **$0.210** | LiteLLM DB: `fireworks_ai/deepseek-v4-flash` |
| `deepseek-v3` | chat | $0.200 | $0.200 | **$0.200** | LiteLLM DB: `hyperbolic/deepseek-ai/DeepSeek-V3` |
| `gemma-4-26b-a4b-it` | chat | $0.100 | $0.300 | **$0.200** | LiteLLM DB: `cloudflare/@cf/google/gemma-4-26b-a4b-it` |
| `llama-3.3-70b-instruct` | chat | $0.200 | $0.200 | **$0.200** | LiteLLM DB: `crusoe/meta-llama/Llama-3.3-70B-Instruct` |
| `laguna-s-2.1` | chat | $0.080 | $0.300 | **$0.190** | estimate: 8B hosted open-model band |
| `qwen3.5-9b` | chat | $0.080 | $0.300 | **$0.190** | estimate: 9B hosted open-model band |
| `gpt-oss-20b` | chat | $0.075 | $0.300 | **$0.188** | official: Groq |
| `gpt-oss-safeguard-20b` | chat | $0.075 | $0.300 | **$0.188** | official: Groq |
| `llama-guard-4-12b` | chat | $0.180 | $0.180 | **$0.180** | LiteLLM DB: `deepinfra/meta-llama/Llama-Guard-4-12B` |
| `qwen3-coder-30b-a3b` | chat | $0.070 | $0.270 | **$0.170** | LiteLLM DB: `novita/qwen/qwen3-coder-30b-a3b-instruct` |
| `qwen3-32b` | chat | $0.080 | $0.230 | **$0.155** | LiteLLM DB: `ovhcloud/Qwen3-32B` |
| `mistral-nemo-instruct-2407` | chat | $0.130 | $0.130 | **$0.130** | LiteLLM DB: `ovhcloud/Mistral-Nemo-Instruct-2407` |
| `laguna-xs-2.1` | chat | $0.050 | $0.200 | **$0.125** | estimate: 3B hosted open-model band |
| `lfm-2.5-2.6b` | chat | $0.050 | $0.200 | **$0.125** | estimate: 2.6B hosted open-model band |
| `nemotron-3-nano-omni-30b-a3b-reasoning` | chat | $0.050 | $0.200 | **$0.125** | estimate: 3B hosted open-model band |
| `qwen3.6-35b-a3b` | chat | $0.050 | $0.200 | **$0.125** | estimate: 3B hosted open-model band |
| `nemotron-3.5-lightning-free` | chat | $0.050 | $0.200 | **$0.125** | LiteLLM DB: `openrouter/nvidia/nemotron-3.5-lightning` |
| `nemotron-nano-9b-v2` | chat | $0.040 | $0.160 | **$0.100** | LiteLLM DB: `deepinfra/nvidia/NVIDIA-Nemotron-Nano-9B-v2` |
| `embedding-code` | embedding | $0.150 | $0.000 | **$0.075** | official: Mistral |
| `embedding-general` | embedding | $0.150 | $0.000 | **$0.075** | official: Google |
| `gemma-3-12b-it` | chat | $0.050 | $0.100 | **$0.075** | LiteLLM DB: `deepinfra/google/gemma-3-12b-it` |
| `llama-4-scout` | chat | $0.050 | $0.100 | **$0.075** | LiteLLM DB: `lambda_ai/llama-4-scout-17b-16e-instruct` |
| `gemma-3-4b-it` | chat | $0.040 | $0.080 | **$0.060** | LiteLLM DB: `deepinfra/google/gemma-3-4b-it` |
| `embedding-liquid` | embedding | $0.100 | $0.000 | **$0.050** | estimate: embedding market benchmark |
| `embedding-multilingual` | embedding | $0.100 | $0.000 | **$0.050** | estimate: embedding market benchmark |
| `embedding-nvidia-text` | embedding | $0.100 | $0.000 | **$0.050** | estimate: embedding market benchmark |
| `embedding-nvidia-vl` | embedding | $0.100 | $0.000 | **$0.050** | estimate: embedding market benchmark |
| `llama-3.1-8b` | chat | $0.030 | $0.030 | **$0.030** | LiteLLM DB: `nscale/meta-llama/Llama-3.1-8B-Instruct` |

## Audio and request-priced models

| Alias | Mode | Reference price | Saving at free-tier price | Basis |
|---|---:|---:|---:|---|
| `audio-speech` | audio_speech | $22 / 1M characters | **$22 / 1M characters** | official: Groq |
| `audio-transcription` | audio_transcription | $0.04 / audio hour | **$0.04 / audio hour** | official: Groq |
| `cloudflare-image` | image_generation | $0.01 / image | **$0.01 / image** | estimate: low-cost image API benchmark |
| `lyria-3-clip` | chat | $0.04 / 30s song | **$0.04 / 30s song** | official: Google |
| `lyria-3-pro` | chat | $0.08 / song | **$0.08 / song** | official: Google |
| `whisper-large-v3` | audio_transcription | $0.111 / audio hour | **$0.111 / audio hour** | official: Groq |
| `whisper-large-v3-turbo` | audio_transcription | $0.04 / audio hour | **$0.04 / audio hour** | official: Groq |

## Estimation method

For chat models without a published/database price, the active MoE size (`A3B`, `A17B`, …) or otherwise the visible parameter size selects a conservative hosted-open-model band. Unknown sizes use $0.30 input / $1.20 output per 1M tokens; embeddings use $0.10 / 1M input tokens. Estimates are directional and should not be used for accounting.

## Sources

- [LiteLLM](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json)
- [Groq](https://console.groq.com/docs/models)
- [Google](https://ai.google.dev/gemini-api/docs/pricing)
- [Mistral](https://docs.mistral.ai/models/model-cards/codestral-embed-25-05)
- [Cohere](https://cohere.com/pricing)
