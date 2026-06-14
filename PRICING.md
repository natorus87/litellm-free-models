# PRICING.md — LiteLLM Free-Models Proxy Cost Information

> **Stand: 2026-06-14** — 13 Provider (inkl. OVHcloud anonymer Free-Tier).
> Preisdaten aus `model_prices_and_context_window.json`
> (LiteLLM-Referenz-DB, identisch mit `https://models.litellm.ai/`).

This document provides average pricing information for the 13 free-tier LLM API providers used by the LiteLLM Free-Models Proxy. All prices are in USD per 1 million tokens (input + output) unless otherwise noted.

Prices are based on public information as of June 2026 and are subject to change. Always check the provider's official website for the most current pricing.

---

## 1. Provider Pricing Summary

| Provider               | Free Tier Available | Average Input Cost (per 1M) | Average Output Cost (per 1M) | Notes                                                                                     |
|------------------------|---------------------|----------------------------|-----------------------------|-------------------------------------------------------------------------------------------|
| **OpenRouter**         | ✅ Yes               | $0.00 - $3.00              | $0.00 - $9.00               | Free models available, 5.5% fee on paid credits, pass-through pricing for paid models     |
| **Cerebras**           | ✅ Yes               | $0.10 - $0.35              | $0.60 - $0.75               | Free tier + paid developer tier, GPT-OSS-120B: $0.35/$0.75                               |
| **Groq**               | ✅ Yes               | $0.05 - $0.59              | $0.08 - $0.79               | Free tier (100K tokens/day), GPT-OSS-120B: $0.15/$0.60, Llama 3.3 70B: $0.59/$0.79       |
| **Cloudflare Workers AI** | ✅ Yes           | $0.045 - $0.293            | $0.384 - $2.253             | Free tier (10K Neurons/day ≈ 10K tokens), Llama 3.1 8B: ~$0.045/$0.384                   |
| **Google AI Studio**   | ✅ Yes               | $0.00 - $3.50              | $0.00 - $21.00              | Free for Gemini 1.5 Flash, paid: $0.075/$0.30 (Flash), $1.25/$10 (Pro)                  |
| **NVIDIA NIM**         | ✅ Yes               | $0.04 - $0.90              | $0.16 - $0.90               | Free for prototyping, production requires NVIDIA AI Enterprise ($4,500/GPU/year)         |
| **Mistral La Plateforme** | ✅ Yes           | $0.15 - $2.00              | $0.15 - $6.00               | Free tier, Mistral Small: $0.20/$0.60, Mistral Large: $2.00/$6.00                       |
| **Cohere**             | ✅ Yes               | $0.0375 - $2.50            | $0.15 - $10.00              | Free trial keys, Command R: $0.15/$0.60, Command R+: $2.50/$10.00                      |
| **GitHub Models**      | ✅ Yes               | $0.13 - $2.50              | $0.50 - $10.00              | Free tier (rate-limited), paid: $0.00001 per token unit with model multipliers          |
| **OpenCode Zen**       | ✅ Yes               | $0.00 - $0.30              | $0.00 - $1.20               | Several free models, paid models: $0.05-0.30/$0.40-1.20 (cheaper tier)                  |
| **LLM7.io**           | ✅ Yes               | $0.00                      | $0.00                       | All models are free, 2 RPM (40 RPM with free token from token.llm7.io)                    |
| **HuggingFace Inference API** | ✅ Yes       | $0.00                      | $0.00                       | Free Inference API, rate-limited, 150K+ models, no credit card required                   |
| **OVHcloud AI Endpoints** | ✅ Yes (anonymous) | $0.00                      | $0.00                       | **Anonymous free tier**, no API key required, 2 RPM/IP/model. GPT-OSS-120B paid: $0.08/$0.40 per 1M |

---

## 2. Detailed Provider Pricing

### OpenRouter
- **Free Tier**: 50 requests/day, 25+ free models
- **Paid**: Pass-through pricing from providers + 5.5% fee on credits
- **Example Models**:
  - Free models: Always free, rate-limited
  - Paid models: Varies by provider (e.g., $0.50/$1.50 for some, $3.00/$9.00 for premium)

