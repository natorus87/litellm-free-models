#!/usr/bin/env python3
"""
Renders config.template.yaml into config.yaml.

  1. Reads .env and substitutes {{ENV_VAR}} placeholders in the template.
  2. Filters out provider deployments whose API key is missing (except for
     the anonymous free tier like OVHcloud).
  3. Removes the Redis blocks (cache + router tracking, marked with
     `# BEGIN REDIS ...` / `# END REDIS ...`) if REDIS_HOST is missing/empty
     or --no-redis was passed.
  4. If OPENROUTER_API_KEY is set, appends `openrouter-free` to every
     fallback chain and to the catch-all `*`.
  5. Removes fallback entries AND chain targets that point to model_names
     that no longer exist.
  6. Writes config.yaml atomically with a .bak.<timestamp> backup of the
     previous version (at most BACKUP_KEEP backups are kept).

Usage:
    python3 render-config.py
    python3 render-config.py --env .env --template config.template.yaml
    python3 render-config.py --dry-run   # stdout only, no writes
    python3 render-config.py --no-redis  # render without cache/router Redis
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

from providers_config import PROVIDERS

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_ENV = REPO_ROOT / ".env"
DEFAULT_TEMPLATE = REPO_ROOT / "config.template.yaml"
DEFAULT_OUTPUT = REPO_ROOT / "config.yaml"

# Maximum number of lines to search backwards for a block header before a
# deployment entry. Actual need in the current template is 3-4 header
# lines; 12 is generously sized to stay robust for future additions too.
MAX_HEADER_LINES = 12

# Number of config.yaml.bak.<timestamp> backups kept when rendering;
# older ones get deleted.
BACKUP_KEEP = 5

# model_names that deliberately have only one provider (documented
# exceptions to the >= 2-provider rule) -- NO warning is emitted for these.
SINGLE_PROVIDER_ALLOWED = {"big-pickle", "north-mini-code", "openrouter-free"}


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


def _provider_from_block(model_id: str, api_base: str) -> str:
    """
    Derives the internal provider name from (model, api_base).

    Discrimination is necessary because several providers use the
    'openai' prefix:
      - NVIDIA:        'openai/<vendor>/<model>' with the NVIDIA API base
      - GitHub Models: 'openai/<ModelName>' (e.g. 'openai/Meta-Llama-...')
                       with the Azure API base
      - OVHcloud:      'openai/<ModelName>' with the OVHcloud API base
      - OpenCode Zen:  'openai/<model>' with the opencode.ai base
      - LLM7.io:       'openai/<model>' with the llm7.io base

    If `model:` alone isn't unambiguous, `api_base` is used as a secondary
    discriminator.

    Examples:
      openrouter/openai/gpt-oss-120b:free         -> openrouter
      cerebras/gpt-oss-120b                       -> cerebras
      openai/openai/gpt-oss-120b                  -> nvidia
      openai/Meta-Llama-3.3-70B + github base     -> github
      openai/Meta-Llama-3.3-70B + ovhcloud base    -> ovhcloud
      openai/big-pickle + opencode base           -> opencode-zen
    """
    if "/" not in model_id:
        return ""
    parts = model_id.split("/", 2)
    prefix = parts[0]
    if prefix != "openai":
        for name, prov in PROVIDERS.items():
            if prov.prefix == prefix:
                return name
        return ""

    # OpenAI-compatible. First try via vendor:
    vendor = parts[1] if len(parts) >= 2 else ""
    if vendor == "openai":
        return "nvidia"
    if vendor and vendor in PROVIDERS:
        return vendor

    # No unambiguous vendor. Discriminate via api_base.
    # We match any OpenAI provider whose api_base_static appears in the
    # block (substring, since api_base may or may not have a trailing slash).
    if api_base and not api_base.startswith("{{"):
        candidates: list[tuple[int, str]] = []
        for name, prov in PROVIDERS.items():
            if prov.prefix != "openai" or not prov.api_base_static:
                continue
            if prov.api_base_static in api_base:
                # Longer api_base URL = more specific (e.g. with a path)
                candidates.append((len(prov.api_base_static), name))
        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][1]

    # Last resort: first OpenAI provider without vendor_in_path
    for name, prov in PROVIDERS.items():
        if prov.prefix == "openai" and not prov.vendor_in_path:
            return name
    return ""


def parse_blocks(lines: list[str]) -> tuple[int, int, list[dict]]:
    """
    Returns (model_list_start, model_list_end, [deployment block]).
    A block = one - model_name: entry with all following lines up to the
    next - model_name: or a line with less than 2-space indent.
    """
    ml_start = -1
    for i, line in enumerate(lines):
        if line.rstrip() == "model_list:" and not line.startswith(" "):
            ml_start = i
            break
    if ml_start < 0:
        raise RuntimeError("model_list not found")

    ml_end = len(lines)
    for i in range(ml_start + 1, len(lines)):
        s = lines[i].strip()
        if s and not lines[i].startswith(" "):
            ml_end = i
            break

    def _finalize(block: dict) -> dict:
        if block.get("model_id"):
            block["provider"] = _provider_from_block(
                block["model_id"], block.get("api_base", "")
            )
        return block

    blocks: list[dict] = []
    current: dict | None = None
    for i in range(ml_start + 1, ml_end):
        s = lines[i].lstrip()
        if s.startswith("- model_name:"):
            if current is not None:
                current["end"] = i - 1
                _finalize(current)
                blocks.append(current)
            current = {
                "start": i,
                "end": i,  # set at the end
                "lines": [lines[i]],
                "model_name": s.split("- model_name:", 1)[1].strip(),
                "provider": "",
                "model_id": "",
                "api_base": "",
            }
        elif current is not None:
            # Block ends before a line with < 2-space indent (top-level key)
            if lines[i] and not lines[i].startswith("  "):
                current["end"] = i - 1
                _finalize(current)
                blocks.append(current)
                current = None
                continue
            current["lines"].append(lines[i])
            stripped = lines[i].strip()
            if stripped.startswith("model:") and " " in stripped and not current["model_id"]:
                # 'model: <prefix>/...' from the first matching line
                mid = stripped.split("model:", 1)[1].strip()
                current["model_id"] = mid
            elif stripped.startswith("api_base:") and " " in stripped and not current["api_base"]:
                current["api_base"] = stripped.split("api_base:", 1)[1].strip()
    if current is not None:
        current["end"] = len(lines) - 1
        _finalize(current)
        blocks.append(current)

    return ml_start, ml_end, blocks


def filter_blocks(blocks: list[dict], env: dict[str, str]) -> tuple[list[dict], list[str]]:
    """
    Removes blocks whose API key is missing.
    Returns (filtered blocks, list of removed provider keys).
    """
    kept: list[dict] = []
    removed: list[str] = []
    for b in blocks:
        provider = b["provider"]
        if not provider:
            kept.append(b)
            continue
        prov = PROVIDERS.get(provider)
        if prov is None:
            kept.append(b)
            continue
        if prov.required:
            env_var = prov.env_var
            if not env.get(env_var):
                removed.append(f"{provider} (no {env_var})")
                continue
        kept.append(b)
    return kept, removed


def substitute_placeholders(text: str, env: dict[str, str]) -> tuple[str, list[str]]:
    """
    Replaces {{VAR}} with env[VAR] (or "" if not set).
    Returns (new_text, list_of_still_missing_placeholders).
    """
    missing: list[str] = []

    def repl(m: re.Match) -> str:
        var = m.group(1)
        if var not in env:
            missing.append(var)
            return ""
        return env[var]

    return re.sub(r"\{\{([A-Z_][A-Z0-9_]*)\}\}", repl, text), missing


def single_deployment_warnings(kept_blocks: list[dict]) -> list[str]:
    """
    Returns the model_names that have only ONE deployment left after the
    provider filter (excluding the documented single-provider exceptions).
    The >= 2-provider rule only applies to the template -- if API keys are
    missing, a model can end up standing on one leg at runtime: if the
    last remaining provider fails (rate limit, downtime), only the
    fallback chain is left to carry the load.
    """
    counts: dict[str, int] = {}
    for b in kept_blocks:
        counts[b["model_name"]] = counts.get(b["model_name"], 0) + 1
    return sorted(
        mn for mn, c in counts.items()
        if c == 1 and mn not in SINGLE_PROVIDER_ALLOWED
    )


def strip_redis_blocks(lines: list[str], redis_active: bool) -> list[str]:
    """
    Processes the blocks marked with `# BEGIN REDIS ...` / `# END REDIS ...`
    (cache in litellm_settings, Redis tracking in router_settings):

    - redis_active=True:  only remove the marker lines, content stays.
    - redis_active=False: remove markers AND content -- the proxy then runs
      without Redis instead of degrading against an unreachable Redis
      (connection-error spam on every request).
    """
    new_lines: list[str] = []
    in_block = False
    for line in lines:
        s = line.strip()
        if s.startswith("# BEGIN REDIS"):
            in_block = True
            continue
        if s.startswith("# END REDIS"):
            in_block = False
            continue
        if in_block and not redis_active:
            continue
        new_lines.append(line)
    return new_lines


def update_fallbacks(
    lines: list[str],
    ml_end: int,
    openrouter_active: bool,
    valid_model_names: set[str] | None = None,
) -> list[str]:
    """
    - If OPENROUTER_API_KEY is set: append 'openrouter-free' to every
      fallback chain and to the catch-all '*' (idempotent).
    - If OPENROUTER_API_KEY is missing: remove 'openrouter-free' from all
      fallback chains, so LiteLLM doesn't try to make an OpenRouter call
      without a key.
    - Chain TARGETS that are no longer an existing model_name get removed
      (in both fallbacks AND context_window_fallbacks) -- otherwise a
      fallback would point at a model with zero deployments.
    """
    new_lines = list(lines)

    in_fallbacks = False
    in_ctx = False
    for i, line in enumerate(new_lines):
        s = line.strip()
        if s == "fallbacks:":
            in_fallbacks = True
            in_ctx = False
            continue
        if s == "context_window_fallbacks:":
            in_fallbacks = False
            in_ctx = True
            continue
        if in_fallbacks and s and not line.startswith("  ") and not line.startswith("    "):
            in_fallbacks = False
        if in_ctx and s and not line.startswith("  ") and not line.startswith("    "):
            in_ctx = False
        if not in_fallbacks and not in_ctx:
            continue
        m = re.match(r'\s*-\s*\{"([^"]+)":\s*\[(.*?)\]\}\s*$', line)
        if not m:
            continue
        chain_str = m.group(2)
        items = [x.strip().strip('"') for x in chain_str.split(",") if x.strip().strip('"')]

        if valid_model_names is not None:
            items = [x for x in items if x in valid_model_names]

        if in_fallbacks:
            if openrouter_active:
                if "openrouter-free" not in items and (
                    valid_model_names is None or "openrouter-free" in valid_model_names
                ):
                    items.append("openrouter-free")
            else:
                if "openrouter-free" in items:
                    items = [x for x in items if x != "openrouter-free"]

        if not items:
            # Chain is empty, delete the line
            new_lines[i] = ""
            continue
        new_chain = ", ".join(f'"{x}"' for x in items)
        new_lines[i] = re.sub(
            r'\["[^\]]*"\]',
            f'[{new_chain}]',
            line,
        )
    return new_lines


def remove_orphaned_fallbacks(
    lines: list[str],
    valid_model_names: set[str],
) -> list[str]:
    """
    Removes fallback entries that point to model_names that no longer
    exist in model_list.
    """
    new_lines: list[str] = []
    in_fallbacks = False
    in_ctx = False
    for line in lines:
        s = line.strip()
        if s == "fallbacks:":
            in_fallbacks = True
            in_ctx = False
            new_lines.append(line)
            continue
        if s == "context_window_fallbacks:":
            in_fallbacks = False
            in_ctx = True
            new_lines.append(line)
            continue
        if (in_fallbacks or in_ctx) and s and not line.startswith("  ") and not line.startswith("    "):
            in_fallbacks = False
            in_ctx = False
        if in_fallbacks or in_ctx:
            m = re.match(r'\s*-\s*\{"([^"]+)":\s*\[(.*?)\]\}\s*$', line)
            if m:
                key = m.group(1)
                if key != "*" and key not in valid_model_names:
                    continue  # orphaned, skip
        new_lines.append(line)
    return new_lines


def render(
    template_path: Path,
    env_path: Path,
    output_path: Path,
    dry_run: bool = False,
    no_redis: bool = False,
) -> int:
    if not template_path.exists():
        print(f"ERROR: template not found: {template_path}", file=sys.stderr)
        return 2
    if not env_path.exists():
        print(f"ERROR: .env not found: {env_path}", file=sys.stderr)
        return 2

    env = load_env(env_path)
    text = template_path.read_text(encoding="utf-8")

    # 1) Substitute placeholders
    text, missing = substitute_placeholders(text, env)
    if missing:
        # OK for OVHcloud etc.; for others the block filter should catch it
        pass

    lines = text.splitlines(keepends=True)

    # 1b) Conditionally strip the Redis blocks (cache + router tracking)
    redis_active = bool(env.get("REDIS_HOST")) and not no_redis
    lines = strip_redis_blocks(lines, redis_active)
    if redis_active:
        print("REDIS_HOST set -> Redis cache + router tracking active.")
    else:
        print("No REDIS_HOST (or --no-redis) -> Redis blocks removed "
              "(proxy runs without cache/cross-instance tracking).")

    # 2) Parse + filter blocks
    ml_start, ml_end, blocks = parse_blocks(lines)
    kept, removed = filter_blocks(blocks, env)

    valid_names = {b["model_name"] for b in kept}

    if removed:
        print(f"Removed provider deployments (no API key): {len(removed)}")
        for r in removed:
            print(f"  - {r}")

    # 3) Strip removed blocks (incl. header comments before them)
    new_lines = list(lines)
    removed_indices: set[int] = set()
    for b in blocks:
        if b in kept:
            continue
        # Header comment: lines with 2-space indent that contain '#',
        # directly before the block. Search at most MAX_HEADER_LINES lines
        # backwards.
        header_start = b["start"]
        for j in range(b["start"] - 1, max(b["start"] - MAX_HEADER_LINES, ml_start), -1):
            line = new_lines[j]
            if line is None:
                continue
            stripped = line.strip()
            if not stripped:
                continue  # blank line, not part of the header
            if stripped.startswith("#") and line.startswith("  "):
                header_start = j
            else:
                break
        for j in range(header_start, b["end"] + 1):
            removed_indices.add(j)
    new_lines = [ln for i, ln in enumerate(new_lines) if i not in removed_indices]

    # 4) Recompute ml_end (indices shifted because blocks were removed).
    #    Search again for 'model_list:' and the first top-level key after it.
    new_ml_start = -1
    for i, line in enumerate(new_lines):
        if line.rstrip() == "model_list:" and not line.startswith(" "):
            new_ml_start = i
            break
    new_ml_end = len(new_lines)
    for i in range(new_ml_start + 1, len(new_lines)):
        s = new_lines[i].strip()
        if s and not new_lines[i].startswith(" "):
            new_ml_end = i
            break

    # 5) Clean up fallback chains + add openrouter-free
    #    (remove_orphaned_fallbacks: orphaned KEYS; update_fallbacks:
    #     orphaned TARGETS + openrouter-free on/off)
    new_lines = remove_orphaned_fallbacks(new_lines, valid_names)
    openrouter_active = bool(env.get("OPENROUTER_API_KEY"))
    new_lines = update_fallbacks(
        new_lines, new_ml_end, openrouter_active, valid_model_names=valid_names
    )

    # 6) Print the valid model_names list
    print(f"Kept deployments: {len(kept)}")
    print(f"Available model_names: {len(valid_names)}")

    singles = single_deployment_warnings(kept)
    if singles:
        print(f"WARNING: {len(singles)} model_name(s) have only 1 deployment "
              f"left after the provider filter (no provider redundancy; "
              f"if it fails, only the fallback chain carries the load):")
        for mn in singles:
            print(f"  ! {mn}")
        print("  -> Add the missing API key(s) to .env to restore "
              "redundancy (see .env.example).")
    if openrouter_active:
        print("OPENROUTER_API_KEY set -> 'openrouter-free' is appended to all fallback chains.")
    else:
        print("OPENROUTER_API_KEY missing -> 'openrouter-free' is NOT added as a fallback.")

    if dry_run:
        print("\n--- DRY RUN: first 40 lines of the generated config.yaml ---")
        for ln in new_lines[:40]:
            print(ln, end="")
        print("---")
        return 0

    # Replace the header: the template warning block ("THIS FILE IS THE
    # SINGLE SOURCE OF TRUTH") shouldn't end up in the rendered config.yaml.
    rendered = "".join(new_lines)
    rendered = re.sub(
        r"^# =+\n# LiteLLM Proxy Configuration.*?# =+\n# THIS FILE.*?# =+\n",
        ("# =============================================================================\n"
         "# LiteLLM Proxy Configuration – Free Models Only\n"
         "# =============================================================================\n"
         "# RENDERED from config.template.yaml via render-config.py.\n"
         "# Direct edits to config.yaml are overwritten on the next render.\n"
         "# =============================================================================\n"),
        rendered,
        count=1,
        flags=re.DOTALL | re.MULTILINE,
    )

    # 7) Backup the OLD version (if any), then atomic write: write to tmp
    #    first, then os.replace() (atomic on POSIX).
    if output_path.exists():
        backup = output_path.with_suffix(output_path.suffix + f".bak.{int(time.time())}")
        import shutil
        shutil.copy2(output_path, backup)
        print(f"Backup: {backup}")

    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp.write_text(rendered, encoding="utf-8")
    os.replace(tmp, output_path)

    prune_backups(output_path)

    print(f"config.yaml written: {output_path} ({rendered.count(chr(10))} lines)")
    return 0


def prune_backups(output_path: Path, keep: int = BACKUP_KEEP) -> None:
    """Deletes old <output>.bak.<timestamp> backups, keeping the last `keep`."""
    pattern = output_path.name + ".bak.*"
    backups = sorted(
        output_path.parent.glob(pattern),
        key=lambda p: p.name,
    )
    for old in backups[:-keep] if keep else backups:
        try:
            old.unlink()
            print(f"Old backup removed: {old.name}")
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--env", type=Path, default=DEFAULT_ENV)
    ap.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--dry-run", action="store_true",
                    help="Only show the diff/preview, don't write")
    ap.add_argument("--no-redis", action="store_true",
                    help="Remove Redis blocks (cache + router tracking), "
                         "even if REDIS_HOST is set (for standalone runs "
                         "without Redis, e.g. make check-config)")
    args = ap.parse_args()
    return render(args.template, args.env, args.output,
                  dry_run=args.dry_run, no_redis=args.no_redis)


if __name__ == "__main__":
    sys.exit(main())
