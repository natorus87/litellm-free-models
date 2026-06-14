#!/usr/bin/env python3
"""
Findet gemeinsame Modelle zwischen Providern und zeigt, was sie auf dem
jeweiligen Paid-Tier kosten wuerden (Sparpotenzial-Anzeige).

Liest API-Keys aus .env, fragt pro Provider die verfuegbaren Modelle ab,
gruppiert nach normalisiertem Namen und schreibt Provider-Kombinationen mit
mindestens 2 gleichen Modellen in providers-overlap.txt.

Zen-Modelle (deepseek-v4-flash, nemotron-3-ultra, big-pickle, north-mini-code)
werden immer aufgenommen, sobald sie ueberhaupt bei irgendeinem Provider
gefunden werden.

Preisdaten stammen aus der LiteLLM-Referenzdatenbank
(https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json,
 identisch mit https://models.litellm.ai/) und werden 24h lokal gecached
(.cache/litellm-prices.json). Pro gemeinsam genutztem Modell zeigt der
Report den hypothetischen Paid-Preis pro 1M Tokens fuer Input und Output --
sodass sichtbar wird, wieviel die Free-Tier-Nutzung einspart.

Nutzung:
    python3 find-shared-models.py
    python3 find-shared-models.py --env /pfad/zur/.env
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from providers_config import PROVIDERS as PROVIDER_CONFIGS

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_ENV = REPO_ROOT / ".env"
DEFAULT_OUTPUT = REPO_ROOT / "providers-overlap.txt"

# LiteLLM model_prices_and_context_window.json (1.5MB, ~2800 Modelle).
# Wird auch von https://models.litellm.ai/ als Datenquelle verwendet.
PRICING_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
PRICING_CACHE = REPO_ROOT / ".cache" / "litellm-prices.json"
PRICING_TTL_SECONDS = 24 * 3600

# Wie wir unsere Provider-Namen auf LiteLLM-Provider mappen.
# Wird aus providers_config.py abgeleitet, damit eine einzige Quelle gilt.
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


def http_get_json(url: str, headers: dict[str, str], timeout: int = 30) -> any:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


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


# ---------------------------------------------------------------------------
# Provider-Definitionen
# ---------------------------------------------------------------------------

def fetch_openrouter(key: str) -> list[str]:
    data = http_get_json(
        "https://openrouter.ai/api/v1/models",
        {"Authorization": f"Bearer {key}"},
    )
    return [m["id"] for m in data.get("data", [])]


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
    url = api_base.rstrip("/") + "/models"
    data = http_get_json(url, {"Authorization": f"Bearer {api_key}"})
    if isinstance(data, dict) and "result" in data:
        data = data["result"]
    if isinstance(data, dict) and "models" in data:
        data = data["models"]
    names: list[str] = []
    for m in data:
        if isinstance(m, str):
            names.append(m)
        elif isinstance(m, dict):
            names.append(m.get("name") or m.get("id") or m.get("model") or "")
    return [n for n in names if n]


def fetch_google_ai(key: str) -> list[str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={urllib.parse.quote(key)}"
    data = http_get_json(url, {})
    return [
        m.get("name", "").split("/")[-1]
        for m in data.get("models", [])
        if m.get("name")
    ]


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


def fetch_cohere(key: str) -> list[str]:
    try:
        data = http_get_json(
            "https://api.cohere.ai/v1/models",
            {"Authorization": f"Bearer {key}"},
        )
    except urllib.error.HTTPError:
        req = urllib.request.Request(
            "https://api.cohere.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    names: list[str] = []
    for m in data.get("models", []):
        names.extend(m.get("endpoints") or [])
    if not names:
        names = [m.get("name", "") for m in data.get("models", [])]
    return [n for n in names if n]


def fetch_github_models(token: str) -> list[str]:
    data = http_get_json(
        "https://models.inference.ai.azure.com/models",
        {"Authorization": f"Bearer {token}"},
    )
    return [m.get("name") or m.get("id") for m in data.get("models", data.get("data", [])) if m.get("name") or m.get("id")]


def fetch_opencode_zen(key: str) -> list[str]:
    try:
        data = http_get_json(
            "https://opencode.ai/zen/v1/models",
            {"Authorization": f"Bearer {key}"},
        )
    except urllib.error.HTTPError:
        return []
    return [m.get("id") or m.get("name") for m in data.get("data", []) if m.get("id") or m.get("name")]


def fetch_llm7io(key: str) -> list[str]:
    headers: dict[str, str] = {}
    if key and key != "unused":
        headers["Authorization"] = f"Bearer {key}"
    data = http_get_json("https://api.llm7.io/v1/models", headers)
    return [m["id"] for m in data.get("data", [])]


def fetch_ovhcloud(*_args) -> list[str]:
    """
    OVHcloud AI Endpoints - OpenAI-kompatibel, **kein API-Key erforderlich**
    (anonymer Free-Tier, 2 RPM/IP/Modell).

    Sendet bewusst KEINEN Authorization-Header, weil:
      - `Authorization: Bearer` (leer)   -> 200 OK
      - `Authorization: Bearer undefined` -> 403
      - `Authorization: Bearer none`      -> 403
    """
    data = http_get_json(
        "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/models",
        {},
    )
    return [m["id"] for m in data.get("data", []) if m.get("id")]


def fetch_huggingface(token: str) -> list[str]:
    """
    Liefert nicht die 150k+ Modelle, sondern eine kuratierte Liste bekannter
    Free-Inference-Modelle. Die komplette Liste ist nicht praktikabel filterbar.
    """
    known = [
        "meta-llama/Meta-Llama-3-8B-Instruct",
        "meta-llama/Meta-Llama-3.1-8B-Instruct",
        "meta-llama/Llama-3.2-3B-Instruct",
        "meta-llama/Llama-3.2-11B-Vision-Instruct",
        "mistralai/Mistral-7B-Instruct-v0.3",
        "mistralai/Mistral-Nemo-Instruct-2407",
        "google/gemma-2-9b-it",
        "google/gemma-2-27b-it",
        "Qwen/Qwen2.5-7B-Instruct",
        "Qwen/Qwen2.5-Coder-32B-Instruct",
        "deepseek-ai/DeepSeek-V3",
        "deepseek-ai/DeepSeek-R1",
        "microsoft/Phi-3.5-mini-instruct",
        "microsoft/Phi-3-medium-128k-instruct",
        "NousResearch/Hermes-3-Llama-3.1-8B",
    ]
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        req = urllib.request.Request(
            "https://huggingface.co/api/whoami-v2",
            headers=headers,
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=15):
            pass
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        # Token ungueltig oder Netzwerkfehler -- das ist OK, da der Token
        # nur fuer die whoami-Validierung gebraucht wird, nicht fuer die
        # eigentliche Modellabfrage.
        pass
    return known


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


def required_env(name: str) -> list[str]:
    if name in {"openrouter"}:        return ["OPENROUTER_API_KEY"]
    if name in {"cerebras"}:          return ["CEREBRAS_API_KEY"]
    if name in {"groq"}:              return ["GROQ_API_KEY"]
    if name in {"cloudflare"}:        return ["CLOUDFLARE_API_KEY", "CLOUDFLARE_API_BASE"]
    if name in {"google-ai"}:         return ["GEMINI_API_KEY"]
    if name in {"nvidia"}:            return ["NVIDIA_API_KEY"]
    if name in {"mistral"}:           return ["MISTRAL_API_KEY"]
    if name in {"cohere"}:            return ["COHERE_API_KEY"]
    if name in {"github"}:            return ["GITHUB_TOKEN"]
    if name in {"opencode-zen"}:      return ["OPENCODE_ZEN_API_KEY"]
    if name in {"llm7io"}:            return []
    if name in {"huggingface"}:       return []
    if name in {"ovhcloud"}:           return []  # Anonymer Free-Tier, kein Key noetig
    return []


# ---------------------------------------------------------------------------
# Preisdaten (LiteLLM-Referenzdatenbank)
# ---------------------------------------------------------------------------

def load_pricing(force_refresh: bool = False) -> dict[str, dict]:
    """
    Laedt model_prices_and_context_window.json mit 24h-Cache.

    Liefert ein Dict: { "openrouter/openai/gpt-oss-120b": {...}, ... }.
    Bei Netzwerkfehler und vorhandenem Cache wird der Cache verwendet.
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
            print(f"  [WARN] Pricing-Download fehlgeschlagen ({exc}), nutze Cache.", file=sys.stderr)
            return json.loads(PRICING_CACHE.read_text(encoding="utf-8"))
        raise

    PRICING_CACHE.write_text(json.dumps(data), encoding="utf-8")
    return data


