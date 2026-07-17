#!/usr/bin/env python3
"""
Finds models shared across providers and shows what they would cost on
the respective paid tier (savings-potential report).

Reads API keys from .env, queries the available models per provider,
groups them by normalized name, and writes provider combinations with
at least 2 shared models to providers-overlap.txt.

Zen models (deepseek-v4-flash, nemotron-3-ultra, big-pickle, north-mini-code)
are always included as soon as they show up at any provider at all.

Pricing data comes from the LiteLLM reference database
(https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json,
 identical to https://models.litellm.ai/) and is cached locally for 24h
(.cache/litellm-prices.json). For each shared model, the report shows the
hypothetical paid price per 1M tokens for input and output -- making it
visible how much the free-tier usage saves.

Usage:
    python3 find-shared-models.py
    python3 find-shared-models.py --env /path/to/.env
    python3 find-shared-models.py --output report.txt
    python3 find-shared-models.py --refresh-pricing
    python3 find-shared-models.py --no-pricing
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from providers_config import PROVIDERS as PROVIDER_CONFIGS

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_ENV = REPO_ROOT / ".env"
DEFAULT_OUTPUT = REPO_ROOT / "providers-overlap.txt"

# LiteLLM model_prices_and_context_window.json (1.5MB, ~2800 models).
# Also used by https://models.litellm.ai/ as its data source.
PRICING_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
PRICING_CACHE = REPO_ROOT / ".cache" / "litellm-prices.json"
PRICING_TTL_SECONDS = 24 * 3600

# How we map our provider names to LiteLLM providers.
# Derived from providers_config.py so there is a single source of truth.
PROVIDER_TO_LITELLM = {name: p.litellm_key for name, p in PROVIDER_CONFIGS.items()}

ZEN_MODEL_NAMES = {
    "deepseek-v4-flash",
    "nemotron-3-ultra",
    "big-pickle",
    "north-mini-code",
}

STOPWORDS = {
    "meta", "llama", "google", "mistral", "alibaba", "qwen", "nvidia",
    "cohere", "openai", "deepseek", "microsoft", "ibm", "anthropic",
    "moonshotai", "moonshot", "kimi", "ai", "the", "a", "an", "of",
    "instruct", "chat", "base", "preview", "experimental", "free",
}

# ---------------------------------------------------------------------------
# Paid-vendor denylist
# ---------------------------------------------------------------------------
# Aggregators like OpenCode Zen and LLM7.io mix genuine open-weight models
# with (presumably proxied/resold) access to paid flagship APIs of major
# vendors under their brand names (e.g. "claude-opus-4-8", "gpt-5.4",
# "gemini-3.5-flash", "grok-4.5", "glm-5.x", "minimax-m..."). These vendors
# (Anthropic, OpenAI's GPT line, Google Gemini, xAI, Zhipu/GLM-5, MiniMax)
# do NOT publish their flagship models openly -- a "free-tier" proxy must
# never automatically adopt such entries as free (misleading + ToS risk),
# regardless of which provider lists them. Observed in practice in exactly
# this form at OpenCode Zen + LLM7.io on 2026-07-16.
#
# EXPLICITLY EXEMPTED because these are genuine open-weight lines:
#   gpt-oss   (OpenAI's open models, not the "gpt-5"/"gpt-4" flagships)
#   gemma     (Google's open models, not "gemini")
#   kimi/moonshotai (Moonshot AI open-sourced the entire K2 family;
#                    kimi-k2.6 is already an established deployment)
#   deepseek, qwen, llama, mistral, nemotron, command-r, codestral (established)
#
# Anthropic, OpenAI's GPT line, Google's Gemini, and xAI NEVER publish
# these flagship models as open weights -- so the deny applies everywhere,
# regardless of provider.
PAID_VENDOR_PATTERNS = [
    re.compile(r"(?:^|/)claude(?:-|$)", re.IGNORECASE),
    re.compile(r"(?:^|/)gpt-5(?:\.\d+)?(?:-|$)", re.IGNORECASE),
    re.compile(r"(?:^|/)gpt-4", re.IGNORECASE),
    re.compile(r"(?:^|/)gemini(?:-|$)", re.IGNORECASE),
    re.compile(r"(?:^|/)grok(?:-|$)", re.IGNORECASE),
]

# GLM (Zhipu/Z.ai) and MiniMax publish SOME open weights (e.g. on
# HuggingFace, where structurally only genuine checkpoints can live -- you
# can't upload an API-only model there). At the API aggregators OpenCode
# Zen/LLM7.io it's unclear, though, whether "glm-5"/"minimax-m2.7" is the
# open checkpoint or the paid flagship API -- so they get filtered out
# there as a precaution.
AMBIGUOUS_VENDOR_PATTERNS = [
    re.compile(r"(?:^|/)glm-5", re.IGNORECASE),
    re.compile(r"(?:^|/)minimax", re.IGNORECASE),
]
AGGREGATOR_PROVIDERS = {"opencode-zen", "llm7io"}


def is_paid_vendor_model(model_id: str, provider: str = "") -> bool:
    """True if model_id matches a known paid flagship model of a major
    vendor (see the PAID_VENDOR_PATTERNS comment for the rationale +
    exemptions). `provider` controls the additional ambiguous denylist
    (GLM-5/MiniMax), which only applies at the API aggregators, not at
    open-weight hosts like HuggingFace."""
    if any(p.search(model_id) for p in PAID_VENDOR_PATTERNS):
        return True
    if provider in AGGREGATOR_PROVIDERS:
        return any(p.search(model_id) for p in AMBIGUOUS_VENDOR_PATTERNS)
    return False


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


# Retry behavior for catalog queries: transient errors (network, 429, 5xx)
# shouldn't disqualify a provider for the whole run right away.
HTTP_RETRIES = 3
HTTP_BACKOFF_SECONDS = (1, 3)  # wait time before retry 2 and 3 respectively

# Several providers (Cerebras, Groq, OpenCode Zen) sit behind Cloudflare's
# bot protection, which blocks urllib's default User-Agent
# ("Python-urllib/3.x") (403, "error code: 1010" -- a WAF block, NOT an
# auth error despite the 403). A browser-like User-Agent reliably avoids it.
DEFAULT_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) litellm-free-models/find-shared-models.py"


def http_get_json(url: str, headers: dict[str, str], timeout: int = 30) -> any:
    headers = {"User-Agent": DEFAULT_USER_AGENT, **headers}
    last_exc: Exception | None = None
    for attempt in range(HTTP_RETRIES):
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            # Only retry transient HTTP errors; 4xx (except 429) are
            # deterministic (wrong key, wrong URL) -> bail out immediately.
            if exc.code != 429 and exc.code < 500:
                raise
            last_exc = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
        if attempt < HTTP_RETRIES - 1:
            time.sleep(HTTP_BACKOFF_SECONDS[min(attempt, len(HTTP_BACKOFF_SECONDS) - 1)])
    raise last_exc


def normalize(name: str) -> str:
    s = name.lower()
    s = re.sub(r":[a-z\-]+$", "", s)
    s = re.sub(r"\.(fast|lite|mini|max|pro|ultra)$", "", s)
    s = re.sub(r"-(fast|lite|mini|max|pro|ultra)$", "", s)
    s = re.sub(r"-(preview|experimental|free|chat|instruct|base|it|fp8|fp4|q4|k|m)$", "", s)
    s = re.sub(r"\b(latest|preview|free|chat|instruct|base|it|fp8|fp4|q4)\b", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    parts = [p for p in s.split("-") if p and p not in STOPWORDS]
    return "-".join(parts) if parts else s


def short_key(name: str) -> str:
    return name.split("/")[-1]


def pretty_model_name(model_id: str) -> str:
    """
    Derives a readable model_name from a raw provider model ID -- WITHOUT
    normalize()'s aggressive STOPWORDS cleanup.

    normalize() is meant for GROUPING the same model across providers and
    deliberately strips vendor words (including "deepseek", "kimi",
    "moonshotai") because many provider IDs duplicate the vendor (e.g.
    "deepseek/deepseek-v4-pro" -- without the stopword filter that
    wouldn't group with "DeepSeek-V4-Pro" from another provider). For the
    actual model_name, the same cleanup is too aggressive though: it turned
    "deepseek-v4-pro" into the unusable name "v4" (just because "deepseek"
    is a stopword), and "moonshotai/Kimi-K2.5" became "k2-5" instead of
    "kimi-k2.5".

    So this only takes the last path segment (the vendor prefix like "org/"
    is dropped, the actual model name is kept), lowercased, without a
    ':tag' suffix (e.g. ':free'). Dots are preserved (repo convention:
    "kimi-k2.6", "mistral-small-3.2").
    """
    tail = model_id.rsplit("/", 1)[-1]
    tail = re.sub(r":[a-z\-]+$", "", tail, flags=re.IGNORECASE)
    tail = tail.lower()
    tail = re.sub(r"[^a-z0-9.\-]+", "-", tail)
    tail = re.sub(r"-+", "-", tail).strip("-.")
    return tail or normalize(model_id)


# ---------------------------------------------------------------------------
# Provider definitions
# ---------------------------------------------------------------------------

def _filter_free_openrouter(data: dict) -> list[str]:
    """
    OpenRouter lists its ENTIRE catalog (400+ models, mostly paid). For a
    free-tier proxy only the actually-free models matter: `:free` variants
    or entries with both prompt AND completion price at 0. Without this
    filter, --apply could write a PAID model into the config.
    """
    out: list[str] = []
    for m in data.get("data", []):
        mid = m.get("id") or ""
        if not mid:
            continue
        if mid.endswith(":free"):
            out.append(mid)
            continue
        pricing = m.get("pricing") or {}
        try:
            prompt = float(pricing.get("prompt") or 0)
            completion = float(pricing.get("completion") or 0)
        except (TypeError, ValueError):
            continue
        if prompt == 0 and completion == 0:
            out.append(mid)
    return out


def fetch_openrouter(key: str) -> list[str]:
    data = http_get_json(
        "https://openrouter.ai/api/v1/models",
        {"Authorization": f"Bearer {key}"},
    )
    return _filter_free_openrouter(data)


def fetch_cerebras(key: str) -> list[str]:
    data = http_get_json(
        "https://api.cerebras.ai/v1/models",
        {"Authorization": f"Bearer {key}"},
    )
    return [m.get("id") or m.get("name") for m in data.get("data", []) if m.get("id") or m.get("name")]


def fetch_groq(key: str) -> list[str]:
    data = http_get_json(
        "https://api.groq.com/openai/v1/models",
        {"Authorization": f"Bearer {key}"},
    )
    return [m["id"] for m in data.get("data", [])]


def fetch_cloudflare(api_key: str, api_base: str) -> list[str]:
    """
    Cloudflare Workers AI has NO OpenAI-compatible GET /v1/models (405
    Method Not Allowed). The catalog lives at
    /accounts/{id}/ai/models/search (paginated). api_base is
    .../accounts/<id>/ai/v1 -> strip /v1, append /models/search.
    """
    account_base = re.sub(r"/v1/?$", "", api_base.rstrip("/"))
    headers = {"Authorization": f"Bearer {api_key}"}
    names: list[str] = []
    page = 1
    while True:
        url = f"{account_base}/models/search?per_page=100&page={page}"
        data = http_get_json(url, headers)
        result = data.get("result") or []
        for m in result:
            if isinstance(m, str):
                names.append(m)
            elif isinstance(m, dict):
                name = m.get("name") or m.get("id") or m.get("model") or ""
                if name:
                    names.append(name)
        if len(result) < 100 or page >= 10:
            break
        page += 1
    return names


def _parse_google_models(data: dict) -> list[str]:
    """Chat-capable models only (generateContent); embedding/AQA models
    like `embedding-001` are irrelevant for the proxy and would otherwise
    pollute the overlap groups."""
    out: list[str] = []
    for m in data.get("models", []):
        name = m.get("name", "")
        if not name:
            continue
        methods = m.get("supportedGenerationMethods") or []
        if methods and "generateContent" not in methods:
            continue
        out.append(name.split("/")[-1])
    return out


def fetch_google_ai(key: str) -> list[str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={urllib.parse.quote(key)}"
    data = http_get_json(url, {})
    return _parse_google_models(data)


def fetch_nvidia(key: str) -> list[str]:
    data = http_get_json(
        "https://integrate.api.nvidia.com/v1/models",
        {"Authorization": f"Bearer {key}"},
    )
    return [m["id"] for m in data.get("data", [])]


def fetch_mistral(key: str) -> list[str]:
    data = http_get_json(
        "https://api.mistral.ai/v1/models",
        {"Authorization": f"Bearer {key}"},
    )
    return [m["id"] for m in data.get("data", [])]


def _parse_cohere_models(data: dict) -> list[str]:
    """
    Cohere returns {"models": [{"name": "command-r-plus", "endpoints":
    ["chat", ...]}, ...]}. What matters are the MODEL names of the
    chat-capable entries. (An earlier version mistakenly collected the
    endpoint names "chat"/"generate"/"embed" instead -- the Cohere catalog
    in the report was useless as a result.)
    """
    names: list[str] = []
    for m in data.get("models", []):
        name = m.get("name", "")
        if not name:
            continue
        endpoints = m.get("endpoints") or []
        if endpoints and "chat" not in endpoints:
            continue
        names.append(name)
    return names


def fetch_cohere(key: str) -> list[str]:
    try:
        data = http_get_json(
            "https://api.cohere.ai/v1/models",
            {"Authorization": f"Bearer {key}"},
        )
    except urllib.error.HTTPError:
        data = http_get_json(
            "https://api.cohere.com/v1/models",
            {"Authorization": f"Bearer {key}"},
        )
    return _parse_cohere_models(data)


def _parse_github_models(data) -> list[str]:
    """GitHub Models returns either a bare LIST of model objects or a dict
    with a models/data key, depending on the endpoint."""
    if isinstance(data, dict):
        items = data.get("models", data.get("data", []))
    else:
        items = data or []
    out: list[str] = []
    for m in items:
        if isinstance(m, str):
            out.append(m)
        elif isinstance(m, dict):
            name = m.get("name") or m.get("id") or ""
            if name:
                out.append(name)
    return out


def fetch_github_models(token: str) -> list[str]:
    data = http_get_json(
        "https://models.inference.ai.azure.com/models",
        {"Authorization": f"Bearer {token}"},
    )
    return _parse_github_models(data)


def fetch_opencode_zen(key: str) -> list[str]:
    # Deliberately do NOT swallow HTTP errors: a 401 (wrong key) should
    # show up as [FAIL] instead of silently slipping through as
    # "[OK] 0 models".
    data = http_get_json(
        "https://opencode.ai/zen/v1/models",
        {"Authorization": f"Bearer {key}"},
    )
    return [m.get("id") or m.get("name") for m in data.get("data", []) if m.get("id") or m.get("name")]


def fetch_llm7io(key: str) -> list[str]:
    headers: dict[str, str] = {}
    if key and key != "unused":
        headers["Authorization"] = f"Bearer {key}"
    data = http_get_json("https://api.llm7.io/v1/models", headers)
    return [m["id"] for m in data.get("data", [])]


def fetch_ovhcloud(*_args) -> list[str]:
    """
    OVHcloud AI Endpoints - OpenAI-compatible, **no API key required**
    (anonymous free tier, 2 RPM/IP/model).

    Deliberately sends NO Authorization header, because:
      - `Authorization: Bearer` (empty)     -> 200 OK
      - `Authorization: Bearer undefined`   -> 403
      - `Authorization: Bearer none`        -> 403
    """
    data = http_get_json(
        "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/models",
        {},
    )
    return [m["id"] for m in data.get("data", []) if m.get("id")]


# Curated fallback list in case the HF router's live catalog isn't
# reachable. Deliberately small; the live path is the normal case.
HF_FALLBACK_MODELS = [
    "meta-llama/Llama-3.3-70B-Instruct",
    "meta-llama/Meta-Llama-3.1-8B-Instruct",
    "mistralai/Mistral-Small-3.2-24B-Instruct-2506",
    "Qwen/Qwen2.5-Coder-32B-Instruct",
    "deepseek-ai/DeepSeek-V3",
    "deepseek-ai/DeepSeek-R1",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]

# Providers whose catalog is NOT complete in the current run (e.g. the HF
# fallback list). Such catalogs must not be used for stale-deployment
# detection (false positives).
PARTIAL_CATALOGS: set[str] = set()

# { provider: [model_id, ...] } -- models filtered out by the paid-vendor
# filter in the current run (for transparency in the report).
PAID_FILTERED: dict[str, list[str]] = {}


def fetch_huggingface(token: str) -> list[str]:
    """
    Queries the HF Inference Router live (OpenAI-compatible /v1/models,
    lists the models actually servable via inference providers). Only
    falls back to the curated list on errors -- the old, hardcoded 2024
    list (gemma-2, Phi-3.5, ...) was permanently stale.
    """
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        data = http_get_json("https://router.huggingface.co/v1/models", headers)
        models = [m.get("id") for m in data.get("data", []) if m.get("id")]
        if models:
            PARTIAL_CATALOGS.discard("huggingface")
            return models
    except Exception:
        pass
    PARTIAL_CATALOGS.add("huggingface")
    return list(HF_FALLBACK_MODELS)


PROVIDERS: dict[str, Callable[..., list[str]]] = {
    "openrouter": lambda env: fetch_openrouter(env["OPENROUTER_API_KEY"]),
    "cerebras":   lambda env: fetch_cerebras(env["CEREBRAS_API_KEY"]),
    "groq":       lambda env: fetch_groq(env["GROQ_API_KEY"]),
    "cloudflare": lambda env: fetch_cloudflare(env["CLOUDFLARE_API_KEY"], env["CLOUDFLARE_API_BASE"]),
    "google-ai":  lambda env: fetch_google_ai(env["GEMINI_API_KEY"]),
    "nvidia":     lambda env: fetch_nvidia(env["NVIDIA_API_KEY"]),
    "mistral":    lambda env: fetch_mistral(env["MISTRAL_API_KEY"]),
    "cohere":     lambda env: fetch_cohere(env["COHERE_API_KEY"]),
    "github":     lambda env: fetch_github_models(env["GITHUB_TOKEN"]),
    "opencode-zen": lambda env: fetch_opencode_zen(env["OPENCODE_ZEN_API_KEY"]),
    "llm7io":     lambda env: fetch_llm7io(env.get("LLM7IO_API_KEY", "unused")),
    "huggingface": lambda env: fetch_huggingface(env.get("HF_TOKEN", "")),
    "ovhcloud":   lambda env: fetch_ovhcloud(),
}


_REQUIRED_ENV = {
    "openrouter": ["OPENROUTER_API_KEY"],
    "cerebras": ["CEREBRAS_API_KEY"],
    "groq": ["GROQ_API_KEY"],
    "cloudflare": ["CLOUDFLARE_API_KEY", "CLOUDFLARE_API_BASE"],
    "google-ai": ["GEMINI_API_KEY"],
    "nvidia": ["NVIDIA_API_KEY"],
    "mistral": ["MISTRAL_API_KEY"],
    "cohere": ["COHERE_API_KEY"],
    "github": ["GITHUB_TOKEN"],
    "opencode-zen": ["OPENCODE_ZEN_API_KEY"],
    # llm7io/huggingface/ovhcloud: free tier without a required key
    "llm7io": [],
    "huggingface": [],
    "ovhcloud": [],
}


def required_env(name: str) -> list[str]:
    return _REQUIRED_ENV.get(name, [])


# ---------------------------------------------------------------------------
# Pricing data (LiteLLM reference database)
# ---------------------------------------------------------------------------

def load_pricing(force_refresh: bool = False) -> dict[str, dict]:
    """
    Loads model_prices_and_context_window.json with a 24h cache.

    Returns a dict: { "openrouter/openai/gpt-oss-120b": {...}, ... }.
    On a network error with an existing cache, the cache is used.
    """
    PRICING_CACHE.parent.mkdir(parents=True, exist_ok=True)

    if not force_refresh and PRICING_CACHE.exists():
        age = time.time() - PRICING_CACHE.stat().st_mtime
        if age < PRICING_TTL_SECONDS:
            try:
                return json.loads(PRICING_CACHE.read_text(encoding="utf-8"))
            except Exception:
                pass

    try:
        data = http_get_json(PRICING_URL, {}, timeout=60)
    except Exception as exc:
        if PRICING_CACHE.exists():
            print(f"  [WARN] Pricing download failed ({exc}), using cache.", file=sys.stderr)
            return json.loads(PRICING_CACHE.read_text(encoding="utf-8"))
        raise

    PRICING_CACHE.write_text(json.dumps(data), encoding="utf-8")
    return data


def _strip_vendor(model_id: str) -> str:
    """Removes leading vendor prefixes (openai/, meta-llama/, ...)."""
    parts = model_id.split("/", 1)
    if len(parts) == 2 and parts[0] in {
        "openai", "meta-llama", "mistralai", "google", "nvidia", "deepseek-ai",
        "deepseek", "anthropic", "microsoft", "qwen", "alibaba", "ibm",
        "cohere", "moonshotai", "nousresearch",
    }:
        return parts[1]
    return model_id


def _strip_free_suffix(model_id: str) -> str:
    """Removes ':free' and '-free', but not doubled as '-free-free'."""
    s = re.sub(r":free$", "", model_id)
    s = re.sub(r"-free$", "", s)
    return s


class _PricingIndex:
    """
    Inverted index over the LiteLLM pricing database:
        model_norm_lower -> [(entry, db_key, cost_mix), ...]
    where 'cost_mix' = 0.5M * ic + 0.5M * oc (for a 50/50 mix over 1M tokens).
    Built once per pricing load, then O(1) lookups in lookup_price().
    """

    __slots__ = ("by_name",)

    def __init__(self, pricing: dict[str, dict]) -> None:
        self.by_name: dict[str, list[tuple[dict, str, float]]] = {}
        for db_key, entry in pricing.items():
            if db_key == "sample_spec" or not isinstance(entry, dict):
                continue
            if "/" not in db_key:
                continue
            ic = entry.get("input_cost_per_token")
            oc = entry.get("output_cost_per_token")
            if not (isinstance(ic, (int, float)) and isinstance(oc, (int, float))):
                continue
            db_model = db_key.split("/", 1)[1]
            db_norm = _strip_free_suffix(db_model).lower()
            cost = float(ic) * 0.5e6 + float(oc) * 0.5e6
            self.by_name.setdefault(db_norm, []).append((entry, db_key, cost))

    def best_for(self, candidates: set[str]) -> tuple[dict, str, float] | None:
        best: tuple[float, dict, str] | None = None
        cand_lower = {c.lower() for c in candidates}
        for norm, items in self.by_name.items():
            if norm not in cand_lower:
                continue
            for entry, db_key, cost in items:
                if best is None or cost < best[0]:
                    best = (cost, entry, db_key)
        return best


_PRICING_INDEX: _PricingIndex | None = None


def _get_pricing_index(pricing: dict[str, dict]) -> _PricingIndex:
    global _PRICING_INDEX
    if _PRICING_INDEX is None:
        _PRICING_INDEX = _PricingIndex(pricing)
    return _PRICING_INDEX


def _reset_pricing_index() -> None:
    """For tests: invalidate the index."""
    global _PRICING_INDEX
    _PRICING_INDEX = None


def lookup_price(
    pricing: dict[str, dict],
    provider: str,
    model_id: str,
    with_fallback: bool = False,
) -> tuple[dict | None, str | None]:
    """
    Maps (provider, model_id) -> (DB entry, DB key) or (None, None).

    Examples:
      ('openrouter', 'openai/gpt-oss-120b:free')  -> openrouter/openai/gpt-oss-120b
      ('cerebras',   'gpt-oss-120b')               -> cerebras/gpt-oss-120b
      ('nvidia',     'openai/gpt-oss-120b')        -> nvidia_nim/openai/gpt-oss-120b

    With with_fallback=True, if no direct match is found, all LiteLLM
    providers are searched for the same model name and the entry with the
    lowest "mix price" (input+output) is returned.

    Uses an inverted index (_PricingIndex) over the pricing DB, so fallback
    lookups are O(1) instead of O(n) per call.
    """
    litellm_prov = PROVIDER_TO_LITELLM.get(provider)
    if not litellm_prov:
        if not with_fallback:
            return None, None
        litellm_prov = ""

    raw = model_id
    direct_candidates = [
        f"{litellm_prov}/{raw}",
        f"{litellm_prov}/{_strip_vendor(raw)}",
        f"{litellm_prov}/{_strip_free_suffix(raw)}",
        f"{litellm_prov}/{_strip_free_suffix(_strip_vendor(raw))}",
    ]
    for cand in direct_candidates:
        if cand in pricing:
            return pricing[cand], cand

    if not with_fallback:
        return None, None

    # Fallback: same model name across all LiteLLM providers (O(1) via index)
    idx = _get_pricing_index(pricing)
    suffixes = {_strip_vendor(raw), _strip_free_suffix(raw),
                _strip_free_suffix(_strip_vendor(raw)), raw}
    best = idx.best_for(suffixes)
    if best:
        return best[1], best[2]
    return None, None


def fmt_cost(per_token: float | None) -> str:
    if per_token is None or per_token == 0:
        return "$0.000"
    return f"${per_token * 1e6:.3f}/M"


# ---------------------------------------------------------------------------
# Apply engine: update config.yaml structurally
# ---------------------------------------------------------------------------

# Provider -> (litellm_params prefix, env_var, api_base env var or None,
#              rpm default, tpm default, requires api_base) is derived
# centrally from providers_config.PROVIDERS -- no more double maintenance.


def build_deployment(
    model_name: str,
    provider: str,
    model_id: str,
    ic: float = 0.0,
    oc: float = 0.0,
) -> list[str]:
    """
    Creates a deployment block (list of YAML lines, 2-space indent) for
    the model_list. Example:

      - model_name: gpt-oss-120b
        litellm_params:
          model: openrouter/openai/gpt-oss-120b
          api_key: os.environ/OPENROUTER_API_KEY
          tpm: 200000
          rpm: 1
        model_info:
          input_cost_per_token: 0
          output_cost_per_token: 0
          mode: chat

    tpm/rpm live in litellm_params (not at the deployment top level), so
    usage-based-routing-v2 evaluates them for budget routing.
    """
    prov = PROVIDER_CONFIGS[provider]

    # model_id is appended verbatim after the provider prefix. For NVIDIA
    # that's e.g. "openai/openai/gpt-oss-120b" (intentional, see AGENTS.md
    # §2). If model_id already carries a vendor prefix (e.g. "openai/..."),
    # you get "openai/openai/..." -- that's the documented convention and
    # LiteLLM routes it correctly.
    model_str = f"{prov.prefix}/{model_id}"

    lines: list[str] = []
    lines.append(f"  - model_name: {model_name}\n")
    lines.append("    litellm_params:\n")
    lines.append(f"      model: {model_str}\n")
    if prov.env_var:
        lines.append(f"      api_key: os.environ/{prov.env_var}\n")
    else:
        lines.append("      api_key: \"\"\n")
    if prov.needs_api_base:
        if prov.api_base_env:
            lines.append(f"      api_base: os.environ/{prov.api_base_env}\n")
        elif prov.api_base_static:
            lines.append(f"      api_base: {prov.api_base_static}\n")
    lines.append(f"      tpm: {prov.tpm}\n")
    lines.append(f"      rpm: {prov.rpm}\n")
    lines.append("    model_info:\n")
    lines.append(f"      input_cost_per_token: {_fmt_cost_yaml(ic)}\n")
    lines.append(f"      output_cost_per_token: {_fmt_cost_yaml(oc)}\n")
    lines.append("      mode: chat\n")
    lines.append("\n")  # blank line after the block
    return lines


def _fmt_cost_yaml(value: float) -> str:
    """Values < 1e-3 as scientific notation (1e-07), 0 as 0."""
    if value == 0:
        return "0"
    if value < 1e-3:
        # e.g. 1e-07
        return f"{value:g}"
    return f"{value}"


def parse_config(path: Path) -> tuple[list[str], int, int, dict[str, list[dict]]]:
    """
    Reads config.yaml line by line. Returns:
      - all lines
      - the index where 'model_list:' is (or -1)
      - the index where 'router_settings:' (or the next top-level key) is
      - parsed existing models: { model_name: [ {provider, model_id, ic, oc, line_start, line_end} ] }
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    model_list_start, model_list_end = _find_model_list_bounds(lines)
    existing = _scan_existing_blocks(lines, model_list_start, model_list_end)
    return lines, model_list_start, model_list_end, existing


def _find_model_list_bounds(lines: list[str]) -> tuple[int, int]:
    """Returns (model_list_start, model_list_end) for a given list of
    lines. Reused for both the initial file and for new_lines that have
    already been structurally modified (see apply_to_config: indices shift
    after every insertion, so bounds must be RE-scanned after structural
    mutations instead of reusing stale indices)."""
    model_list_start = -1
    model_list_end = len(lines)
    for i, line in enumerate(lines):
        if line.rstrip() == "model_list:" and not line.startswith(" "):
            model_list_start = i
            break
    if model_list_start >= 0:
        for i in range(model_list_start + 1, len(lines)):
            stripped = lines[i].strip()
            if stripped and not lines[i].startswith(" "):
                model_list_end = i
                break
    return model_list_start, model_list_end


def _scan_existing_blocks(
    lines: list[str], model_list_start: int, model_list_end: int
) -> dict[str, list[dict]]:
    """Scans the deployment blocks between model_list_start/-end and
    returns { model_name: [ {provider, model_id, ic, oc, line_start,
    line_end}, ... ] }. Factored out of parse_config() so apply_to_config()
    can get fresh line_start/line_end for the cost-patch step after
    structural mutations (new blocks, insertions) -- old indices computed
    before the mutation would then point at the wrong lines (see the
    comment in apply_to_config)."""
    existing: dict[str, list[dict]] = {}
    current_mn: str | None = None
    current_block_start = -1
    current_block_lines: list[str] = []

    def flush():
        nonlocal current_mn, current_block_start, current_block_lines
        if current_mn is None:
            return
        # Parse model_id, api_base, ic, oc from the block
        model_id = ""
        api_base = ""
        ic = 0.0
        oc = 0.0
        for ln in current_block_lines:
            s = ln.strip()
            if s.startswith("model:") and "model_id" not in s:
                model_id = s.split("model:", 1)[1].strip()
            elif s.startswith("api_base:"):
                api_base = s.split("api_base:", 1)[1].strip()
            elif s.startswith("input_cost_per_token:"):
                try:
                    ic = float(s.split(":", 1)[1].strip())
                except ValueError:
                    ic = 0.0
            elif s.startswith("output_cost_per_token:"):
                try:
                    oc = float(s.split(":", 1)[1].strip())
                except ValueError:
                    oc = 0.0
        # Derive provider: render-config._provider_from_block also uses
        # api_base besides the prefix -- necessary because NVIDIA, GitHub
        # Models, OpenCode Zen, LLM7.io, and OVHcloud ALL share the
        # 'openai/' prefix. A plain prefix match used to lump all these
        # deployments together as 'nvidia', which made the apply plan fail
        # to recognize existing OVH/GitHub/LLM7 deployments and plan
        # duplicates.
        provider = ""
        if "/" in model_id:
            provider = _load_render_config_cached()._provider_from_block(model_id, api_base)
            if not provider:
                provider = model_id.split("/", 1)[0]
        existing.setdefault(current_mn, []).append({
            "provider": provider,
            "model_id": model_id,
            "ic": ic,
            "oc": oc,
            "line_start": current_block_start,
            "line_end": current_block_start + len(current_block_lines) - 1,
        })

    for i in range(model_list_start + 1, model_list_end):
        line = lines[i]
        s = line.lstrip()
        if s.startswith("- model_name:"):
            flush()
            current_mn = s.split("- model_name:", 1)[1].strip()
            current_block_start = i
            current_block_lines = [line]
        elif current_mn is not None:
            if not line.strip():
                # A blank line ALWAYS ends the current block. Deployment
                # blocks never have internal blank lines by convention (see
                # build_deployment()). The earlier version only looked 1
                # line ahead and only flushed if "- model_name:" followed
                # directly -- if a comment header followed instead (blank
                # line + 3 "#" lines before the next deployment), the
                # header was mistakenly pulled into the current block and
                # its line_end was computed too large by the header's
                # length. That made apply_to_config insert new deployments
                # RIGHT IN THE MIDDLE of the wrongly-bounded previous block
                # instead of after it.
                flush()
                current_mn = None
                current_block_lines = []
                continue
            current_block_lines.append(line)
    flush()

    return existing


def model_id_key(provider: str, model_id: str) -> str:
    """Normalizes (provider, model_id) into a comparison key."""
    return f"{provider}|{model_id.split('/')[-1].lower()}"


def generate_apply_plan(
    groups: dict[str, dict[str, list[str]]],
    zen_groups: dict[str, dict[str, list[str]]],
    existing: dict[str, list[dict]],
    pricing: dict[str, dict] | None,
) -> list[dict]:
    """
    Produces a list of apply operations:
      { 'model_name', 'provider', 'model_id', 'ic', 'oc', 'action' }
    'action' is 'add' (new entry), 'update_costs' (existing entry gets
    costs), or 'skip' (already present).
    """
    plan: list[dict] = []
    # Combine groups + zen_groups
    all_groups: dict[str, dict[str, list[str]]] = {}
    for n, p in groups.items():
        all_groups.setdefault(n, {}).update(p)
    for n, p in zen_groups.items():
        all_groups.setdefault(n, {}).update(p)

    # Groups are NORMALIZED names (e.g. "3-3-70b"), the template uses
    # readable model_names ("llama-3.3-70b-instruct"). Without this mapping
    # almost every existing deployment would be planned as "new" and
    # --apply would create duplicate blocks under the normalized names.
    norm_to_existing: dict[str, str] = {}
    for mn in existing:
        norm_to_existing.setdefault(normalize(mn), mn)

    # Global dedupe set: a deployment that already exists under ANY
    # model_name is never proposed again.
    global_keys = {
        model_id_key(e["provider"], e["model_id"])
        for entries in existing.values()
        for e in entries
    }

    for group_norm, providers in all_groups.items():
        if group_norm in norm_to_existing:
            model_name = norm_to_existing[group_norm]
        else:
            # New group: derive a readable name from one of the original
            # IDs instead of using the aggressively STOPWORDS-cleaned
            # grouping key directly as the model_name (that would be e.g.
            # "v4" instead of "deepseek-v4-pro", or "k2-5" instead of
            # "kimi-k2.5" -- see the pretty_model_name() docstring).
            # Deterministic: the alphabetically first original ID across
            # all providers of the group.
            sample_orig = min(o for origs in providers.values() for o in origs)
            model_name = pretty_model_name(sample_orig)
        existing_keys = set()
        if model_name in existing:
            for e in existing[model_name]:
                existing_keys.add(model_id_key(e["provider"], e["model_id"]))

        for provider, originals in providers.items():
            for orig in sorted(set(originals)):
                key = model_id_key(provider, orig)
                if key in existing_keys or key in global_keys:
                    plan.append({
                        "model_name": model_name,
                        "provider": provider,
                        "model_id": orig,
                        "action": "skip",
                    })
                    continue
                # Determine cost with fallback
                ic = 0.0
                oc = 0.0
                if pricing is not None:
                    entry, _ = lookup_price(pricing, provider, orig, with_fallback=True)
                    if entry is not None:
                        ic_val = entry.get("input_cost_per_token")
                        oc_val = entry.get("output_cost_per_token")
                        if isinstance(ic_val, (int, float)):
                            ic = float(ic_val)
                        if isinstance(oc_val, (int, float)):
                            oc = float(oc_val)
                plan.append({
                    "model_name": model_name,
                    "provider": provider,
                    "model_id": orig,
                    "ic": ic,
                    "oc": oc,
                    "action": "add",
                })
    return plan


def render_plan_diff(plan: list[dict]) -> str:
    """Formatted plan output for the console/report."""
    adds = [p for p in plan if p["action"] == "add"]
    skips = [p for p in plan if p["action"] == "skip"]
    lines: list[str] = []
    lines.append(f"  New deployments: {len(adds)}")
    lines.append(f"  Already present (skip): {len(skips)}")
    lines.append("")
    by_model: dict[str, list[dict]] = {}
    for p in adds:
        by_model.setdefault(p["model_name"], []).append(p)
    for mn in sorted(by_model):
        lines.append(f"  + {mn}  ({len(by_model[mn])} new provider(s))")
        for p in by_model[mn]:
            ic_s = fmt_cost(p["ic"])
            oc_s = fmt_cost(p["oc"])
            lines.append(
                f"      {p['provider']:14s}  {p['model_id']:48s}  "
                f"in={ic_s:>12s}  out={oc_s:>12s}"
            )
    return "\n".join(lines)


def apply_to_config(
    config_path: Path,
    plan: list[dict],
    groups: dict[str, dict[str, list[str]]],
    zen_groups: dict[str, dict[str, list[str]]],
    pricing: dict[str, dict] | None = None,
) -> tuple[int, int, int]:
    """
    Rewrites config.yaml:
      - Inserts new deployments at the end of the respective model_name
        block (or creates a fresh block at the end of model_list if it
        doesn't exist yet)
      - Updates model_info costs for existing entries that are currently
        0 where the plan proposes costs
      - Updates router_settings.fallbacks and context_window_fallbacks
    Returns (added, costs_updated, fallbacks_added).
    """
    lines, ml_start, ml_end, existing = parse_config(config_path)
    if ml_start < 0:
        raise RuntimeError("model_list not found in config.yaml")

    # 1) Group new deployments by model_name
    adds_by_model: dict[str, list[dict]] = {}
    for p in plan:
        if p["action"] == "add":
            adds_by_model.setdefault(p["model_name"], []).append(p)

    # 2) Which model_names are already in the config?
    existing_model_names = set(existing.keys())

    # 3) Insert new blocks at the end of model_list (before ml_end)
    new_blocks: list[str] = []
    for mn in sorted(adds_by_model):
        if mn not in existing_model_names:
            # Create a full new block with header
            n_providers = len(adds_by_model[mn])
            header = (
                f"  # ===========================================================================\n"
                f"  # {mn}  –  {n_providers} FREE PROVIDER{'S' if n_providers != 1 else ''}\n"
                f"  # ===========================================================================\n"
            )
            new_blocks.append("\n" + header)
            for p in adds_by_model[mn]:
                new_blocks.extend(
                    build_deployment(mn, p["provider"], p["model_id"], p["ic"], p["oc"])
                )

    # 4) Existing blocks: insert new provider deployments at the end
    insertions: list[tuple[int, list[str]]] = []  # (insert_index, lines_to_add)
    for mn, adds in adds_by_model.items():
        if mn in existing_model_names:
            # Last block index + 1
            last_idx = max(e["line_end"] for e in existing[mn])
            new_lines: list[str] = []
            for p in adds:
                new_lines.extend(
                    build_deployment(mn, p["provider"], p["model_id"], p["ic"], p["oc"])
                )
            if new_lines:
                insertions.append((last_idx + 1, new_lines))

    # 5) Apply: FIRST new blocks at ml_end, THEN insertions into existing
    #    blocks (back to front).
    #
    #    The order is not a style detail: ml_end was computed ONCE from the
    #    unmodified `lines`. Insertions (step 4) add lines at indices <
    #    ml_end and thereby shift everything after them further back -- if
    #    they were applied FIRST, the (un-adjusted) ml_end index in the
    #    now-grown new_lines list would be too SMALL by exactly that
    #    amount, and the new_blocks splice would land somewhere IN THE
    #    MIDDLE of model_list (observed live: a whole batch of new model
    #    blocks tore apart the existing deepseek-r1-0528 block). Inserting
    #    new_blocks FIRST at ml_end instead (new_lines is still identical
    #    to `lines` at that point, so the index is still valid) leaves all
    #    insertion indices (< ml_end) untouched.
    new_lines = list(lines)
    added_count = 0
    costs_updated = 0

    # New blocks before ml_end (that's the position of router_settings:)
    if new_blocks:
        insert_at = ml_end
        # ml_end is the index of the first non-indented line after model_list
        new_lines[insert_at:insert_at] = new_blocks
        added_count += sum(
            1 for block in new_blocks for ln in block.split("\n")
            if ln.strip().startswith("- model_name:")
        )

    # Insertions (back to front, so the indices don't invalidate each
    # other) -- all indices are < ml_end and thus unaffected by the
    # new_blocks splice above.
    for idx, new_block in sorted(insertions, key=lambda x: -x[0]):
        new_lines[idx:idx] = new_block
        added_count += sum(1 for ln in new_block if ln.strip().startswith("- model_name:"))

    # 6) Cost update for existing entries with 0 values
    #
    # IMPORTANT: `existing` (from the original parse_config() call) has
    # line_start/line_end from the UNMODIFIED text. new_lines above has
    # already been structurally changed by new_blocks + insertions though
    # -- a rescan is mandatory, otherwise this step patches cost lines at
    # the WRONG (shifted) positions (the same class of bug as the
    # new_blocks/ml_end corruption above, here for the cost-patch step).
    if pricing is not None:
        fresh_ml_start, fresh_ml_end = _find_model_list_bounds(new_lines)
        fresh_existing = _scan_existing_blocks(new_lines, fresh_ml_start, fresh_ml_end)
        new_lines, costs_updated = _update_existing_costs(new_lines, fresh_existing, plan)

    # 7) Add fallbacks
    new_lines, fallbacks_added = _update_fallbacks(new_lines, existing_model_names, adds_by_model)

    # 8) Atomic write via tmp + os.replace
    backup = config_path.with_suffix(
        config_path.suffix + f".bak.{int(time.time())}"
    )
    if config_path.exists():
        config_path.rename(backup)

    tmp = config_path.with_suffix(config_path.suffix + ".tmp")
    tmp.write_text("".join(new_lines), encoding="utf-8")
    os.replace(tmp, config_path)

    return added_count, costs_updated, fallbacks_added


def _update_existing_costs(
    lines: list[str],
    existing: dict[str, list[dict]],
    plan: list[dict],
) -> tuple[list[str], int]:
    """
    Sets input_cost_per_token/output_cost_per_token on existing blocks
    where it's currently 0 and the plan proposes costs.
    """
    # Map: (model_name, provider) -> (ic, oc)
    plan_costs: dict[tuple[str, str], tuple[float, float]] = {}
    for p in plan:
        if p["action"] in ("add", "skip") and "ic" in p:
            key = (p["model_name"], p["provider"])
            if key not in plan_costs:
                plan_costs[key] = (p["ic"], p["oc"])

    if not plan_costs:
        return lines, 0

    updated = 0
    new_lines = list(lines)
    for mn, entries in existing.items():
        for entry in entries:
            key = (mn, entry["provider"])
            if key not in plan_costs:
                continue
            ic, oc = plan_costs[key]
            if ic == 0 and oc == 0:
                continue
            if entry["ic"] != 0 or entry["oc"] != 0:
                continue
            # Patch the input_cost_per_token/output_cost_per_token line in the block
            for i in range(entry["line_start"], entry["line_end"] + 1):
                line = new_lines[i]
                s = line.strip()
                if s.startswith("input_cost_per_token:"):
                    new_lines[i] = re.sub(
                        r"input_cost_per_token:\s*[^\n]*",
                        f"      input_cost_per_token: {_fmt_cost_yaml(ic)}",
                        line,
                    )
                    updated += 1
                elif s.startswith("output_cost_per_token:"):
                    new_lines[i] = re.sub(
                        r"output_cost_per_token:\s*[^\n]*",
                        f"      output_cost_per_token: {_fmt_cost_yaml(oc)}",
                        line,
                    )
                    updated += 1
    return new_lines, updated


def _update_fallbacks(
    lines: list[str],
    existing_model_names: set[str],
    adds_by_model: dict[str, list[dict]],
) -> tuple[list[str], int]:
    """
    Adds new model_names to router_settings.fallbacks.
    Catch-all '*' only when >= 4 providers exist.
    """
    new_model_names = set(adds_by_model.keys()) - existing_model_names
    if not new_model_names:
        return lines, 0

    # Reasonable order: known capacity reserves
    fallback_pool = [
        "gpt-oss-120b", "llama-3.3-70b-instruct", "mistral-large",
        "gpt-oss-20b", "nemotron-3-120b", "command-r-plus", "llama-3.1-8b",
    ]

    added = 0
    new_lines = list(lines)
    # Find the 'fallbacks:' line (exactly, not 'context_window_fallbacks:')
    fallbacks_idx = -1
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if stripped == "fallbacks:":
            fallbacks_idx = i
            break
    if fallbacks_idx < 0:
        return lines, 0

    # Find block end: the 'fallbacks:' line has 2-space indent, its items
    # have 4-space indent. The block ends at a line with 2-space indent or
    # less, or at 'context_window_fallbacks:' / 'litellm_settings:' etc.
    block_end = len(new_lines)
    for i in range(fallbacks_idx + 1, len(new_lines)):
        s = new_lines[i]
        if not s.strip():
            continue  # skip blank lines
        # Items have 4-space indent ('    - {"..."')
        if s.startswith("    "):
            continue
        # Otherwise: 2-space indent (router_settings sibling) or 0-space (top-level)
        block_end = i
        break

    # Parse existing keys
    existing_keys: set[str] = set()
    for i in range(fallbacks_idx + 1, block_end):
        # Pattern: - {"<key>": ...}
        m = re.search(r'\{"([^"]+)":', new_lines[i])
        if m:
            existing_keys.add(m.group(1))

    # Insert new lines before block_end
    insertions: list[str] = []
    for mn in sorted(new_model_names):
        if mn in existing_keys:
            continue
        n_prov = len(adds_by_model.get(mn, []))
        chain = [c for c in fallback_pool if c != mn][:4]
        chain_str = ", ".join(f'"{c}"' for c in chain)
        insertions.append(f'    - {{"{mn}": [{chain_str}]}}\n')
        # Catch-all '*' only with >= 4 providers. Chain targets must be
        # current model_names; render-config.py additionally filters out
        # any targets that no longer exist in the model_list when rendering.
        if n_prov >= 4 and "*" not in existing_keys:
            existing_keys.add("*")
            insertions.append(
                '    - {"*": ["llama-3.1-8b", "gpt-oss-20b", '
                '"gemma-4-26b-a4b-it", "deepseek-v4-flash", "openrouter-free"]}\n'
            )
        added += 1

    if insertions:
        new_lines[block_end:block_end] = insertions
    return new_lines, added


def regenerate_multi_instance() -> bool:
    """
    Calls multi-instance/generate-config.py if it exists.
    Returns True on success.
    """
    import subprocess
    mi_dir = REPO_ROOT / "multi-instance"
    script = mi_dir / "generate-config.py"
    if not script.exists():
        return False
    try:
        result = subprocess.run(
            ["python3", str(script)],
            cwd=mi_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            print(result.stdout)
            return True
        print(f"  [WARN] multi-instance generate-config.py exit={result.returncode}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return False
    except Exception as exc:
        print(f"  [WARN] multi-instance regeneration failed: {exc}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def collect_models(env: dict[str, str]) -> tuple[dict[str, list[str]], list[tuple[str, str]]]:
    """
    Queries all provider catalogs in PARALLEL (previously sequential with
    a sleep in between -- needlessly slow with 13 providers). Results are
    deduplicated and sorted; output happens deterministically in
    PROVIDERS order.
    """
    from concurrent.futures import ThreadPoolExecutor

    PAID_FILTERED.clear()
    raw: dict[str, list[str]] = {}
    errors: list[tuple[str, str]] = []
    futures = {}

    with ThreadPoolExecutor(max_workers=8) as pool:
        for name, fn in PROVIDERS.items():
            needed = required_env(name)
            if any(not env.get(v) for v in needed):
                errors.append((name, "Missing key: " + ", ".join(needed)))
                continue
            futures[name] = pool.submit(fn, env)

        for name in PROVIDERS:
            fut = futures.get(name)
            if fut is None:
                continue
            try:
                fetched = [m for m in fut.result() if m]
                paid = sorted({m for m in fetched if is_paid_vendor_model(m, name)})
                models = sorted({m for m in fetched if not is_paid_vendor_model(m, name)})
                raw[name] = models
                partial = "  (incomplete fallback catalog)" if name in PARTIAL_CATALOGS else ""
                paid_note = f"  ({len(paid)} paid flagship model(s) filtered out)" if paid else ""
                print(f"  [OK]   {name:14s} {len(models):4d} models{partial}{paid_note}")
                if paid:
                    PAID_FILTERED.setdefault(name, []).extend(paid)
            except Exception as exc:
                errors.append((name, f"{type(exc).__name__}: {exc}"))
                print(f"  [FAIL] {name:14s} {type(exc).__name__}: {exc}")
    return raw, errors


def build_groups(raw: dict[str, list[str]]) -> dict[str, dict[str, list[str]]]:
    """
    Returns, per normalized name: { provider: [original names] }.
    """
    groups: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for provider, models in raw.items():
        for m in models:
            if not m:
                continue
            groups[normalize(m)][provider].append(m)
    return {k: dict(v) for k, v in groups.items() if len(v) >= 2}


def find_zen_groups(raw: dict[str, list[str]]) -> dict[str, dict[str, list[str]]]:
    """
    Zen models: include the group as soon as it shows up at any provider.
    Other providers are included if they carry the same normalized model.
    """
    out: dict[str, dict[str, list[str]]] = {}
    groups = build_groups(raw)
    for zen in ZEN_MODEL_NAMES:
        zen_norm = normalize(zen)
        # Correct candidate selection: exact normalized match, or a
        # substring match only at a '-' boundary, so e.g. "big-pickle"
        # doesn't wrongly pick up "big-pickle-extra".
        def _is_match(n: str) -> bool:
            if n == zen_norm:
                return True
            return (
                n.startswith(zen_norm + "-") or n.startswith("-" + zen_norm) or
                zen_norm.startswith(n + "-") or zen_norm.startswith("-" + n)
            )
        candidates = {zen_norm} | {n for n in groups if _is_match(n)}
        for norm in candidates:
            for provider, originals in raw.items():
                for orig in originals:
                    if normalize(orig) == norm:
                        out.setdefault(norm, defaultdict(list))[provider].append(orig)
    for k, v in out.items():
        out[k] = dict(v)
    return out


# model_names that are deliberately NOT checked against live catalogs
# (pseudo-/router models that don't show up in /models listings).
STALE_CHECK_EXEMPT = {"openrouter-free"}


def _native_model_id(model_id: str) -> str:
    """
    Removes the LiteLLM routing prefix (first path segment) and returns
    the provider-native model ID:
      openrouter/openai/gpt-oss-120b:free -> openai/gpt-oss-120b:free
      cerebras/gpt-oss-120b               -> gpt-oss-120b
      openai/openai/gpt-oss-120b (NVIDIA) -> openai/gpt-oss-120b
      huggingface/meta-llama/Llama-3.3    -> meta-llama/Llama-3.3
    """
    if "/" not in model_id:
        return model_id
    return model_id.split("/", 1)[1]


def find_stale_deployments(
    template_path: Path,
    raw: dict[str, list[str]],
    partial: set[str] | None = None,
) -> list[dict]:
    """
    Finds template deployments whose model no longer appears in the
    provider's LIVE catalog -- the opposite direction of the apply plan,
    which only knows about new additions. Report-only: removals stay
    deliberately manual (catalogs flap; cf. the gemma-3-12b-it history).

    Only checked against providers whose query succeeded AND was complete
    (no empty catalogs, no PARTIAL_CATALOGS).
    """
    partial = PARTIAL_CATALOGS if partial is None else partial
    rc = _load_render_config_module()
    lines = template_path.read_text(encoding="utf-8").splitlines(keepends=True)
    _, _, blocks = rc.parse_blocks(lines)

    catalogs = {
        p: {m.lower() for m in models}
        for p, models in raw.items()
        if models and p not in partial
    }

    stale: list[dict] = []
    for b in blocks:
        provider = b["provider"]
        if provider not in catalogs:
            continue
        if b["model_name"] in STALE_CHECK_EXEMPT:
            continue
        native = _native_model_id(b["model_id"])
        if native.lower() not in catalogs[provider]:
            stale.append({
                "model_name": b["model_name"],
                "provider": provider,
                "native_id": native,
            })
    return stale


def write_report(
    path: Path,
    raw: dict[str, list[str]],
    errors: list[tuple[str, str]],
    groups: dict[str, dict[str, list[str]]],
    zen_groups: dict[str, dict[str, list[str]]],
    pricing: dict[str, dict] | None = None,
    pricing_status: str = "disabled",
    plan: list[dict] | None = None,
    stale: list[dict] | None = None,
) -> None:
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("LiteLLM Free-Models – Provider Overlap Report")
    lines.append("Generated: " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
    lines.append("=" * 78)
    lines.append("")

    lines.append("─" * 78)
    lines.append("Queried providers")
    lines.append("─" * 78)
    for name in PROVIDERS:
        count = len(raw.get(name, []))
        if name in raw:
            lines.append(f"  [+] {name:14s} {count:4d} models")
        else:
            msg = next((e for n, e in errors if n == name), "unknown")
            lines.append(f"  [-] {name:14s} ERROR: {msg}")
    lines.append("")

    lines.append("─" * 78)
    lines.append(f"Models with >= 2 providers ({len(groups)} entries)")
    lines.append("─" * 78)
    if not groups:
        lines.append("  (none)")
    for norm in sorted(groups, key=lambda k: (-len(groups[k]), k)):
        providers = groups[norm]
        marker = " [ZEN]" if norm in {normalize(z) for z in ZEN_MODEL_NAMES} else ""
        lines.append(f"\n  Model: {norm}{marker}")
        lines.append(f"  Providers: {len(providers)}")
        for p in sorted(providers):
            origs = ", ".join(sorted(set(providers[p])))
            lines.append(f"    - {p:14s} {origs}")
    lines.append("")

    lines.append("─" * 78)
    lines.append("Zen models (always included, high usage limits)")
    lines.append("─" * 78)
    for zen in sorted(ZEN_MODEL_NAMES):
        zen_norm = normalize(zen)
        match = zen_groups.get(zen_norm) or {}
        if match:
            lines.append(f"\n  {zen}  (normalized: {zen_norm})")
            for p in sorted(match):
                lines.append(f"    - {p}: {', '.join(sorted(set(match[p])))}")
        else:
            lines.append(f"\n  {zen}  (normalized: {zen_norm})")
            lines.append("    - not found in the live query")
    lines.append("")

    lines.append("─" * 78)
    lines.append("Provider combinations with >= 2 shared models")
    lines.append("─" * 78)
    pair_count: dict[tuple[str, str], int] = defaultdict(int)
    pair_models: dict[tuple[str, str], set[str]] = defaultdict(set)
    for norm, providers in groups.items():
        plist = sorted(providers)
        for i in range(len(plist)):
            for j in range(i + 1, len(plist)):
                key = (plist[i], plist[j])
                pair_count[key] += 1
                pair_models[key].add(norm)

    rows = [(p, c, pair_models[p]) for p, c in pair_count.items() if c >= 2]
    rows.sort(key=lambda r: (-r[1], r[0]))
    if not rows:
        lines.append("  (no pairs with >= 2 shared models)")
    for (a, b), count, models in rows:
        lines.append(f"\n  {a}  <->  {b}   ({count} shared models)")
        for m in sorted(models):
            tag = " [ZEN]" if m in {normalize(z) for z in ZEN_MODEL_NAMES} else ""
            lines.append(f"      - {m}{tag}")
    lines.append("")

    # ------------------------------------------------------------------
    # Paid-vendor models filtered out
    # ------------------------------------------------------------------
    lines.append("─" * 78)
    lines.append("Filtered-out paid flagship models (paid-vendor denylist)")
    lines.append("─" * 78)
    lines.append("  Aggregators (OpenCode Zen, LLM7.io, ...) sometimes list models under")
    lines.append("  the brand names of paid flagship APIs (Claude, GPT-5.x, Gemini,")
    lines.append("  Grok, GLM-5.x, MiniMax) -- these are NEVER adopted automatically.")
    if not PAID_FILTERED:
        lines.append("  (none found)")
    else:
        for provider in sorted(PAID_FILTERED):
            lines.append(f"\n  {provider}:")
            for m in sorted(PAID_FILTERED[provider]):
                lines.append(f"    - {m}")
    lines.append("")

    lines.append("─" * 78)
    lines.append("Stale template deployments (model missing from the live catalog)")
    lines.append("─" * 78)
    lines.append("  Report-only: removals stay manual (catalogs flap).")
    lines.append("  Only checked against providers queried successfully and completely.")
    if stale is None:
        lines.append("  (check skipped: no template found)")
    elif not stale:
        lines.append("  (none — every template deployment is present in the catalogs)")
    else:
        for s in sorted(stale, key=lambda x: (x["provider"], x["model_name"])):
            lines.append(f"  [!] {s['provider']:14s} {s['model_name']:26s} -> {s['native_id']}")
    lines.append("")

    # ------------------------------------------------------------------
    # Cost & savings
    # ------------------------------------------------------------------
    lines.append("─" * 78)
    lines.append("Cost & savings (hypothetical paid-tier price)")
    lines.append("─" * 78)
    lines.append(f"  Source: {pricing_status}")
    if not pricing:
        lines.append("  (disabled -- rerun with pricing download enabled)")
    else:
        # 1) Per shared model: what would each provider cost?
        lines.append("")
        lines.append("  Per shared model, per provider (price in USD per 1M tokens):")
        lines.append("")
        header = f"  {'Model':40s}  {'Provider':14s}  {'Input':>12s}  {'Output':>12s}  {'DB key'}"
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))
        any_cost_row = False
        # Combine groups + zen_groups (both normalized)
        all_norm_groups: dict[str, dict[str, list[str]]] = {}
        for norm, provs in groups.items():
            all_norm_groups.setdefault(norm, {}).update(provs)
        for norm, provs in zen_groups.items():
            all_norm_groups.setdefault(norm, {}).update(provs)

        for norm in sorted(all_norm_groups):
            for provider, originals in sorted(all_norm_groups[norm].items()):
                ic_sum: float = 0.0
                oc_sum: float = 0.0
                db_keys: list[str] = []
                for orig in sorted(set(originals)):
                    entry, db_key = lookup_price(pricing, provider, orig, with_fallback=True)
                    if entry is None:
                        continue
                    ic = entry.get("input_cost_per_token")
                    oc = entry.get("output_cost_per_token")
                    if isinstance(ic, (int, float)) and ic > 0:
                        ic_sum += ic
                        any_cost_row = True
                    if isinstance(oc, (int, float)) and oc > 0:
                        oc_sum += oc
                        any_cost_row = True
                    if db_key:
                        db_keys.append(db_key)
                if not db_keys:
                    continue
                tag = " [ZEN]" if norm in {normalize(z) for z in ZEN_MODEL_NAMES} else ""
                in_str = fmt_cost(ic_sum) if ic_sum else "n/a (free tier)"
                out_str = fmt_cost(oc_sum) if oc_sum else "n/a (free tier)"
                # shortest DB key as display (one is enough)
                lines.append(
                    f"  {norm[:38]+tag:40s}  {provider:14s}  {in_str:>12s}  {out_str:>12s}  {db_keys[0]}"
                )
        if not any_cost_row:
            lines.append("  (no paid prices found in the DB for the listed models)")

        # 2) Per-provider sum: what would the free-tier proxy have
        #    hypothetically cost per 1M tokens if going directly to each
        #    provider? Assumption: 0.5M input + 0.5M output per 1M tokens.
        lines.append("")
        lines.append("  Hypothetical provider cost per 1M tokens (mix: 500K input + 500K output):")
        lines.append("")
        lines.append(f"  {'Provider':14s}  {'Mix cost':>14s}  {'Model count':>15s}")
        lines.append("  " + "-" * 50)
        provider_sums: dict[str, tuple[float, int]] = {}
        for norm, provs in all_norm_groups.items():
            for provider, originals in provs.items():
                cost = 0.0
                matched = 0
                for orig in set(originals):
                    entry, _ = lookup_price(pricing, provider, orig, with_fallback=True)
                    if entry is None:
                        continue
                    ic = entry.get("input_cost_per_token")
                    oc = entry.get("output_cost_per_token")
                    if not (isinstance(ic, (int, float)) and isinstance(oc, (int, float))):
                        continue
                    if ic == 0 and oc == 0:
                        continue
                    cost += 0.5 * 1e6 * ic + 0.5 * 1e6 * oc
                    matched += 1
                if matched == 0:
                    continue
                old = provider_sums.get(provider, (0.0, 0))
                provider_sums[provider] = (old[0] + cost, old[1] + matched)
        for p in sorted(provider_sums, key=lambda k: -provider_sums[k][0]):
            total, n = provider_sums[p]
            lines.append(f"  {p:14s}  ${total:>12.2f}  {n:>15d}")

        # 3) Top-5 savings-potential models
        lines.append("")
        lines.append("  Top 5 savings potential (most expensive paid price per model):")
        lines.append("")
        savings: list[tuple[str, float, str]] = []
        for norm, provs in all_norm_groups.items():
            best = 0.0
            best_prov = ""
            for provider, originals in provs.items():
                for orig in set(originals):
                    entry, _ = lookup_price(pricing, provider, orig, with_fallback=True)
                    if entry is None:
                        continue
                    ic = entry.get("input_cost_per_token") or 0
                    oc = entry.get("output_cost_per_token") or 0
                    if isinstance(ic, (int, float)) and isinstance(oc, (int, float)):
                        c = 0.5 * 1e6 * ic + 0.5 * 1e6 * oc
                        if c > best:
                            best = c
                            best_prov = provider
            if best > 0:
                savings.append((norm, best, best_prov))
        savings.sort(key=lambda r: -r[1])
        for norm, cost, prov in savings[:5]:
            tag = " [ZEN]" if norm in {normalize(z) for z in ZEN_MODEL_NAMES} else ""
            lines.append(f"  - {norm+tag:42s} would be ~${cost:.2f}/M on {prov}")
        if not savings:
            lines.append("  (no paid prices found)")

    # ------------------------------------------------------------------
    # Apply plan (diff preview for --apply)
    # ------------------------------------------------------------------
    if plan is not None:
        lines.append("")
        lines.append("─" * 78)
        lines.append("Apply plan (preview; --apply writes this to config.yaml)")
        lines.append("─" * 78)
        adds = [p for p in plan if p["action"] == "add"]
        skips = [p for p in plan if p["action"] == "skip"]
        lines.append(f"  New deployments: {len(adds)}")
        lines.append(f"  Already present (skip): {len(skips)}")
        if adds:
            lines.append("")
            by_model: dict[str, list[dict]] = {}
            for p in adds:
                by_model.setdefault(p["model_name"], []).append(p)
            for mn in sorted(by_model):
                lines.append(f"  + {mn}  ({len(by_model[mn])} new provider(s))")
                for p in by_model[mn]:
                    ic_s = fmt_cost(p["ic"])
                    oc_s = fmt_cost(p["oc"])
                    lines.append(
                        f"      {p['provider']:14s}  {p['model_id']:48s}  "
                        f"in={ic_s:>12s}  out={oc_s:>12s}"
                    )
        if not adds and not skips:
            lines.append("  (no plan -- config.yaml may be missing)")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Deployment matrix generator (--emit-matrix / --write-docs)
# ---------------------------------------------------------------------------

PROVIDER_DISPLAY = {
    "openrouter": "OpenRouter",
    "cerebras": "Cerebras",
    "groq": "Groq",
    "cloudflare": "Cloudflare",
    "google-ai": "Google AI Studio",
    "nvidia": "NVIDIA",
    "mistral": "Mistral",
    "cohere": "Cohere",
    "github": "GitHub Models",
    "opencode-zen": "OpenCode Zen",
    "llm7io": "LLM7.io",
    "huggingface": "HuggingFace",
    "ovhcloud": "OVHcloud",
}

MATRIX_BEGIN = "<!-- BEGIN GENERATED MODEL MATRIX (python3 find-shared-models.py --write-docs) -->"
MATRIX_END = "<!-- END GENERATED MODEL MATRIX -->"


def _load_render_config_module():
    """Loads render-config.py (hyphen in the name) as a module so its
    block parser incl. provider discrimination can be reused."""
    import importlib.util
    path = REPO_ROOT / "render-config.py"
    spec = importlib.util.spec_from_file_location("render_config", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_RC_MODULE = None


def _load_render_config_cached():
    """Cached variant for hot paths (parse_config calls provider
    discrimination once per deployment block)."""
    global _RC_MODULE
    if _RC_MODULE is None:
        _RC_MODULE = _load_render_config_module()
    return _RC_MODULE


def build_matrix(template_path: Path) -> str:
    """
    Builds the deployment matrix (Markdown table) from the template:
    model_name -> deployment count + provider list. This means the table
    in AGENTS.md/README.md no longer needs to be maintained by hand.
    """
    rc = _load_render_config_module()
    lines = template_path.read_text(encoding="utf-8").splitlines(keepends=True)
    _, _, blocks = rc.parse_blocks(lines)

    order: list[str] = []
    providers_by_model: dict[str, list[str]] = {}
    for b in blocks:
        mn = b["model_name"]
        if mn not in providers_by_model:
            providers_by_model[mn] = []
            order.append(mn)
        disp = PROVIDER_DISPLAY.get(b["provider"], b["provider"] or "?")
        if disp not in providers_by_model[mn]:
            providers_by_model[mn].append(disp)

    counts = {mn: sum(1 for b in blocks if b["model_name"] == mn) for mn in order}

    md: list[str] = []
    md.append(
        f"Snapshot (generated from `{template_path.name}`): "
        f"**{len(order)} model_names, {len(blocks)} base deployments**. "
        f"`render-config.py` removes deployments from providers without "
        f"an API key in `.env` — the effective count can therefore be lower."
    )
    md.append("")
    md.append("| model_name | Deployments | Provider |")
    md.append("|---|---|---|")
    for mn in sorted(order, key=lambda m: (-counts[m], m)):
        md.append(f"| `{mn}` | {counts[mn]} | {', '.join(providers_by_model[mn])} |")
    return "\n".join(md)


def write_matrix_into_docs(matrix_md: str, doc_paths: list[Path]) -> int:
    """Replaces the content between the MATRIX markers in the doc files."""
    updated = 0
    replacement = f"{MATRIX_BEGIN}\n{matrix_md}\n{MATRIX_END}"
    for p in doc_paths:
        if not p.exists():
            print(f"  [WARN] {p} not found, skipped")
            continue
        text = p.read_text(encoding="utf-8")
        if MATRIX_BEGIN not in text or MATRIX_END not in text:
            print(f"  [WARN] Markers missing in {p.name}, skipped "
                  f"(expected: {MATRIX_BEGIN})")
            continue
        pattern = re.escape(MATRIX_BEGIN) + r".*?" + re.escape(MATRIX_END)
        new_text = re.sub(pattern, replacement.replace("\\", r"\\"), text, count=1, flags=re.DOTALL)
        if new_text != text:
            p.write_text(new_text, encoding="utf-8")
            print(f"  Matrix updated in {p.name}")
            updated += 1
        else:
            print(f"  {p.name} already up to date")
    return updated


def main() -> int:
    global PRICING_CACHE, PRICING_URL
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--env", type=Path, default=DEFAULT_ENV, help="Path to the .env file")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output file")
    ap.add_argument("--no-pricing", action="store_true",
                    help="Skip the pricing download (no cost report)")
    ap.add_argument("--refresh-pricing", action="store_true",
                    help="Ignore the pricing cache and reload from GitHub")
    ap.add_argument("--pricing-url", default=PRICING_URL,
                    help="Alternative URL for model_prices_and_context_window.json "
                         "(default: GitHub raw)")
    ap.add_argument("--pricing-cache", type=Path, default=PRICING_CACHE,
                    help="Local cache path for the pricing DB")
    ap.add_argument("--config", type=Path,
                    default=REPO_ROOT / "config.yaml",
                    help="Fallback path to config.yaml. Only used when "
                         "config.template.yaml doesn't exist (old state "
                         "without the template pipeline).")
    ap.add_argument("--template", type=Path,
                    default=REPO_ROOT / "config.template.yaml",
                    help="Path to config.template.yaml (single source of truth). "
                         "If present, --apply writes to the template and calls "
                         "render-config.py afterwards.")
    ap.add_argument("--apply", action="store_true",
                    help="Write changes to config.template.yaml (single "
                         "source of truth) and render them to config.yaml "
                         "via render-config.py (default: diff in the report only)")
    ap.add_argument("--regen-multi-instance", action="store_true",
                    help="Run multi-instance/generate-config.py after --apply")
    ap.add_argument("--emit-matrix", action="store_true",
                    help="Write the deployment matrix (Markdown) from the "
                         "template to stdout and exit (no API queries)")
    ap.add_argument("--write-docs", action="store_true",
                    help="Write the deployment matrix between the marker "
                         "comments in AGENTS.md and README.md and exit")
    args = ap.parse_args()

    # Matrix modes need neither .env nor provider queries
    if args.emit_matrix or args.write_docs:
        src = args.template if args.template.exists() else args.config
        if not src.exists():
            print(f"ERROR: {src} not found.", file=sys.stderr)
            return 2
        matrix = build_matrix(src)
        if args.write_docs:
            write_matrix_into_docs(
                matrix, [REPO_ROOT / "AGENTS.md", REPO_ROOT / "README.md"]
            )
        else:
            print(matrix)
        return 0

    env = load_env(args.env)
    if not env:
        print(f"ERROR: {args.env} not found or empty.", file=sys.stderr)
        return 2

    print(f"Loading .env from {args.env}")
    print("Querying...\n")
    raw, errors = collect_models(env)
    print()

    groups = build_groups(raw)
    zen_groups = find_zen_groups(raw)

    pricing: dict[str, dict] | None = None
    pricing_status = "disabled"
    if not args.no_pricing:
        # Patch the cache path at runtime (enables the --pricing-cache override)
        PRICING_CACHE = args.pricing_cache
        PRICING_CACHE.parent.mkdir(parents=True, exist_ok=True)
        url = args.pricing_url
        try:
            # On refresh, the pricing index must be rebuilt, otherwise it
            # would still point at the old DB.
            if args.refresh_pricing:
                _reset_pricing_index()
            pricing = load_pricing(force_refresh=args.refresh_pricing)
            cache_age = "live"
            if PRICING_CACHE.exists():
                age_s = time.time() - PRICING_CACHE.stat().st_mtime
                if age_s < 60:
                    cache_age = "live (<1 min old)"
                elif age_s < PRICING_TTL_SECONDS:
                    cache_age = f"cache ({int(age_s // 3600)}h {int(age_s % 3600 // 60)}m old)"
                else:
                    cache_age = f"cache (expired, {int(age_s // 3600)}h)"
            pricing_status = (
                f"{url}  |  {cache_age}  |  "
                f"{len([k for k in pricing if k != 'sample_spec'])} model entries"
            )
            print(f"Pricing DB: {pricing_status}")
        except Exception as exc:
            print(f"  [WARN] Pricing download failed: {exc}", file=sys.stderr)
            pricing = None
            pricing_status = f"failed ({exc})"

    # Apply plan (only if config or template exists; otherwise report only).
    # The template takes precedence because it's the single source of truth.
    plan: list[dict] = []
    target_for_apply: Path | None = None
    is_template = False
    if args.template.exists():
        target_for_apply = args.template
        is_template = True
        _, _, _, existing = parse_config(args.template)
        plan = generate_apply_plan(groups, zen_groups, existing, pricing)
        print(f"\nApply plan (template): {len([p for p in plan if p['action'] == 'add'])} "
              f"new deployment(s), {len([p for p in plan if p['action'] == 'skip'])} already present")
    elif args.config.exists():
        target_for_apply = args.config
        _, _, _, existing = parse_config(args.config)
        plan = generate_apply_plan(groups, zen_groups, existing, pricing)
        print(f"\nApply plan (config.yaml): {len([p for p in plan if p['action'] == 'add'])} "
              f"new deployment(s), {len([p for p in plan if p['action'] == 'skip'])} already present")
    else:
        print(f"\n  [WARN] Neither {args.template} nor {args.config} found, "
              "skipping apply plan.", file=sys.stderr)

    # Opposite direction of the apply plan: template deployments whose
    # model is missing from the live catalog (report-only, no automatic removal).
    stale: list[dict] | None = None
    if args.template.exists() and raw:
        stale = find_stale_deployments(args.template, raw)
        if stale:
            print(f"\n[WARN] {len(stale)} template deployment(s) no longer found "
                  f"in the provider catalog — see the report (section "
                  f"'Stale template deployments') for details.")

    write_report(args.output, raw, errors, groups, zen_groups, pricing,
                 pricing_status, plan, stale)
    print(f"\nReport written to: {args.output}")

    if args.apply and plan and target_for_apply is not None:
        any_adds = any(p["action"] == "add" for p in plan)
        if not any_adds:
            print("\nNo new deployments, config.yaml stays unchanged.")
            return 0
        print("\n" + "=" * 78)
        if is_template:
            print(f"APPLY -- writing changes to the template {args.template}")
        else:
            print(f"APPLY -- writing changes to {args.config}")
        print("=" * 78)
        print(render_plan_diff(plan))
        added, costs, fallbacks = apply_to_config(
            target_for_apply, plan, groups, zen_groups, pricing,
        )
        print(f"\n  Deployments added:  {added}")
        print(f"  Costs updated:      {costs}")
        print(f"  Fallbacks added:    {fallbacks}")
        if is_template:
            print("\n  Rendering config.template.yaml -> config.yaml via render-config.py ...")
            import subprocess
            render_script = REPO_ROOT / "render-config.py"
            if render_script.exists():
                result = subprocess.run(
                    ["python3", str(render_script)],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    print(result.stdout)
                else:
                    print(f"  [WARN] render-config.py exit={result.returncode}", file=sys.stderr)
                    print(result.stderr, file=sys.stderr)
            else:
                print(f"  [WARN] {render_script} missing, skipping render.", file=sys.stderr)
        if args.regen_multi_instance:
            print("\n  Regenerating multi-instance/ ...")
            regenerate_multi_instance()
        print(f"\nDone. Backup at {target_for_apply}.bak.*")
        return 0
    elif not args.apply and plan:
        if is_template:
            print(f"\nTip: with --apply, the {len([p for p in plan if p['action'] == 'add'])} "
                  "new deployment(s) will be written to config.template.yaml and "
                  "then rendered into config.yaml via render-config.py.")
        else:
            print(f"\nTip: with --apply, the {len([p for p in plan if p['action'] == 'add'])} "
                  "new deployment(s) will be written to config.yaml.")
        if plan:
            print("\n  Diff preview:")
            print(render_plan_diff(plan))
    return 0


if __name__ == "__main__":
    sys.exit(main())
