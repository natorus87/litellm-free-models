#!/usr/bin/env python3
"""
Interaktives Onboarding fuer den LiteLLM Free-Models Proxy.

Fuehrt durch das komplette Setup und ist bewusst WIEDERHOLBAR — auch fuer
spaetere Aenderungen (neuer API-Key, Passwort-Rotation, Re-Render, Restart):

  1. .env anlegen (aus .env.example) bzw. bestehende .env weiterverwenden
  2. Grund-Secrets generieren (LITELLM_MASTER_KEY, REDIS_/POSTGRES_PASSWORD)
  3. Provider-API-Keys gefuehrt eintragen (mit Signup-URLs und Hinweisen)
  4. Optional: Keys LIVE gegen die Provider-Kataloge testen
  5. config.yaml rendern (inkl. Single-Deployment-Warnungen)
  6. Optional: Docker-Compose-Stack starten/neustarten + Readiness-Check

Nutzung:
    python3 onboard.py                  # interaktiv (empfohlen)
    python3 onboard.py --non-interactive  # nur Secrets generieren + rendern
    make onboard

Nur Python-Standardbibliothek, keine Dependencies (Repo-Konvention).
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

# Werte, die als "nicht gesetzt" gelten (Platzhalter aus .env.example)
PLACEHOLDER_MARKERS = ("change-me", "change_me", "your-", "-here", "placeholder")

# (env_var, Anzeigename, Signup-URL, Hinweis)
PROVIDER_KEYS: list[tuple[str, str, str, str]] = [
    ("OPENROUTER_API_KEY", "OpenRouter", "https://openrouter.ai/keys",
     "Wichtigster Key: aktiviert den openrouter-free-Fallback in allen Chains."),
    ("CEREBRAS_API_KEY", "Cerebras", "https://cloud.cerebras.ai/", ""),
    ("GROQ_API_KEY", "Groq", "https://console.groq.com/keys", ""),
    ("CLOUDFLARE_API_KEY", "Cloudflare Workers AI",
     "https://dash.cloudflare.com/profile/api-tokens",
     "Braucht zusaetzlich CLOUDFLARE_API_BASE (naechster Eintrag)."),
    ("CLOUDFLARE_API_BASE", "Cloudflare API-Base",
     "https://developers.cloudflare.com/fundamentals/setup/find-account-and-zone-ids/",
     "Format: https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/v1"),
    ("GEMINI_API_KEY", "Google AI Studio", "https://aistudio.google.com/apikey",
     "Derzeit kein aktives Deployment (gemma-3 eingestellt); nur fuer Syncs."),
    ("NVIDIA_API_KEY", "NVIDIA NIM", "https://build.nvidia.com/",
     "Telefon-Verifikation noetig; dafuer 40 RPM."),
    ("MISTRAL_API_KEY", "Mistral La Plateforme", "https://console.mistral.ai/", ""),
    ("COHERE_API_KEY", "Cohere", "https://dashboard.cohere.com/api-keys",
     "Trial-Key: 1000 Calls/Monat."),
    ("GITHUB_TOKEN", "GitHub Models", "https://github.com/settings/tokens",
     "PAT mit Scope models:read."),
    ("OPENCODE_ZEN_API_KEY", "OpenCode Zen", "https://opencode.ai/zen", ""),
    ("LLM7IO_API_KEY", "LLM7.io", "https://token.llm7.io",
     "'unused' = Basis-Free-Tier (2 RPM); kostenloses Token = 40 RPM."),
    ("HF_TOKEN", "HuggingFace", "https://huggingface.co/settings/tokens", ""),
    ("OVHCLOUD_API_KEY", "OVHcloud", "https://www.ovhcloud.com/en/public-cloud/ai-endpoints/",
     "Leer lassen = anonymer Free-Tier (2 RPM/IP/Modell), voellig OK."),
]

# Variablen, bei denen "leer" ein gueltiger, gewollter Zustand ist
EMPTY_IS_OK = {"OVHCLOUD_API_KEY", "GEMINI_API_KEY"}
# Variablen mit gueltigem Nicht-Key-Default
SPECIAL_DEFAULTS = {"LLM7IO_API_KEY": "unused"}


# ---------------------------------------------------------------------------
# .env-Handling (kommentar-erhaltend)
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
    """'ok' | 'leer' | 'platzhalter' | 'default'"""
    if not value:
        return "leer"
    if is_placeholder(value):
        return "platzhalter"
    if SPECIAL_DEFAULTS.get(var) == value:
        return "default"
    return "ok"


def mask(value: str) -> str:
    if not value:
        return "(leer)"
    if len(value) <= 8:
        return value[:2] + "…"
    return value[:6] + "…" + value[-2:]


# ---------------------------------------------------------------------------
# Interaktions-Helfer
# ---------------------------------------------------------------------------

def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAbgebrochen. Bereits geschriebene .env-Aenderungen bleiben erhalten.")
        sys.exit(130)
    return answer or default


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    hint = "J/n" if default else "j/N"
    answer = ask(f"{prompt} ({hint})").lower()
    if not answer:
        return default
    return answer in {"j", "ja", "y", "yes"}


def heading(text: str) -> None:
    print()
    print("─" * 74)
    print(f"  {text}")
    print("─" * 74)


# ---------------------------------------------------------------------------
# Schritte
# ---------------------------------------------------------------------------

def step_env_file() -> list[str]:
    heading("Schritt 1/6 — .env")
    if ENV_FILE.exists():
        print(f"  Bestehende {ENV_FILE.name} gefunden — Werte werden uebernommen,")
        print("  du kannst sie in den naechsten Schritten gezielt aendern.")
    else:
        shutil.copy2(ENV_EXAMPLE, ENV_FILE)
        print(f"  {ENV_FILE.name} aus {ENV_EXAMPLE.name} angelegt.")
    return read_env_lines()


def step_base_secrets(lines: list[str], interactive: bool) -> None:
    heading("Schritt 2/6 — Grund-Secrets (Master-Key & Passwoerter)")
    specs = [
        ("LITELLM_MASTER_KEY", "sk-" + secrets.token_hex(24),
         "Auth-Token, das Clients an den Proxy senden"),
        ("REDIS_PASSWORD", secrets.token_hex(16),
         "Pflicht: docker compose startet ohne nicht"),
        ("POSTGRES_PASSWORD", secrets.token_hex(16),
         "Pflicht: docker compose startet ohne nicht"),
    ]
    for var, generated, why in specs:
        current = get_value(lines, var)
        if key_state(current, var) == "ok":
            print(f"  [OK] {var} ist gesetzt ({mask(current)})")
            continue
        if interactive:
            print(f"\n  {var} — {why}")
            value = ask("  Eigenen Wert eingeben oder Enter = sicher generieren")
            value = value or generated
        else:
            value = generated
        set_value(lines, var, value)
        print(f"  [NEU] {var} = {mask(value)}")


def step_provider_keys(lines: list[str]) -> None:
    heading("Schritt 3/6 — Provider-API-Keys")
    print("  Alle Keys sind optional: Provider ohne Key werden beim Rendern")
    print("  einfach weggelassen. Mehr Provider = mehr Redundanz & Rate-Limit.")

    def print_table() -> None:
        print()
        for i, (var, name, _url, _hint) in enumerate(PROVIDER_KEYS, 1):
            state = key_state(get_value(lines, var), var)
            label = {
                "ok": "[OK]  ",
                "default": "[STD] ",
                "leer": "[--]  ",
                "platzhalter": "[??]  ",
            }[state]
            extra = ""
            if state == "platzhalter":
                extra = "  (Platzhalter — zaehlt als nicht gesetzt)"
            elif state == "default":
                extra = "  (Default-Free-Tier)"
            elif state == "leer" and var in EMPTY_IS_OK:
                extra = "  (leer ist OK)"
            print(f"   {i:2d}  {label} {var:24s} {name}{extra}")

    def edit(idx: int) -> None:
        var, name, url, hint = PROVIDER_KEYS[idx]
        current = get_value(lines, var)
        print(f"\n  ── {name} ({var})")
        print(f"     Key holen: {url}")
        if hint:
            print(f"     Hinweis:   {hint}")
        print(f"     Aktuell:   {mask(current) if key_state(current, var) == 'ok' else key_state(current, var)}")
        value = ask("     Neuer Wert ('-' = leeren, Enter = unveraendert)")
        if value == "-":
            set_value(lines, var, "")
            print("     -> geleert")
        elif value:
            set_value(lines, var, value)
            print(f"     -> gesetzt ({mask(value)})")

    while True:
        print_table()
        choice = ask("\n  Nummer bearbeiten, 'a' = alle fehlenden durchgehen, Enter = weiter")
        if not choice:
            return
        if choice.lower() == "a":
            for i, (var, _n, _u, _h) in enumerate(PROVIDER_KEYS):
                state = key_state(get_value(lines, var), var)
                if state in {"leer", "platzhalter"} and var not in EMPTY_IS_OK:
                    edit(i)
        elif choice.isdigit() and 1 <= int(choice) <= len(PROVIDER_KEYS):
            edit(int(choice) - 1)
        else:
            print("  Ungueltige Eingabe.")


def step_key_check(lines: list[str]) -> None:
    heading("Schritt 4/6 — Live-Key-Check (Provider-Kataloge abfragen)")
    print("  Testet jeden gesetzten Key mit einer read-only Katalog-Abfrage.")
    print("  [FAIL] mit 401/403 = Key ungueltig; 'Key fehlt' = nicht gesetzt.\n")
    import importlib.util
    path = REPO_ROOT / "find-shared-models.py"
    spec = importlib.util.spec_from_file_location("fsm_onboard", path)
    fsm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fsm)

    # Platzhalter-Werte nicht mitschicken — sie wuerden nur als 401 failen
    env = {
        k: v for k, v in env_dict(lines).items()
        if not is_placeholder(v)
    }
    _raw, errors = fsm.collect_models(env)
    missing = [n for n, msg in errors if msg.startswith("Key fehlt")]
    failed = [(n, msg) for n, msg in errors if not msg.startswith("Key fehlt")]
    if missing:
        print(f"\n  Ohne Key uebersprungen: {', '.join(missing)}")
    if failed:
        print("\n  ⚠ Fehlgeschlagene Abfragen (Key pruefen!):")
        for n, msg in failed:
            print(f"    - {n}: {msg}")


def step_render() -> bool:
    heading("Schritt 5/6 — config.yaml rendern")
    sys.stdout.flush()  # Reihenfolge wahren, wenn stdout gepiped ist
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "render-config.py")],
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        print("  FEHLER: Rendern fehlgeschlagen — siehe Ausgabe oben.")
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
    print(f"  Warte auf {url} (max. {timeout_seconds}s; erster Start zieht Images) ...")
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
    heading("Schritt 6/6 — Docker-Compose-Stack")
    if not docker_available():
        print("  docker / docker compose nicht gefunden — Schritt uebersprungen.")
        print("  Manueller Start spaeter:  make docker-compose-up")
        return

    running = stack_running()
    if running:
        print("  Stack laeuft bereits.")
        action = "Neu starten (uebernimmt neue .env + config.yaml)?"
    else:
        action = "Stack jetzt starten (Postgres + Redis + Proxy auf Port 4444)?"
    if not ask_yes_no(f"  {action}"):
        print("  Uebersprungen. Spaeter:  make docker-compose-up")
        return

    if compose(["up", "-d"]).returncode != 0:
        print("  FEHLER: docker compose up fehlgeschlagen — siehe Ausgabe oben.")
        return
    if running:
        # up -d erkennt Aenderungen an der gemounteten config.yaml nicht —
        # der Proxy liest sie nur beim Start. Deshalb expliziter Restart.
        compose(["restart", "litellm-proxy"])

    if wait_for_readiness():
        print(f"\n  ✔ Proxy ist bereit: {PROXY_URL}")
        print("\n  Test-Request (Master-Key steht in .env):")
        print(f"""
    curl {PROXY_URL}/v1/chat/completions \\
      -H "Authorization: Bearer $(grep '^LITELLM_MASTER_KEY=' .env | cut -d= -f2-)" \\
      -H "Content-Type: application/json" \\
      -d '{{"model": "gpt-oss-120b", "messages": [{{"role": "user", "content": "Sag hallo!"}}]}}'