def _strip_vendor(model_id: str) -> str:
    """Entfernt fuehrende Vendor-Praefixe (openai/, meta-llama/, ...)."""
    parts = model_id.split("/", 1)
    if len(parts) == 2 and parts[0] in {
        "openai", "meta-llama", "mistralai", "google", "nvidia", "deepseek-ai",
        "deepseek", "anthropic", "microsoft", "qwen", "alibaba", "ibm",
        "cohere", "moonshotai", "nousresearch",
    }:
        return parts[1]
    return model_id


def _strip_free_suffix(model_id: str) -> str:
    """':free' und '-free' entfernen, nicht aber '-free-free' doppelt."""
    s = re.sub(r":free$", "", model_id)
    s = re.sub(r"-free$", "", s)
    return s


class _PricingIndex:
    """
    Invertierter Index ueber die LiteLLM-Preisdatenbank:
        model_norm_lower -> [(entry, db_key, cost_mix), ...]
    wobei 'cost_mix' = 0.5M * ic + 0.5M * oc (fuer 1M Tokens 50/50 Mix).
    Wird einmal pro Pricing-Load gebaut, danach O(1)-Lookups in lookup_price().
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
    """Fuer Tests: Index invalidieren."""
    global _PRICING_INDEX
    _PRICING_INDEX = None


def lookup_price(
    pricing: dict[str, dict],
    provider: str,
    model_id: str,
    with_fallback: bool = False,
) -> tuple[dict | None, str | None]:
    """
    Mappt (provider, model_id) -> (DB-Eintrag, DB-Key) oder (None, None).

    Beispiele:
      ('openrouter', 'openai/gpt-oss-120b:free')  -> openrouter/openai/gpt-oss-120b
      ('cerebras',   'gpt-oss-120b')             -> cerebras/gpt-oss-120b
      ('nvidia',     'openai/gpt-oss-120b')      -> nvidia_nim/openai/gpt-oss-120b

    Mit with_fallback=True wird, falls kein direkter Match gefunden wird,
    ueber alle LiteLLM-Provider nach demselben Modellnamen gesucht und der
    Eintrag mit dem niedrigsten 'Mix-Preis' (Input+Output) zurueckgegeben.

    Verwendet einen invertierten Index (_PricingIndex) ueber die Pricing-DB,
    sodass Fallback-Suchen O(1) statt O(n) pro Aufruf sind.
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

    # Fallback: gleicher Modellname ueber alle LiteLLM-Provider (O(1) via Index)
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
# Apply-Engine: config.yaml strukturell aktualisieren
# ---------------------------------------------------------------------------

