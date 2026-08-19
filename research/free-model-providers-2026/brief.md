# Research brief: Additional genuinely free AI model providers

## Refined question

Which additional API providers, not already integrated into this repository, offer a genuine ongoing or clearly disclosed promotional free tier for AI models as of 2026-08-18, across chat/reasoning/code, embeddings/reranking, image generation/understanding, speech-to-text, text-to-speech, music/audio generation, and related modalities?

## Scope and decision

The result is intended to decide which providers should be integrated into the LiteLLM Free-Models Proxy next. Prioritize primary documentation, usable APIs, transparent quotas, OpenAI compatibility or known LiteLLM support, and availability to individual developers in Germany/EU. Distinguish permanent free quotas, trial credits, limited-time previews, local/self-hosted offerings, and services that require a payment method. Exclude the 13 providers already integrated: OpenRouter, Cerebras, Groq, Cloudflare Workers AI, Google AI Studio, NVIDIA NIM, Mistral, Cohere, OpenCode Zen, LLM7.io, Hugging Face, OVHcloud, and Poolside. GitHub Models is retired and must not be proposed.

## Assumptions

- "Free" means usable without per-request payment after signup, not merely open-weight models whose inference is paid.
- Trial-only offers may be listed but must be clearly separated from renewable free tiers.
- Provider availability and quotas are time-sensitive; all findings are dated 2026-08-18.
- This is research and prioritization only; no provider will be added to code in this pass.
- Depth: standard; target at least 15 strong sources.

## Angles

1. General-purpose inference providers offering free chat, reasoning, coding, vision, embeddings, or reranking APIs.
2. Image and multimodal providers offering free API quotas for image generation, editing, vision, video, or document understanding.
3. Audio-specialist providers offering free API quotas for speech-to-text, text-to-speech, translation, music, or audio generation.
4. Integration and risk validation: LiteLLM/OpenAI compatibility, exact free-tier restrictions, regional/payment requirements, and misleading "free" claims for the strongest candidates.
