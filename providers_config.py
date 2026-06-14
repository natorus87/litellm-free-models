#!/usr/bin/env python3
"""
Zentrale Provider-Definitionen fuer render-config.py und find-shared-models.py.

Statt 5 paralleler Datenstrukturen (PROVIDER_PARAMS, PREFIX_TO_KEY,
OPENAI_COMPAT_KEYS, STATIC_API_BASE, required_env) wird hier alles pro
Provider zusammengefasst.

Schema pro Provider:
  prefix:          litellm_params.model Praefix (z.B. 'openrouter', 'openai')
  env_var:         API-Key Env-Variable in .env (oder None fuer anonymen Tier)
  required:        True wenn Deployment ohne Key entfernt wird
  api_base_env:    Env-Variable fuer api_base (oder None, dann static)
  api_base_static: Statischer api_base (z.B. NVIDIA), None wenn via env
  rpm:             Default-Rate-Limit
  tpm:             Default-Token-Limit
  needs_api_base:  True wenn api_base gesetzt werden muss (OpenAI-kompatibel)
  litellm_key:     Key in der LiteLLM-Preisdatenbank (z.B. 'nvidia_nim')
  vendor_in_path:  True wenn 'openai/<vendor>/<model>' -- der zweite Pfadteil
                   identifiziert den Provider. False wenn 'openai/<model>'
                   und der Provider via api_base-Diskrimination erkannt wird.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    prefix: str
    env_var: Optional[str]
    required: bool
    api_base_env: Optional[str]
    api_base_static: Optional[str]
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
            name="github", prefix="openai", env_var="GITHUB_TOKEN",
            required=True, api_base_env=None,
            api_base_static="https://models.inference.ai.azure.com",
            rpm=15, tpm=100000, needs_api_base=True, litellm_key="github_models",
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
    """Lookup mit klarer Fehlermeldung."""
    if name not in PROVIDERS:
        raise KeyError(f"Unbekannter Provider: {name!r}")
    return PROVIDERS[name]


def find_by_litellm_prefix_and_vendor(prefix: str, vendor: Optional[str]) -> Optional[ProviderConfig]:
    """
    Mappt (prefix, vendor) -> ProviderConfig. None wenn nicht gefunden.
    Beispiel: ('openai', 'openai') -> nvidia (vendor_in_path)
              ('openai', None)    -> None (mehrdeutig -- Github vs OVHcloud)
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