# Provider -> (litellm_params Praefix, env_var, api_base env var oder None,
#              rpm default, tpm default, requires api_base) wird zentral
# aus providers_config.PROVIDERS abgeleitet -- keine Doppel-Pflege mehr.


def build_deployment(
    model_name: str,
    provider: str,
    model_id: str,
    ic: float = 0.0,
    oc: float = 0.0,
) -> list[str]:
    """
    Erzeugt einen Deployment-Block (Liste von YAML-Zeilen, 2-Space-Indent) fuer
    die model_list. Beispiel:

      - model_name: gpt-oss-120b
        litellm_params:
          model: openrouter/openai/gpt-oss-120b
          api_key: os.environ/OPENROUTER_API_KEY
        model_info:
          input_cost_per_token: 0
          output_cost_per_token: 0
          mode: chat
        tpm: 200000
        rpm: 1
    """
    prov = PROVIDER_CONFIGS[provider]

    # model_id wird verbatim hinter den Provider-Prefix gehaengt.
    # Fuer NVIDIA ist das z.B. "openai/openai/gpt-oss-120b" (gewollt, siehe
    # AGENTS.md §2). Wenn model_id bereits einen Vendor-Prefix traegt
    # (z.B. "openai/..."), entsteht "openai/openai/..." -- das ist die
    # dokumentierte Konvention und wird von LiteLLM korrekt geroutet.
    model_str = f"{prov.prefix}/{model_id}"

    lines: list[str] = []
    lines.append(f"  - model_name: {model_name}\n")
    lines.append(f"    litellm_params:\n")
    lines.append(f"      model: {model_str}\n")
    if prov.env_var:
        lines.append(f"      api_key: os.environ/{prov.env_var}\n")
    else:
        lines.append(f"      api_key: \"\"\n")
    if prov.needs_api_base:
        if prov.api_base_env:
            lines.append(f"      api_base: os.environ/{prov.api_base_env}\n")
        elif prov.api_base_static:
            lines.append(f"      api_base: {prov.api_base_static}\n")
    lines.append(f"    model_info:\n")
    lines.append(f"      input_cost_per_token: {_fmt_cost_yaml(ic)}\n")
    lines.append(f"      output_cost_per_token: {_fmt_cost_yaml(oc)}\n")
    lines.append(f"      mode: chat\n")
    lines.append(f"    tpm: {prov.tpm}\n")
    lines.append(f"    rpm: {prov.rpm}\n")
    lines.append("\n")  # Leerzeile nach Block
    return lines


def _fmt_cost_yaml(value: float) -> str:
    """Werte < 1e-3 als scientific notation (1e-07), 0 als 0."""
    if value == 0:
        return "0"
    if value < 1e-3:
        # z.B. 1e-07
        return f"{value:g}"
    return f"{value}"