""")
    else:
        print("\n  ⚠ Proxy wurde nicht rechtzeitig ready. Logs ansehen mit:")
        print("    docker compose --env-file .env logs -f litellm-proxy")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--non-interactive", action="store_true",
                    help="Keine Fragen: .env sicherstellen, fehlende Grund-Secrets "
                         "generieren, rendern. (Keine Key-Eingabe, kein Docker.)")
    ap.add_argument("--skip-keycheck", action="store_true",
                    help="Live-Key-Check ueberspringen (keine Netzwerk-Abfragen)")
    ap.add_argument("--skip-docker", action="store_true",
                    help="Docker-Schritt ueberspringen")
    args = ap.parse_args()

    interactive = not args.non_interactive
    if interactive and not sys.stdin.isatty():
        print("Kein TTY erkannt — nutze --non-interactive fuer Skript-Setups.",
              file=sys.stderr)
        return 2

    print("=" * 74)
    print("  LiteLLM Free-Models Proxy — Onboarding")
    print("  (jederzeit wieder ausfuehrbar, z.B. fuer neue Keys oder Restarts)")
    print("=" * 74)

    lines = step_env_file()
    step_base_secrets(lines, interactive)
    write_env(lines)

    if interactive:
        step_provider_keys(lines)
        write_env(lines)
        print(f"\n  .env gespeichert ({ENV_FILE})")

        if not args.skip_keycheck and ask_yes_no(
                "\n  Keys jetzt live gegen die Provider-Kataloge testen?"):
            step_key_check(lines)

    if not step_render():
        return 1

    if interactive and not args.skip_docker:
        step_docker(lines)

    heading("Fertig — nuetzliche Kommandos")
    print("""  python3 onboard.py                        dieses Onboarding erneut
  make docker-compose-up / -down            Stack starten / stoppen
  make render-config                        nach .env-Aenderungen neu rendern
  make check-config                         Config durch echten LiteLLM-Boot validieren
  make test                                 Unit-Tests
  python3 find-shared-models.py             Provider-Overlap + Stale-Report
  make backup-db                            Postgres-Dump nach ./backups/
  make opencode-config                      Provider-Eintrag fuer OpenCode anlegen/updaten""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