### Cerebras
- **Free Tier**: Available for all models
- **Developer Tier**:
  - Llama 3.1 8B: $0.10/M input, $0.10/M output
  - Llama 3.1 70B: $0.60/M input, $0.60/M output
  - GPT-OSS-120B: $0.35/M input, $0.75/M output

### Groq
- **Free Tier**: 100K tokens/day, 30 RPM, 1000 RPD
- **Paid**:
  - Llama 3.1 8B Instant: $0.05/M input, $0.08/M output
  - Llama 3.3 70B Versatile: $0.59/M input, $0.79/M output
  - GPT-OSS-120B: $0.15/M input, $0.60/M output
  - Prompt caching available (50% discount on cached input tokens)

### Cloudflare Workers AI
- **Free Tier**: 10,000 Neurons/day ≈ 10K tokens/day
- **Paid**: $0.011 per 1,000 Neurons
- **Per-Model Pricing (approximate token equivalents)**:
  - Llama 3.1 8B: ~$0.045/M input, $0.384/M output
  - Llama 3.3 70B: ~$0.293/M input, $2.253/M output
  - Mistral 7B: ~$0.110/M input, $0.190/M output

### Google AI Studio (Gemini)
- **Free Tier**: Gemini 1.5 Flash (free), other models free for limited use
- **Paid**:
  - Gemini 1.5 Flash: $0.075/M input, $0.30/M output
  - Gemini 1.5 Pro: $1.25/M input, $10.00/M output (≤ 128K tokens)
  - Context caching: $0.15/M tokens/hour (storage)

### NVIDIA NIM
- **Free Tier**: Available for prototyping via Developer Program (rate-limited)
- **Production**: Requires NVIDIA AI Enterprise ($4,500/GPU/year or ~$1/GPU/hour)
- **Hosted API Per-Token Pricing**:
  - Nemotron Nano 9B V2: $0.04/M input, $0.16/M output
  - Nemotron 3 Nano 30B A3B: $0.05/M input, $0.20/M output
  - Nemotron 3 Super 120B A12B: $0.09-0.10/M input, $0.45-0.50/M output
  - Llama 3.1 Nemotron 70B: $0.90/M input, $0.90/M output

### Mistral La Plateforme
- **Free Tier**: Available for experimentation
- **Paid**:
  - Mistral Nemo: $0.15/M input, $0.15/M output
  - Mistral Small: $0.20/M input, $0.60/M output
  - Codestral: $0.20/M input, $0.60/M output
  - Mistral Large: $2.00/M input, $6.00/M output
  - Batch processing: 50% discount

### Cohere
- **Free Tier**: Trial keys (1000 calls/month, 20 RPM)
- **Paid**:
  - Command R7B: $0.0375/M input, $0.15/M output
  - Command R: $0.15/M input, $0.60/M output
  - Command R+: $2.50/M input, $10.00/M output
  - Command A: $2.50/M input, $10.00/M output

### GitHub Models
- **Free Tier**: Rate-limited access to all models
- **Paid**: $0.00001 per token unit (with model multipliers)
- **Example Models**:
  - Phi-4: $0.13/M input, $0.50/M output
  - Llama-3.3-70B-Instruct: $0.71/M input, $0.71/M output
  - GPT-4o: $2.50/M input, $10.00/M output

### OpenCode Zen
- **Free Models**:
  - Big Pickle: Free
  - DeepSeek V4 Flash Free: Free
  - Nemotron 3 Ultra Free: Free
  - North Mini Code Free: Free
- **Paid Models**:
  - MiniMax M2.7: $0.30/M input, $1.20/M output
  - Kimi K2.6: $0.95/M input, $4.00/M output
  - Qwen3.5 Plus: $0.20/M input, $1.20/M output
  - Claude Haiku 4.5: $1.00/M input, $5.00/M output
  - GPT 5.4 Mini: $0.75/M input, $4.50/M output

### LLM7.io
- **Free Tier**: 2 RPM (40 RPM with free token), 30+ models, no credit card
- **No paid tier mentioned**
- **API**: OpenAI-compatible at https://api.llm7.io/v1
- **Models**: deepseek-r1-0528, qwen3-235b, mistral-small-3.2, codestral-latest

