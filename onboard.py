#!/usr/bin/env python3
"""
Interactive onboarding for the LiteLLM Free-Models Proxy.

Walks through the complete setup and is deliberately RE-RUNNABLE — also
for later changes (new API key, password rotation, re-render, restart):

  1. Create .env (from .env.example) or reuse an existing .env
  2. Generate base secrets (LITELLM_MASTER_KEY, REDIS_/POSTGRES_PASSWORD)
  3. Enter provider API keys interactively (with sign-up URLs and hints)
  4. Optional: test the keys LIVE against the provider catalogs
  5. Render config.yaml (including single-deployment warnings)
  6. Optional: start/restart the Docker Compose stack + readiness check

Usage:
    python3 onboard.py                    # interactive (recommended)
    python3 onboard.py --non-interactive  # only generate secrets + render
    make onboard

Standard library only, no dependencies (repo convention).
"""

from __future__ import annotations

import argparse
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
ENV_FILE = REPO_ROOT / ".env"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
PROXY_URL = "http://localhost:4444"

# Values that count as "not set" (placeholders from .env.example)
PLACEHOLDER_MARKERS = ("change-me", "change_me", "your-", "-here", "placeholder")

# (env_var, display name, sign-up URL, hint)
PROVIDER_KEYS: list[tuple[str, str, str, str]] = [
    ("OPENROUTER_API_KEY", "OpenRouter", "https://openrouter.ai/keys",
     "Most important key: enables the openrouter-free fallback in every chain."),
    ("CEREBRAS_API_KEY", "Cerebras", "https://cloud.cerebras.ai/", ""),
    ("GROQ_API_KEY", "Groq", "https://console.groq.com/keys", ""),
    ("CLOUDFLARE_API_KEY", "Cloudflare Workers AI",
     "https://dash.cloudflare.com/profile/api-tokens",
     "Also needs CLOUDFLARE_API_BASE (next entry)."),
    ("CLOUDFLARE_API_BASE", "Cloudflare API base",
     "https://developers.cloudflare.com/fundamentals/setup/find-account-and-zone-ids/",
     "Format: https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/v1"),
    ("GEMINI_API_KEY", "Google AI Studio", "https://aistudio.google.com/apikey",
     "Currently no active deployment (gemma-3 retired); only for future syncs."),
    ("NVIDIA_API_KEY", "NVIDIA NIM", "https://build.nvidia.com/",
     "Phone verification required; 40 RPM in return."),
    ("MISTRAL_API_KEY", "Mistral La Plateforme", "https://console.mistral.ai/", ""),
    ("COHERE_API_KEY", "Cohere", "https://dashboard.cohere.com/api-keys",
     "Trial key: 1000 calls/month."),
    ("GITHUB_TOKEN", "GitHub Models", "https://github.com/settings/tokens",
     "PAT with the models:read scope."),
    ("OPENCODE_ZEN_API_KEY", "OpenCode Zen", "https://opencode.ai/zen", ""),
    ("LLM7IO_API_KEY", "LLM7.io", "https://token.llm7.io",
     "'unused' = base free tier (2 RPM); free token = 40 RPM."),
    ("HF_TOKEN", "HuggingFace", "https://huggingface.co/settings/tokens", ""),
    ("OVHCLOUD_API_KEY", "OVHcloud", "https://www.ovhcloud.com/en/public-cloud/ai-endpoints/",
     "Leave empty = anonymous free tier (2 RPM/IP/model), perfectly fine."),
]

# Variables where "empty" is a valid, intentional state
EMPTY_IS_OK = {"OVHCLOUD_API_KEY", "GEMINI_API_KEY"}
# Variables with a valid non-key default
SPECIAL_DEFAULTS = {"LLM7IO_API_KEY": "unused"}


# ---------------------------------------------------------------------------
# .env handling (comment-preserving)
# ---------------------------------------------------------------------------

def read_env_lines() -> list[str]:
    return ENV_FILE.read_text(encoding="utf-8").splitlines()


def get_value(lines: list[str], key: str) -> str:
    for line in lines:
        s = line.strip()
        if s.startswith(f"{key}="):
            return s.partition("=")[2].strip().strip('"').strip("'")
    return ""


def set_value(lines: list[str], key: str, value: str) -> None:
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            return
    lines.append(f"{key}={value}")


