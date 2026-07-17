#!/usr/bin/env python3
"""
Generates/extends an OpenCode config (~/.config/opencode/opencode.json)
with a provider entry for this LiteLLM proxy.

Writes ONLY that one provider key (default: "litellm") -- every other
provider and top-level field in the target file is left untouched. The
provider block is built schema-compliant per
https://opencode.ai/config.json (apiKey/baseURL/timeout/chunkTimeout
belong under "options", not at the top level -- existing configs
sometimes got that wrong).

Model list:
  - Default: queried live from this proxy via GET /models (exactly
    mirrors what's servable with the currently-set .env keys).
  - Fallback (--from-template, or if the proxy isn't reachable): parsed
    from config.template.yaml (may include models that aren't actually
    available without the matching API key).

Idempotent and safe to re-run: creates a timestamped backup of the
previous opencode.json before every write (the last 5 are kept), supports
--dry-run to preview without writing.

Usage:
    python3 opencode-config.py                       # localhost:4444, writes
    python3 opencode-config.py --dry-run              # preview only
    python3 opencode-config.py --host 10.11.13.93     # different host
    python3 opencode-config.py --from-template         # without a live query
    python3 opencode-config.py --output /path/to/opencode.json
    make opencode-config
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_ENV = REPO_ROOT / ".env"
DEFAULT_TEMPLATE = REPO_ROOT / "config.template.yaml"
DEFAULT_OUTPUT = Path.home() / ".config" / "opencode" / "opencode.json"

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 4444
DEFAULT_TIMEOUT_MS = 900_000       # 15 min -- full requests can take a
                                    # while with free-tier fallback chains
DEFAULT_CHUNK_TIMEOUT_MS = 120_000  # 2 min between SSE chunks
BACKUP_KEEP = 5


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


def fetch_live_models(base_url: str, api_key: str, timeout: int = 10) -> list[str] | None:
    """GET {base_url}/models. Returns None (instead of raising) if the
    proxy isn't reachable -- the caller then falls back to the template
    instead of aborting the whole script."""
    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return sorted({m["id"] for m in data.get("data", []) if m.get("id")})
    except (urllib.error.URLError, OSError, TimeoutError, ValueError, KeyError) as exc:
        print(f"  [WARN] Live query to {url} failed ({exc}) "
              "-- falling back to config.template.yaml.", file=sys.stderr)
        return None


def models_from_template(template_path: Path) -> list[str]:
    """Parses model_names directly from config.template.yaml (unfiltered --
    may include models whose provider key is missing from .env)."""
    text = template_path.read_text(encoding="utf-8")
    names = sorted(set(re.findall(r"^\s*-\s*model_name:\s*(\S+)\s*$", text, re.MULTILINE)))
    return names


def build_provider_block(
    base_url: str,
    api_key: str,
    models: list[str],
    display_name: str,
    timeout_ms: int,
    chunk_timeout_ms: int,
) -> dict:
    return {
        "npm": "@ai-sdk/openai-compatible",
        "name": display_name,
        "options": {
            "baseURL": base_url,
            "apiKey": api_key,
            "timeout": timeout_ms,
            "chunkTimeout": chunk_timeout_ms,
        },
        "models": {m: {} for m in models},
    }


def load_opencode_config(path: Path) -> dict:
    if not path.exists():
        return {
            "$schema": "https://opencode.ai/config.json",
            "plugin": [],
            "provider": {},
        }
    return json.loads(path.read_text(encoding="utf-8"))


def prune_backups(path: Path, keep: int = BACKUP_KEEP) -> None:
    pattern = path.name + ".bak.*"
    backups = sorted(path.parent.glob(pattern), key=lambda p: p.name)
    for old in backups[:-keep] if keep else backups:
        try:
            old.unlink()
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--host", default=None,
                    help=f"Proxy host. Default: reuse the existing baseURL "
                         f"on update, otherwise {DEFAULT_HOST}")
    ap.add_argument("--port", type=int, default=None,
                    help=f"Proxy port. Default: reuse the existing baseURL "
                         f"on update, otherwise {DEFAULT_PORT}")
    ap.add_argument("--base-url", default=None,
                    help="Full base URL, overrides --host/--port "
                         "(e.g. http://10.11.13.93:4444/v1)")
    ap.add_argument("--api-key", default=None,
                    help="Master key. Default: LITELLM_MASTER_KEY from .env")
    ap.add_argument("--env", type=Path, default=DEFAULT_ENV)
    ap.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    ap.add_argument("--provider-id", default="litellm",
                    help="Key under 'provider' in opencode.json (default: litellm)")
    ap.add_argument("--name", default="Litellm-free-models",
                    help="Display name (default: Litellm-free-models)")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_MS,
                    help=f"Request timeout in ms (default: {DEFAULT_TIMEOUT_MS})")
    ap.add_argument("--chunk-timeout", type=int, default=DEFAULT_CHUNK_TIMEOUT_MS,
                    help=f"SSE chunk timeout in ms (default: {DEFAULT_CHUNK_TIMEOUT_MS})")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                    help=f"Target opencode.json (default: {DEFAULT_OUTPUT})")
    ap.add_argument("--from-template", action="store_true",
                    help="Use models from config.template.yaml instead of a "
                         "live query (e.g. when the proxy isn't running)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Only show what would be written, don't save")
    args = ap.parse_args()

    env = load_env(args.env)
    api_key = args.api_key or env.get("LITELLM_MASTER_KEY", "")
    if not api_key:
        print("ERROR: no API key. Set --api-key or maintain LITELLM_MASTER_KEY "
              f"in {args.env}.", file=sys.stderr)
        return 2

    config = load_opencode_config(args.output)
    config.setdefault("provider", {})
    existing_block = config["provider"].get(args.provider_id)
    existing_base_url = (existing_block or {}).get("options", {}).get("baseURL")

    # baseURL priority: explicit flags > existing value on update (prevents
    # a re-run from accidentally overwriting an already-working LAN address
    # with the local default) > default.
    if args.base_url:
        base_url = args.base_url
    elif args.host or args.port:
        base_url = f"http://{args.host or DEFAULT_HOST}:{args.port or DEFAULT_PORT}/v1"
    elif existing_base_url:
        base_url = existing_base_url
        print(f"Reusing the existing baseURL from {args.output}: {base_url}")
    else:
        base_url = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/v1"

    models: list[str] | None = None
    if not args.from_template:
        print(f"Querying live models: {base_url}/models ...")
        models = fetch_live_models(base_url, api_key)
    if models is None:
        if not args.template.exists():
            print(f"ERROR: {args.template} not found and a live query "
                  "isn't possible.", file=sys.stderr)
            return 2
        print(f"Reading models from {args.template} ...")
        models = models_from_template(args.template)

    print(f"{len(models)} models: {', '.join(models[:6])}"
          f"{', ...' if len(models) > 6 else ''}")

    provider_block = build_provider_block(
        base_url=base_url,
        api_key=api_key,
        models=models,
        display_name=args.name,
        timeout_ms=args.timeout,
        chunk_timeout_ms=args.chunk_timeout,
    )

    config["provider"][args.provider_id] = provider_block

    rendered = json.dumps(config, indent=2, ensure_ascii=False) + "\n"

    if args.dry_run:
        print(f"\n--- DRY RUN: provider.{args.provider_id} ---")
        print(json.dumps(provider_block, indent=2, ensure_ascii=False))
        if existing_block is not None and existing_block != provider_block:
            print(f"\n(Would replace the existing provider.{args.provider_id} block)")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        backup = args.output.with_suffix(
            args.output.suffix + f".bak.{int(time.time())}"
        )
        backup.write_text(args.output.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Backup: {backup}")
        prune_backups(args.output)

    tmp = args.output.with_suffix(args.output.suffix + ".tmp")
    tmp.write_text(rendered, encoding="utf-8")
    tmp.replace(args.output)

    action = "updated" if existing_block is not None else "created"
    print(f"\nprovider.{args.provider_id} {action} in {args.output} "
          f"({len(models)} models, baseURL={base_url}, "
          f"timeout={args.timeout}ms, chunkTimeout={args.chunk_timeout}ms).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
