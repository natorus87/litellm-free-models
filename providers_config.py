#!/usr/bin/env python3
"""
Central provider definitions for render-config.py and find-shared-models.py.

Instead of 5 parallel data structures (PROVIDER_PARAMS, PREFIX_TO_KEY,
OPENAI_COMPAT_KEYS, STATIC_API_BASE, required_env), everything is grouped
here per provider.

Schema per provider:
  prefix:          litellm_params.model prefix (e.g. 'openrouter', 'openai')
  env_var:         API key env variable in .env (or None for an anonymous tier)
  required:        True if the deployment is removed without a key
  api_base_env:    Env variable for api_base (or None, then static)
  api_base_static: Static api_base (e.g. NVIDIA), None if set via env
  rpm:             Default rate limit
  tpm:             Default token limit
  needs_api_base:  True if api_base must be set (OpenAI-compatible)
  litellm_key:     Key in the LiteLLM pricing database (e.g. 'nvidia_nim')
  vendor_in_path:  True if 'openai/<vendor>/<model>' -- the second path
                   segment identifies the provider. False if
                   'openai/<model>' and the provider is discriminated via
                   api_base.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    prefix: str
    env_var: str | None
    required: bool
    api_base_env: str | None
    api_base_static: str | None
    rpm: int
    tpm: int
    needs_api_base: bool
    litellm_key: str
    vendor_in_path: bool = False


PROVIDERS: dict[str, ProviderConfig] = {
    p.name: p for p in [
        ProviderConfig(
            name="openrouter", prefix="openrouter", env_var="OPENROUTER_API_KEY",
            required=True, api_base_env=None, api_base_static=None,
            rpm=1, tpm=200000, needs_api_base=False, litellm_key="openrouter",
        ),
        ProviderConfig(
            name="cerebras", prefix="cerebras", env_var="CEREBRAS_API_KEY",
            required=True, api_base_env=None, api_base_static=None,
            rpm=30, tpm=1000000, needs_api_base=False, litellm_key="cerebras",
        ),
        ProviderConfig(
            name="groq", prefix="groq", env_var="GROQ_API_KEY",
            required=True, api_base_env=None, api_base_static=None,
            rpm=2, tpm=8000, needs_api_base=False, litellm_key="groq",
        ),
        ProviderConfig(
            name="cloudflare", prefix="cloudflare", env_var="CLOUDFLARE_API_KEY",
            required=True, api_base_env="CLOUDFLARE_API_BASE", api_base_static=None,
            rpm=10, tpm=500000, needs_api_base=True, litellm_key="cloudflare",
        ),
        ProviderConfig(
            name="google-ai", prefix="gemini", env_var="GEMINI_API_KEY",
            required=True, api_base_env=None, api_base_static=None,
            rpm=2, tpm=200000, needs_api_base=False, litellm_key="gemini",
        ),
        ProviderConfig(
            name="nvidia", prefix="openai", env_var="NVIDIA_API_KEY",
            required=True, api_base_env=None,
            api_base_static="https://integrate.api.nvidia.com/v1",
            rpm=40, tpm=500000, needs_api_base=True, litellm_key="nvidia_nim",
            vendor_in_path=True,
        ),
        ProviderConfig(
            name="mistral", prefix="mistral", env_var="MISTRAL_API_KEY",
            required=True, api_base_env=None, api_base_static=None,
            rpm=2, tpm=200000, needs_api_base=False, litellm_key="mistral",
        ),
        ProviderConfig(
            name="cohere", prefix="cohere", env_var="COHERE_API_KEY",
            required=True, api_base_env=None, api_base_static=None,
            rpm=20, tpm=200000, needs_api_base=False, litellm_key="cohere",
        ),
        ProviderConfig(
            name="poolside", prefix="openai", env_var="POOLSIDE_API_KEY",
            required=True, api_base_env=None,
            api_base_static="https://inference.poolside.ai/v1",
            # Poolside does not publish preview rate limits; keep conservative
            # local router budgets until response headers document otherwise.
            rpm=10, tpm=200000, needs_api_base=True, litellm_key="poolside",
            vendor_in_path=True,
        ),
        ProviderConfig(
            name="hetzner", prefix="openai", env_var="HETZNER_VLLM_API_KEY",
            required=True, api_base_env=None,
            api_base_static="https://inference.hetzner.com/api/v1",
            # Experiments is free/best-effort and has no published fixed RPM.
            # Start conservatively until live response headers show otherwise.
            rpm=5, tpm=200000, needs_api_base=True, litellm_key="hetzner",
        ),
        ProviderConfig(
            name="zai", prefix="zai", env_var="ZAI_API_KEY",
            required=True, api_base_env=None, api_base_static=None,
            # Z.AI does not publish fixed free-model limits. Live testing
            # showed intermittent provider-side 429s, so keep the initial
            # routing budget deliberately conservative.
            rpm=1, tpm=100000, needs_api_base=False, litellm_key="zai",
        ),
        ProviderConfig(
            name="elevenlabs", prefix="elevenlabs", env_var="ELEVENLABS_API_KEY",
            required=True, api_base_env=None, api_base_static=None,
            # The free plan is quota-based and exposes no stable public RPM.
            # This provider is currently used only for Scribe STT.
            rpm=2, tpm=8000, needs_api_base=False, litellm_key="elevenlabs",
        ),
        ProviderConfig(
            name="opencode-zen", prefix="openai", env_var="OPENCODE_ZEN_API_KEY",
            required=True, api_base_env=None,
            api_base_static="https://opencode.ai/zen/v1",
            rpm=10, tpm=200000, needs_api_base=True, litellm_key="opencode_zen",
        ),
        ProviderConfig(
            name="llm7io", prefix="openai", env_var="LLM7IO_API_KEY",
            required=True, api_base_env=None,
            api_base_static="https://api.llm7.io/v1",
            rpm=40, tpm=200000, needs_api_base=True, litellm_key="llm7io",
        ),
        ProviderConfig(
            name="huggingface", prefix="huggingface", env_var="HF_TOKEN",
            required=True, api_base_env=None, api_base_static=None,
            rpm=30, tpm=200000, needs_api_base=False, litellm_key="huggingface",
        ),
        ProviderConfig(
            name="ovhcloud", prefix="openai", env_var="OVHCLOUD_API_KEY",
            required=False, api_base_env=None,
            api_base_static="https://oai.endpoints.kepler.ai.cloud.ovh.net/v1",
            rpm=2, tpm=200000, needs_api_base=True, litellm_key="ovhcloud",
        ),
    ]
}


def get(name: str) -> ProviderConfig:
    """Lookup with a clear error message."""
    if name not in PROVIDERS:
        raise KeyError(f"Unknown provider: {name!r}")
    return PROVIDERS[name]


def find_by_litellm_prefix_and_vendor(prefix: str, vendor: str | None) -> ProviderConfig | None:
    """
    Maps (prefix, vendor) -> ProviderConfig. None if not found.
    Example: ('openai', 'openai') -> nvidia (vendor_in_path)
             ('openai', None)    -> None (ambiguous -- several API bases)
    """
    for p in PROVIDERS.values():
        if p.prefix != prefix:
            continue
        if p.vendor_in_path:
            if vendor and p.name == vendor:
                return p
        else:
            if vendor is None and not p.vendor_in_path:
                return p
    return None