### HuggingFace Inference API
- **Free Tier**: rate-limited, no credit card, 150K+ models available
- **No paid tier** (uses community inference)
- **API**: LiteLLM huggingface/ prefix routes to https://api-inference.huggingface.co/models/
- **Pricing**: Free for inference, rate-limited per model
- **Notable Models in this Proxy**:
  - gpt-oss-120b via HuggingFace
  - llama-3.3-70b-instruct via HuggingFace
  - gpt-oss-20b via HuggingFace
  - Various Llama, Gemma, Nemotron models

### OVHcloud AI Endpoints
- **Free Tier**: **Anonymous** — no API key required, 2 RPM per IP per model
- **API**: OpenAI-compatible at https://oai.endpoints.kepler.ai.cloud.ovh.net/v1
- **Pricing (hypothetical paid, falls Free-Tier wegfällt)**: GPT-OSS-120B: $0.08/$0.40 per 1M
- **Models** (Auswahl):
  - gpt-oss-120b
  - gpt-oss-20b
  - Meta-Llama-3_3-70B-Instruct
  - Llama-3.1-8B-Instruct
  - Mistral-Small-3.2-24B-Instruct-2506
  - Qwen3-32B, Qwen3.5-9B, Qwen3-Coder-30B-A3B-Instruct
  - Whisper, Stable Diffusion XL, Embedding-Modelle
- **Besonderheit**: `api_key: ""` in `config.yaml` — funktioniert ohne Auth-Header. IP-basiertes Rate-Limit, problematisch in Multi-Instance-Setups.

---

## 3. Cost Comparison for Common Models

| Model Name               | OpenRouter | Cerebras | Groq   | Cloudflare | Google AI | NVIDIA   | Mistral  | Cohere  | GitHub  | OpenCode Zen | LLM7.io | HuggingFace | OVHcloud |
|--------------------------|------------|----------|--------|------------|-----------|----------|----------|---------|---------|--------------|---------|-------------|----------|
| **Llama 3.1 8B**         | Free       | $0.10    | $0.05   | ~$0.045     | Free      | -        | -        | -       | -       | -            | -       | Free        | Free     |
| **Llama 3.3 70B**        | Varies     | $0.60    | $0.59   | ~$0.293     | -         | -        | -        | -       | $0.71    | -            | -       | Free        | Free     |
| **GPT-OSS-120B**         | Varies     | $0.35    | $0.15   | -          | -         | $0.90    | -        | -       | -       | -            | -       | Free        | $0.08/$0.40 |
| **Mistral Small**        | Varies     | -        | -      | ~$0.110     | -         | -        | $0.20    | -       | -       | -            | Free    | -           | Free     |
| **Command R**           | Varies     | -        | -      | -          | -         | -        | -        | $0.15   | -       | -            | -       | -           | -        |
| **DeepSeek V4 Flash**   | Varies     | -        | -      | -          | -         | -        | -        | -       | -       | Free         | -       | -           | -        |
| **Gemini 1.5 Flash**    | Varies     | -        | -      | -          | $0.075    | -        | -        | -       | -       | -            | -       | -           | -        |

---

## 4. Cost-Saving Tips

1. **Use Free Tiers**: All providers offer free tiers - use them for experimentation and prototyping
2. **Leverage Free Models**: OpenRouter, OpenCode Zen, Cerebras, LLM7.io, and HuggingFace offer free models with no token costs
3. **Batch Processing**: Groq and Mistral offer discounts for batch processing
4. **Prompt Caching**: Groq and OpenCode Zen offer caching to reduce costs for repeated prompts
5. **Model Selection**: Choose smaller models for simple tasks to save costs
6. **Rate Limits**: Monitor rate limits to avoid unexpected charges
7. **Context Window**: Use models with appropriate context windows to avoid tiered pricing

---

## 5. Important Notes

- Prices are subject to change - always check the provider's official website
- Some providers have tiered pricing based on prompt length
- Free tiers are typically rate-limited and not for production use
- Some providers charge differently for input vs. output tokens
- Always monitor your usage to avoid unexpected charges
- This document provides average costs - actual costs may vary based on specific models and usage patterns