def env_dict(lines: list[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def write_env(lines: list[str]) -> None:
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def is_placeholder(value: str) -> bool:
    low = value.lower()
    return any(m in low for m in PLACEHOLDER_MARKERS)


def key_state(value: str, var: str) -> str:
    """'ok' | 'empty' | 'placeholder' | 'default'"""
    if not value:
        return "empty"
    if is_placeholder(value):
        return "placeholder"
    if SPECIAL_DEFAULTS.get(var) == value:
        return "default"
    return "ok"


def mask(value: str) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return value[:2] + "…"
    return value[:6] + "…" + value[-2:]


# ---------------------------------------------------------------------------
# Interaction helpers
# ---------------------------------------------------------------------------

def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted. .env changes already written are kept.")
        sys.exit(130)
    return answer or default


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    answer = ask(f"{prompt} ({hint})").lower()
    if not answer:
        return default
    return answer in {"y", "yes", "j", "ja"}


def heading(text: str) -> None:
    print()
    print("─" * 74)
    print(f"  {text}")
    print("─" * 74)


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def step_env_file() -> list[str]:
    heading("Step 1/6 — .env")
    if ENV_FILE.exists():
        print(f"  Found an existing {ENV_FILE.name} — its values are reused,")
        print("  you can change them selectively in the next steps.")
    else:
        shutil.copy2(ENV_EXAMPLE, ENV_FILE)
        print(f"  Created {ENV_FILE.name} from {ENV_EXAMPLE.name}.")
    return read_env_lines()


def step_base_secrets(lines: list[str], interactive: bool) -> None:
    heading("Step 2/6 — Base secrets (master key & passwords)")
    specs = [
        ("LITELLM_MASTER_KEY", "sk-" + secrets.token_hex(24),
         "Auth token that clients send to the proxy"),
        ("REDIS_PASSWORD", secrets.token_hex(16),
         "Required: docker compose won't start without it"),
        ("POSTGRES_PASSWORD", secrets.token_hex(16),
         "Required: docker compose won't start without it"),
    ]
    for var, generated, why in specs:
        current = get_value(lines, var)
        if key_state(current, var) == "ok":
            print(f"  [OK] {var} is set ({mask(current)})")
            continue
        if interactive:
            print(f"\n  {var} — {why}")
            value = ask("  Enter your own value or press Enter to generate one securely")
            value = value or generated
        else:
            value = generated
        set_value(lines, var, value)
        print(f"  [NEW] {var} = {mask(value)}")


def step_provider_keys(lines: list[str]) -> None:
    heading("Step 3/6 — Provider API keys")
    print("  All keys are optional: providers without a key are simply")
    print("  dropped when rendering. More providers = more redundancy & rate limit.")

    def print_table() -> None:
        print()
        for i, (var, name, _url, _hint) in enumerate(PROVIDER_KEYS, 1):
            state = key_state(get_value(lines, var), var)
            label = {
                "ok": "[OK]  ",
                "default": "[STD] ",
                "empty": "[--]  ",
                "placeholder": "[??]  ",
            }[state]
            extra = ""
            if state == "placeholder":
                extra = "  (placeholder — counts as not set)"
            elif state == "default":
                extra = "  (default free tier)"
            elif state == "empty" and var in EMPTY_IS_OK:
                extra = "  (empty is fine)"
            print(f"   {i:2d}  {label} {var:24s} {name}{extra}")

    def edit(idx: int) -> None:
        var, name, url, hint = PROVIDER_KEYS[idx]
        current = get_value(lines, var)
        print(f"\n  ── {name} ({var})")
        print(f"     Get a key: {url}")
        if hint:
            print(f"     Hint:      {hint}")
        print(f"     Current:   {mask(current) if key_state(current, var) == 'ok' else key_state(current, var)}")
        value = ask("     New value ('-' = clear, Enter = unchanged)")
        if value == "-":
            set_value(lines, var, "")
            print("     -> cleared")
        elif value:
            set_value(lines, var, value)
            print(f"     -> set ({mask(value)})")

    while True:
        print_table()
        choice = ask("\n  Number to edit, 'a' = go through all missing ones, Enter = continue")
        if not choice:
            return
        if choice.lower() == "a":
            for i, (var, _n, _u, _h) in enumerate(PROVIDER_KEYS):
                state = key_state(get_value(lines, var), var)
                if state in {"empty", "placeholder"} and var not in EMPTY_IS_OK:
                    edit(i)
        elif choice.isdigit() and 1 <= int(choice) <= len(PROVIDER_KEYS):
            edit(int(choice) - 1)
        else:
            print("  Invalid input.")


def step_key_check(lines: list[str]) -> None:
    heading("Step 4/6 — Live key check (querying provider catalogs)")
    print("  Tests every key that's set with a read-only catalog query.")
    print("  [FAIL] with 401/403 = invalid key; 'Missing key' = not set.\n")
    import importlib.util
    path = REPO_ROOT / "find-shared-models.py"
    spec = importlib.util.spec_from_file_location("fsm_onboard", path)
    fsm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fsm)

    # Don't send placeholder values — they'd just fail as 401
    env = {
        k: v for k, v in env_dict(lines).items()
        if not is_placeholder(v)
    }
    _raw, errors = fsm.collect_models(env)
    missing = [n for n, msg in errors if msg.startswith("Missing key")]
    failed = [(n, msg) for n, msg in errors if not msg.startswith("Missing key")]
    if missing:
        print(f"\n  Skipped without a key: {', '.join(missing)}")
    if failed:
        print("\n  ⚠ Failed queries (check the key!):")
        for n, msg in failed:
            print(f"    - {n}: {msg}")


def step_render() -> bool:
    heading("Step 5/6 — Render config.yaml")
    sys.stdout.flush()  # keep ordering when stdout is piped
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "render-config.py")],
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        print("  ERROR: rendering failed — see the output above.")
        return False
    return True


# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------

def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(
        ["docker", "compose", "version"],
        capture_output=True,
    ).returncode == 0


def compose(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    sys.stdout.flush()
    return subprocess.run(
        ["docker", "compose", "--env-file", ".env", *args],
        cwd=REPO_ROOT, **kwargs,
    )


def stack_running() -> bool:
    result = compose(["ps", "-q", "--status", "running"], capture_output=True, text=True)
    return result.returncode == 0 and bool(result.stdout.strip())


def wait_for_readiness(timeout_seconds: int = 180) -> bool:
    url = f"{PROXY_URL}/health/readiness"
    print(f"  Waiting for {url} (up to {timeout_seconds}s; the first start pulls images) ...")
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        time.sleep(3)
    return False


def step_docker(lines: list[str]) -> None:
    heading("Step 6/6 — Docker Compose stack")
    if not docker_available():
        print("  docker / docker compose not found — step skipped.")
        print("  Start it manually later:  make docker-compose-up")
        return

    running = stack_running()
    if running:
        print("  The stack is already running.")
        action = "Restart it (picks up the new .env + config.yaml)?"
    else:
        action = "Start the stack now (Postgres + Redis + proxy on port 4444)?"
    if not ask_yes_no(f"  {action}"):
        print("  Skipped. Later:  make docker-compose-up")
        return

    if compose(["up", "-d"]).returncode != 0:
        print("  ERROR: docker compose up failed — see the output above.")
        return
    if running:
        # up -d doesn't detect changes to the mounted config.yaml — the
        # proxy only reads it at startup. Hence an explicit restart.
        compose(["restart", "litellm-proxy"])

    if wait_for_readiness():
        print(f"\n  ✔ Proxy is ready: {PROXY_URL}")
        print("\n  Test request (the master key is in .env):")
        print(f"""
    curl {PROXY_URL}/v1/chat/completions \\
      -H "Authorization: Bearer $(grep '^LITELLM_MASTER_KEY=' .env | cut -d= -f2-)" \\
      -H "Content-Type: application/json" \\
      -d '{{"model": "gpt-oss-120b", "messages": [{{"role": "user", "content": "Say hello!"}}]}}'
""")
    else:
        print("\n  ⚠ The proxy didn't become ready in time. Check the logs with:")
        print("    docker compose --env-file .env logs -f litellm-proxy")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--non-interactive", action="store_true",
                    help="No prompts: ensure .env exists, generate missing base "
                         "secrets, render. (No key entry, no Docker.)")
    ap.add_argument("--skip-keycheck", action="store_true",
                    help="Skip the live key check (no network queries)")
    ap.add_argument("--skip-docker", action="store_true",
                    help="Skip the Docker step")
    args = ap.parse_args()

    interactive = not args.non_interactive
    if interactive and not sys.stdin.isatty():
        print("No TTY detected — use --non-interactive for scripted setups.",
              file=sys.stderr)
        return 2

    print("=" * 74)
    print("  LiteLLM Free-Models Proxy — Onboarding")
    print("  (safe to re-run any time, e.g. for new keys or restarts)")
    print("=" * 74)

    lines = step_env_file()
    step_base_secrets(lines, interactive)
    write_env(lines)

    if interactive:
        step_provider_keys(lines)
        write_env(lines)
        print(f"\n  .env saved ({ENV_FILE})")

        if not args.skip_keycheck and ask_yes_no(
                "\n  Test the keys live against the provider catalogs now?"):
            step_key_check(lines)

    if not step_render():
        return 1

    if interactive and not args.skip_docker:
        step_docker(lines)

    heading("Done — useful commands")
    print("""  python3 onboard.py                        run this onboarding again
  make docker-compose-up / -down            start / stop the stack
  make render-config                        re-render after .env changes
  make check-config                         validate the config with a real LiteLLM boot
  make test                                 unit tests
  python3 find-shared-models.py             provider overlap + stale report
  make backup-db                            Postgres dump to ./backups/
  make opencode-config                      create/update the OpenCode provider entry""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