def parse_config(path: Path) -> tuple[list[str], int, int, dict[str, list[dict]]]:
    """
    Liest config.yaml zeilenbasiert. Liefert:
      - alle Zeilen
      - Index wo 'model_list:' steht (oder -1)
      - Index wo 'router_settings:' (oder naechster top-level key) steht
      - parsed existing models: { model_name: [ {provider, model_id, ic, oc, line_start, line_end} ] }
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)

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

    existing: dict[str, list[dict]] = {}
    current_mn: str | None = None
    current_block_start = -1
    current_block_lines: list[str] = []

    def flush():
        nonlocal current_mn, current_block_start, current_block_lines
        if current_mn is None:
            return
        # Parse model_id, ic, oc aus dem Block
        model_id = ""
        ic = 0.0
        oc = 0.0
        for ln in current_block_lines:
            s = ln.strip()
            if s.startswith("model:") and "model_id" not in s:
                model_id = s.split("model:", 1)[1].strip()
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
        # Provider ableiten aus 'model:' String (z.B. 'openrouter/...')
        provider = ""
        if "/" in model_id:
            prefix = model_id.split("/", 1)[0]
            for name, p in PROVIDER_CONFIGS.items():
                if p.prefix == prefix:
                    provider = name
                    break
            if not provider:
                provider = prefix
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
            if not line.strip() and i + 1 < model_list_end:
                # Leerzeile am Block-Ende? Nur flushen wenn der naechste Eintrag
                # mit "- model_name:" startet
                next_line = lines[i + 1] if i + 1 < len(lines) else ""
                if next_line.lstrip().startswith("- model_name:"):
                    flush()
                    current_mn = None
                    current_block_lines = []
                    continue
            current_block_lines.append(line)
    flush()

    return lines, model_list_start, model_list_end, existing


def model_id_key(provider: str, model_id: str) -> str:
    """Normalisiert (provider, model_id) zu einem Vergleichs-Key."""
    return f"{provider}|{model_id.split('/')[-1].lower()}"


def generate_apply_plan(
    groups: dict[str, dict[str, list[str]]],
    zen_groups: dict[str, dict[str, list[str]]],
    existing: dict[str, list[dict]],
    pricing: dict[str, dict] | None,
) -> list[dict]:
    """
    Erzeugt eine Liste von Apply-Operationen:
      { 'model_name', 'provider', 'model_id', 'ic', 'oc', 'action' }
    'action' ist 'add' (neuer Eintrag) oder 'update_costs' (bestehender
    Eintrag bekommt Kosten) oder 'skip' (bereits vorhanden).
    """
    plan: list[dict] = []
    # Kombiniere groups + zen_groups
    all_groups: dict[str, dict[str, list[str]]] = {}
    for n, p in groups.items():
        all_groups.setdefault(n, {}).update(p)
    for n, p in zen_groups.items():
        all_groups.setdefault(n, {}).update(p)

    for model_name, providers in all_groups.items():
        # Bestehende Eintraege als Set
        existing_keys = set()
        if model_name in existing:
            for e in existing[model_name]:
                existing_keys.add(model_id_key(e["provider"], e["model_id"]))

        for provider, originals in providers.items():
            for orig in sorted(set(originals)):
                key = model_id_key(provider, orig)
                if key in existing_keys:
                    plan.append({
                        "model_name": model_name,
                        "provider": provider,
                        "model_id": orig,
                        "action": "skip",
                    })
                    continue
                # Kosten mit Fallback bestimmen
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
    """Formatierter Plan-Output fuer Konsole/Report."""
    adds = [p for p in plan if p["action"] == "add"]
    skips = [p for p in plan if p["action"] == "skip"]
    lines: list[str] = []
    lines.append(f"  Neue Deployments: {len(adds)}")
    lines.append(f"  Bereits vorhanden (skip): {len(skips)}")
    lines.append("")
    by_model: dict[str, list[dict]] = {}
    for p in adds:
        by_model.setdefault(p["model_name"], []).append(p)
    for mn in sorted(by_model):
        lines.append(f"  + {mn}  ({len(by_model[mn])} neue Provider)")
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
    Schreibt config.yaml neu:
      - Fuegt neue Deployments am Ende des jeweiligen model_name-Blocks ein
        (oder am Anfang von model_list wenn der Block noch nicht existiert)
      - Aktualisiert model_info-Kosten fuer bestehende Eintraege mit 0-Werten
        wo der Plan Kosten hat
      - Aktualisiert router_settings.fallbacks und context_window_fallbacks
    Liefert (added, costs_updated, fallbacks_added).
    """
    lines, ml_start, ml_end, existing = parse_config(config_path)
    if ml_start < 0:
        raise RuntimeError("model_list nicht gefunden in config.yaml")

    # 1) Neue Deployments gruppieren pro model_name
    adds_by_model: dict[str, list[dict]] = {}
    for p in plan:
        if p["action"] == "add":
            adds_by_model.setdefault(p["model_name"], []).append(p)

    # 2) Welche model_names sind in der config?
    existing_model_names = set(existing.keys())

    # 3) Neue Bloecke am Ende der model_list (vor ml_end) einfuegen
    new_blocks: list[str] = []
    for mn in sorted(adds_by_model):
        if mn not in existing_model_names:
            # Kompletten neuen Block mit Header anlegen
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

    # 4) Bestehende Bloecke: neue Provider-Deployments am Ende einfuegen
    insertions: list[tuple[int, list[str]]] = []  # (insert_index, lines_to_add)
    for mn, adds in adds_by_model.items():
        if mn in existing_model_names:
            # Letzter Block-Index + 1
            last_idx = max(e["line_end"] for e in existing[mn])
            new_lines: list[str] = []
            for p in adds:
                new_lines.extend(
                    build_deployment(mn, p["provider"], p["model_id"], p["ic"], p["oc"])
                )
            if new_lines:
                insertions.append((last_idx + 1, new_lines))

    # 5) Anwenden: zuerst neue Bloecke am Listenende, dann Insertions in
    #    bestehende Bloecke (von hinten nach vorne, damit Indizes stabil)
    new_lines = list(lines)
    added_count = 0
    costs_updated = 0

    # Insertions (von hinten)
    for idx, new_block in sorted(insertions, key=lambda x: -x[0]):
        new_lines[idx:idx] = new_block
        added_count += sum(1 for ln in new_block if ln.strip().startswith("- model_name:"))

    # Neue Bloecke vor ml_end (das ist die Position von router_settings:)
    if new_blocks:
        insert_at = ml_end
        # ml_end ist der Index der ersten nicht-indented Zeile nach model_list
        new_lines[insert_at:insert_at] = new_blocks
        added_count += sum(
            1 for block in new_blocks for ln in block.split("\n")
            if ln.strip().startswith("- model_name:")
        )

    # 6) Kosten-Update fuer bestehende Eintraege mit 0-Werten
    if pricing is not None:
        new_lines, costs_updated = _update_existing_costs(new_lines, existing, plan)

    # 7) Fallbacks ergaenzen
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
    Setzt input_cost_per_token/output_cost_per_token in bestehenden Bloecken,
    wo aktuell 0 ist und der Plan Kosten vorschlaegt.
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
            # Zeile input_cost_per_token/output_cost_per_token im Block patchen
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
    Ergaenzt router_settings.fallbacks um neue model_names.
    Catch-All '*' nur wenn >= 4 Provider vorhanden.
    """
    new_model_names = set(adds_by_model.keys()) - existing_model_names
    if not new_model_names:
        return lines, 0

    # Sinnvolle Reihenfolge: bekannte Capacity-Reserven
    fallback_pool = [
        "gpt-oss-120b", "llama-3.3-70b-instruct", "mistral-large",
        "gpt-oss-20b", "nemotron-3-120b", "command-r-plus", "llama-3.1-8b",
    ]

    added = 0
    new_lines = list(lines)
    # Finde die 'fallbacks:' Zeile (genau, nicht 'context_window_fallbacks:')
    fallbacks_idx = -1
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if stripped == "fallbacks:":
            fallbacks_idx = i
            break
    if fallbacks_idx < 0:
        return lines, 0

    # Finde Block-Ende: die 'fallbacks:' Zeile hat 2-Space-Indent, ihre Items
    # 4-Space-Indent. Block endet bei einer Zeile mit 2-Space-Indent oder weniger,
    # oder bei 'context_window_fallbacks:' / 'litellm_settings:' etc.
    block_end = len(new_lines)
    for i in range(fallbacks_idx + 1, len(new_lines)):
        s = new_lines[i]
        if not s.strip():
            continue  # Leerzeilen ueberspringen
        # Items haben 4-Space-Indent ('    - {"..."')
        if s.startswith("    "):
            continue
        # Sonst: 2-Space-Indent (router_settings-Nachbar) oder 0-Space (top-level)
        block_end = i
        break

    # Bestehende Keys parsen
    existing_keys: set[str] = set()
    for i in range(fallbacks_idx + 1, block_end):
        # Pattern: - {"<key>": ...}
        m = re.search(r'\{"([^"]+)":', new_lines[i])
        if m:
            existing_keys.add(m.group(1))

    # Neue Zeilen vor block_end einfuegen
    insertions: list[str] = []
    for mn in sorted(new_model_names):
        if mn in existing_keys:
            continue
        n_prov = len(adds_by_model.get(mn, []))
        chain = [c for c in fallback_pool if c != mn][:4]
        chain_str = ", ".join(f'"{c}"' for c in chain)
        insertions.append(f'    - {{"{mn}": [{chain_str}]}}\n')
        # Catch-All '*' nur bei >= 4 Providern
        if n_prov >= 4 and "*" not in existing_keys:
            existing_keys.add("*")
            insertions.append(
                '    - {"*": ["llama-3.1-8b", "gpt-oss-20b", '
                '"gemma-3-12b-it", "deepseek-v4-flash", "openrouter-free"]}\n'
            )
        added += 1

    if insertions:
        new_lines[block_end:block_end] = insertions
    return new_lines, added


def regenerate_multi_instance() -> bool:
    """
    Ruft multi-instance/generate-config.py auf, falls vorhanden.
    Liefert True bei Erfolg.
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
        print(f"  [WARN] multi-instance Regenerierung fehlgeschlagen: {exc}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def collect_models(env: dict[str, str]) -> tuple[dict[str, list[str]], list[tuple[str, str]]]:
    raw: dict[str, list[str]] = {}
    errors: list[tuple[str, str]] = []
    for name, fn in PROVIDERS.items():
        needed = required_env(name)
        if any(not env.get(v) for v in needed):
            errors.append((name, "Key fehlt: " + ", ".join(needed) or "(keiner)"))
            continue
        try:
            models = fn(env)
            raw[name] = models
            print(f"  [OK]   {name:14s} {len(models):4d} Modelle")
        except Exception as exc:
            errors.append((name, f"{type(exc).__name__}: {exc}"))
            print(f"  [FAIL] {name:14s} {type(exc).__name__}: {exc}")
        time.sleep(0.2)
    return raw, errors


def build_groups(raw: dict[str, list[str]]) -> dict[str, dict[str, list[str]]]:
    """
    Liefert pro normalisiertem Namen: { provider: [originale Namen] }.
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
    Zen-Modelle: Gruppe aufnehmen sobald sie bei einem Provider vorkommen.
    Andere Provider werden inkludiert wenn sie das gleiche normalisierte Modell fuehren.
    """
    out: dict[str, dict[str, list[str]]] = {}
    groups = build_groups(raw)
    for zen in ZEN_MODEL_NAMES:
        zen_norm = normalize(zen)
        # Korrekte Kandidatenwahl: exakter normalized match, oder
        # Substring-Match nur an '-' Boundary, damit z.B. "big-pickle" nicht
        # fälschlich "big-pickle-extra" aufnimmt.
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


def write_report(
    path: Path,
    raw: dict[str, list[str]],
    errors: list[tuple[str, str]],
    groups: dict[str, dict[str, list[str]]],
    zen_groups: dict[str, dict[str, list[str]]],
    pricing: dict[str, dict] | None = None,
    pricing_status: str = "deaktiviert",
    plan: list[dict] | None = None,
) -> None:
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("LiteLLM Free-Models – Provider-Overlap Report")
    lines.append("Erstellt: " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
    lines.append("=" * 78)
    lines.append("")

    lines.append("─" * 78)
    lines.append("Abgefragte Provider")
    lines.append("─" * 78)
    for name in PROVIDERS:
        count = len(raw.get(name, []))
        if name in raw:
            lines.append(f"  [+] {name:14s} {count:4d} Modelle")
        else:
            msg = next((e for n, e in errors if n == name), "unbekannt")
            lines.append(f"  [-] {name:14s} FEHLER: {msg}")
    lines.append("")

    lines.append("─" * 78)
    lines.append(f"Modelle mit >= 2 Providern ({len(groups)} Eintraege)")
    lines.append("─" * 78)
    if not groups:
        lines.append("  (keine)")
    for norm in sorted(groups, key=lambda k: (-len(groups[k]), k)):
        providers = groups[norm]
        marker = " [ZEN]" if norm in {normalize(z) for z in ZEN_MODEL_NAMES} else ""
        lines.append(f"\n  Modell: {norm}{marker}")
        lines.append(f"  Provider: {len(providers)}")
        for p in sorted(providers):
            origs = ", ".join(sorted(set(providers[p])))
            lines.append(f"    - {p:14s} {origs}")
    lines.append("")

    lines.append("─" * 78)
    lines.append("Zen-Modelle (immer enthalten, hohe Nutzungslimits)")
    lines.append("─" * 78)
    for zen in sorted(ZEN_MODEL_NAMES):
        zen_norm = normalize(zen)
        match = zen_groups.get(zen_norm) or {}
        if match:
            lines.append(f"\n  {zen}  (normalisiert: {zen_norm})")
            for p in sorted(match):
                lines.append(f"    - {p}: {', '.join(sorted(set(match[p])))}")
        else:
            lines.append(f"\n  {zen}  (normalisiert: {zen_norm})")
            lines.append("    - nicht in der Live-Abfrage gefunden")
    lines.append("")

    lines.append("─" * 78)
    lines.append("Provider-Kombinationen mit >= 2 gemeinsamen Modellen")
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
        lines.append("  (keine Paare mit >= 2 gemeinsamen Modellen)")
    for (a, b), count, models in rows:
        lines.append(f"\n  {a}  <->  {b}   ({count} gemeinsame Modelle)")
        for m in sorted(models):
            tag = " [ZEN]" if m in {normalize(z) for z in ZEN_MODEL_NAMES} else ""
            lines.append(f"      - {m}{tag}")
    lines.append("")

    # ------------------------------------------------------------------
    # Kosten & Ersparnis
    # ------------------------------------------------------------------
    lines.append("─" * 78)
    lines.append("Kosten & Ersparnis (hypothetischer Paid-Tier-Preis)")
    lines.append("─" * 78)
    lines.append(f"  Quelle: {pricing_status}")
    if not pricing:
        lines.append("  (deaktiviert -- mit aktivem Pricing-Download erneut ausfuehren)")
    else:
        # 1) Pro gemeinsamem Modell: was wuerde jeder Provider kosten?
        lines.append("")
        lines.append("  Pro gemeinsamem Modell, pro Provider (Preis in USD pro 1M Tokens):")
        lines.append("")
        header = f"  {'Modell':40s}  {'Provider':14s}  {'Input':>12s}  {'Output':>12s}  {'DB-Key'}"
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))
        any_cost_row = False
        # Kombiniere groups + zen_groups (beide normalisiert)
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
                # kuerzester DB-Key als Anzeige (einer reicht)
                lines.append(
                    f"  {norm[:38]+tag:40s}  {provider:14s}  {in_str:>12s}  {out_str:>12s}  {db_keys[0]}"
                )
        if not any_cost_row:
            lines.append("  (keine Paid-Preise in der DB fuer die gelisteten Modelle gefunden)")

        # 2) Pro-Provider-Summe: was haette der Free-Tier-Proxy pro 1M Tokens
        #    hypothetisch gekostet, wenn man direkt bei jedem Provider waere?
        #    Annahme: je 0.5M Input + 0.5M Output pro 1M Tokens.
        lines.append("")
        lines.append("  Hypothetische Provider-Kosten pro 1M Tokens (Mix: 500K Input + 500K Output):")
        lines.append("")
        lines.append(f"  {'Provider':14s}  {'Mix-Kosten':>14s}  {'Anzahl Modelle':>15s}")
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

        # 3) Top-5 Sparpotenzial-Modelle
        lines.append("")
        lines.append("  Top 5 Sparpotenzial (teuerster Paid-Preis pro Modell):")
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
            lines.append(f"  - {norm+tag:42s} waere ~${cost:.2f}/M auf {prov}")
        if not savings:
            lines.append("  (keine Paid-Preise ermittelt)")

    # ------------------------------------------------------------------
    # Apply-Plan (Diff-Vorschau fuer --apply)
    # ------------------------------------------------------------------
    if plan is not None:
        lines.append("")
        lines.append("─" * 78)
        lines.append("Apply-Plan (Vorschau; mit --apply wird das in config.yaml geschrieben)")
        lines.append("─" * 78)
        adds = [p for p in plan if p["action"] == "add"]
        skips = [p for p in plan if p["action"] == "skip"]
        lines.append(f"  Neue Deployments: {len(adds)}")
        lines.append(f"  Bereits vorhanden (skip): {len(skips)}")
        if adds:
            lines.append("")
            by_model: dict[str, list[dict]] = {}
            for p in adds:
                by_model.setdefault(p["model_name"], []).append(p)
            for mn in sorted(by_model):
                lines.append(f"  + {mn}  ({len(by_model[mn])} neue Provider)")
                for p in by_model[mn]:
                    ic_s = fmt_cost(p["ic"])
                    oc_s = fmt_cost(p["oc"])
                    lines.append(
                        f"      {p['provider']:14s}  {p['model_id']:48s}  "
                        f"in={ic_s:>12s}  out={oc_s:>12s}"
                    )
        if not adds and not skips:
            lines.append("  (kein Plan -- eventuell config.yaml fehlt)")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    global PRICING_CACHE, PRICING_URL
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--env", type=Path, default=DEFAULT_ENV, help="Pfad zur .env-Datei")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output-Datei")
    ap.add_argument("--no-pricing", action="store_true",
                    help="Preis-Download ueberspringen (kein Kosten-Report)")
    ap.add_argument("--refresh-pricing", action="store_true",
                    help="Preis-Cache ignorieren und neu von GitHub laden")
    ap.add_argument("--pricing-url", default=PRICING_URL,
                    help=f"Alternative URL fuer model_prices_and_context_window.json "
                         f"(default: GitHub raw)")
    ap.add_argument("--pricing-cache", type=Path, default=PRICING_CACHE,
                    help="Lokaler Cache-Pfad fuer die Preis-DB")
    ap.add_argument("--config", type=Path,
                    default=REPO_ROOT / "config.yaml",
                    help="Fallback-Pfad zu config.yaml. Wird nur genutzt wenn "
                         "kein config.template.yaml existiert (alter Stand ohne "
                         "Template-Pipeline).")
    ap.add_argument("--template", type=Path,
                    default=REPO_ROOT / "config.template.yaml",
                    help="Pfad zu config.template.yaml (Single Source of Truth). "
                         "Wenn vorhanden, schreibt --apply ins Template und ruft "
                         "render-config.py danach auf.")
    ap.add_argument("--apply", action="store_true",
                    help="Aenderungen in config.template.yaml schreiben (Single "
                         "Source of Truth) und via render-config.py nach "
                         "config.yaml rendern (default: nur Diff im Report)")
    ap.add_argument("--regen-multi-instance", action="store_true",
                    help="Nach --apply multi-instance/generate-config.py ausfuehren")
    args = ap.parse_args()

    env = load_env(args.env)
    if not env:
        print(f"FEHLER: {args.env} nicht gefunden oder leer.", file=sys.stderr)
        return 2

    print(f"Lade .env aus {args.env}")
    print(f"Abfrage laeuft...\n")
    raw, errors = collect_models(env)
    print()

    groups = build_groups(raw)
    zen_groups = find_zen_groups(raw)

    pricing: dict[str, dict] | None = None
    pricing_status = "deaktiviert"
    if not args.no_pricing:
        # Cache-Pfad zur Laufzeit patchen (ermoeglicht --pricing-cache Override)
        PRICING_CACHE = args.pricing_cache
        PRICING_CACHE.parent.mkdir(parents=True, exist_ok=True)
        url = args.pricing_url
        try:
            # Bei Refresh muss der Pricing-Index neu gebaut werden, sonst
            # verweist er noch auf die alte DB.
            if args.refresh_pricing:
                _reset_pricing_index()
            pricing = load_pricing(force_refresh=args.refresh_pricing)
            cache_age = "live"
            if PRICING_CACHE.exists():
                age_s = time.time() - PRICING_CACHE.stat().st_mtime
                if age_s < 60:
                    cache_age = "live (<1 min alt)"
                elif age_s < PRICING_TTL_SECONDS:
                    cache_age = f"Cache ({int(age_s // 3600)}h {int(age_s % 3600 // 60)}m alt)"
                else:
                    cache_age = f"Cache (abgelaufen, {int(age_s // 3600)}h)"
            pricing_status = (
                f"{url}  |  {cache_age}  |  "
                f"{len([k for k in pricing if k != 'sample_spec'])} Modelleintraege"
            )
            print(f"Preis-DB: {pricing_status}")
        except Exception as exc:
            print(f"  [WARN] Pricing-Download fehlgeschlagen: {exc}", file=sys.stderr)
            pricing = None
            pricing_status = f"fehlgeschlagen ({exc})"

    # Apply-Plan (nur wenn config oder template existiert; sonst nur Report).
    # Template hat Vorrang, weil es Single Source of Truth ist.
    plan: list[dict] = []
    target_for_apply: Path | None = None
    is_template = False
    if args.template.exists():
        target_for_apply = args.template
        is_template = True
        _, _, _, existing = parse_config(args.template)
        plan = generate_apply_plan(groups, zen_groups, existing, pricing)
        print(f"\nApply-Plan (Template): {len([p for p in plan if p['action'] == 'add'])} "
              f"neue Deployments, {len([p for p in plan if p['action'] == 'skip'])} bereits vorhanden")
    elif args.config.exists():
        target_for_apply = args.config
        _, _, _, existing = parse_config(args.config)
        plan = generate_apply_plan(groups, zen_groups, existing, pricing)
        print(f"\nApply-Plan (config.yaml): {len([p for p in plan if p['action'] == 'add'])} "
              f"neue Deployments, {len([p for p in plan if p['action'] == 'skip'])} bereits vorhanden")
    else:
        print(f"\n  [WARN] weder {args.template} noch {args.config} gefunden, "
              "Apply-Plan uebersprungen.", file=sys.stderr)

    write_report(args.output, raw, errors, groups, zen_groups, pricing, pricing_status, plan)
    print(f"\nReport geschrieben nach: {args.output}")

    if args.apply and plan and target_for_apply is not None:
        any_adds = any(p["action"] == "add" for p in plan)
        if not any_adds:
            print("\nKeine neuen Deployments, config.yaml bleibt unveraendert.")
            return 0
        print("\n" + "=" * 78)
        if is_template:
            print(f"APPLY -- schreibe Aenderungen ins Template {args.template}")
        else:
            print(f"APPLY -- schreibe Aenderungen nach {args.config}")
        print("=" * 78)
        print(render_plan_diff(plan))
        added, costs, fallbacks = apply_to_config(
            target_for_apply, plan, groups, zen_groups, pricing,
        )
        print(f"\n  Deployments hinzugefuegt: {added}")
        print(f"  Kosten aktualisiert:      {costs}")
        print(f"  Fallbacks ergaenzt:       {fallbacks}")
        if is_template:
            print("\n  Rendere config.template.yaml -> config.yaml via render-config.py ...")
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
                print(f"  [WARN] {render_script} fehlt, ueberspringe Render.", file=sys.stderr)
        if args.regen_multi_instance:
            print("\n  Regeneriere multi-instance/ ...")
            regenerate_multi_instance()
        print(f"\nFertig. Backup unter {target_for_apply}.bak.*")
        return 0
    elif not args.apply and plan:
        if is_template:
            print(f"\nTipp: mit --apply werden die {len([p for p in plan if p['action'] == 'add'])} "
                  "neuen Deployments in config.template.yaml geschrieben und "
                  "anschliessend via render-config.py in config.yaml gerendert.")
        else:
            print(f"\nTipp: mit --apply werden die {len([p for p in plan if p['action'] == 'add'])} "
                  "neuen Deployments in config.yaml geschrieben.")
        if plan:
            print("\n  Diff-Vorschau:")
            print(render_plan_diff(plan))
    return 0


if __name__ == "__main__":
    sys.exit(main())
