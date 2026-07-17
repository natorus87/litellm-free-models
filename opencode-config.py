#!/usr/bin/env python3
"""
Generiert/erweitert eine OpenCode-Config (~/.config/opencode/opencode.json)
um einen Provider-Eintrag fuer diesen LiteLLM-Proxy.

Schreibt NUR den einen Provider-Key (Default: "litellm") -- alle anderen
Provider und Top-Level-Felder in der Zieldatei bleiben unangetastet. Der
Provider-Block wird schema-konform gemaess https://opencode.ai/config.json
gebaut (apiKey/baseURL/timeout/chunkTimeout gehoeren in "options", nicht
auf die oberste Ebene -- das war in bestehenden Configs teils falsch).

Modell-Liste:
  - Standard: live von diesem Proxy per GET /models abgefragt (spiegelt
    exakt wider, was mit den aktuell gesetzten .env-Keys servierbar ist).
  - Fallback (--from-template oder wenn der Proxy nicht erreichbar ist):
    aus config.template.yaml geparst (kann Modelle enthalten, die ohne
    den passenden API-Key nicht wirklich verfuegbar sind).

Idempotent und sicher wiederholbar: legt vor jedem Schreiben ein
Timestamp-Backup der vorherigen opencode.json an (die letzten 5 werden
behalten), unterstuetzt --dry-run zum Pruefen ohne zu schreiben.

Nutzung:
    python3 opencode-config.py                       # localhost:4444, schreibt
    python3 opencode-config.py --dry-run              # nur Vorschau
    python3 opencode-config.py --host 10.11.13.93     # anderer Host
    python3 opencode-config.py --from-template         # ohne Live-Abfrage
    python3 opencode-config.py --output /pfad/zu/opencode.json
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
DEFAULT_TIMEOUT_MS = 900_000       # 15 min -- volle Requests koennen bei
                                    # Free-Tier-Fallback-Ketten lange dauern
DEFAULT_CHUNK_TIMEOUT_MS = 120_000  # 2 min zwischen SSE-Chunks
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
    """GET {base_url}/models. Liefert None (statt zu werfen) wenn der Proxy
    nicht erreichbar ist -- der Aufrufer faellt dann auf das Template
    zurueck, statt das ganze Script abzubrechen."""
    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return sorted({m["id"] for m in data.get("data", []) if m.get("id")})
    except (urllib.error.URLError, OSError, TimeoutError, ValueError, KeyError) as exc:
        print(f"  [WARN] Live-Abfrage von {url} fehlgeschlagen ({exc}) "
              "-- falle auf config.template.yaml zurueck.", file=sys.stderr)
        return None


def models_from_template(template_path: Path) -> list[str]:
    """Parst model_names direkt aus config.template.yaml (ungefiltert --
    kann Modelle enthalten, deren Provider-Key in .env fehlt)."""
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
                    help=f"Proxy-Host. Default: bestehende baseURL beim "
                         f"Update wiederverwenden, sonst {DEFAULT_HOST}")
    ap.add_argument("--port", type=int, default=None,
                    help=f"Proxy-Port. Default: bestehende baseURL beim "
                         f"Update wiederverwenden, sonst {DEFAULT_PORT}")
    ap.add_argument("--base-url", default=None,
                    help="Vollstaendige Base-URL, ueberschreibt --host/--port "
                         "(z.B. http://10.11.13.93:4444/v1)")
    ap.add_argument("--api-key", default=None,
                    help="Master-Key. Default: LITELLM_MASTER_KEY aus .env")
    ap.add_argument("--env", type=Path, default=DEFAULT_ENV)
    ap.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    ap.add_argument("--provider-id", default="litellm",
                    help="Key unter 'provider' in der opencode.json (default: litellm)")
    ap.add_argument("--name", default="Litellm-free-models",
                    help="Anzeigename (default: Litellm-free-models)")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_MS,
                    help=f"Request-Timeout in ms (default: {DEFAULT_TIMEOUT_MS})")
    ap.add_argument("--chunk-timeout", type=int, default=DEFAULT_CHUNK_TIMEOUT_MS,
                    help=f"SSE-Chunk-Timeout in ms (default: {DEFAULT_CHUNK_TIMEOUT_MS})")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                    help=f"Ziel-opencode.json (default: {DEFAULT_OUTPUT})")
    ap.add_argument("--from-template", action="store_true",
                    help="Modelle aus config.template.yaml statt Live-Abfrage "
                         "(z.B. wenn der Proxy gerade nicht laeuft)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Nur anzeigen was geschrieben wuerde, nicht speichern")
    args = ap.parse_args()

    env = load_env(args.env)
    api_key = args.api_key or env.get("LITELLM_MASTER_KEY", "")
    if not api_key:
        print("FEHLER: kein API-Key. --api-key setzen oder LITELLM_MASTER_KEY "
              f"in {args.env} pflegen.", file=sys.stderr)
        return 2

    config = load_opencode_config(args.output)
    config.setdefault("provider", {})
    existing_block = config["provider"].get(args.provider_id)
    existing_base_url = (existing_block or {}).get("options", {}).get("baseURL")

    # baseURL-Prioritaet: explizite Flags > bestehender Wert beim Update
    # (verhindert, dass ein re-Run versehentlich eine bereits funktionierende
    # LAN-Adresse durch den lokalen Default ueberschreibt) > Default.
    if args.base_url:
        base_url = args.base_url
    elif args.host or args.port:
        base_url = f"http://{args.host or DEFAULT_HOST}:{args.port or DEFAULT_PORT}/v1"
    elif existing_base_url:
        base_url = existing_base_url
        print(f"Nutze bestehende baseURL aus {args.output}: {base_url}")
    else:
        base_url = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/v1"

    models: list[str] | None = None
    if not args.from_template:
        print(f"Frage Live-Modelle ab: {base_url}/models ...")
        models = fetch_live_models(base_url, api_key)
    if models is None:
        if not args.template.exists():
            print(f"FEHLER: {args.template} nicht gefunden und Live-Abfrage "
                  "nicht moeglich.", file=sys.stderr)
            return 2
        print(f"Lese Modelle aus {args.template} ...")
        models = models_from_template(args.template)

    print(f"{len(models)} Modelle: {', '.join(models[:6])}"
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
        print(f"\n--- DRY-RUN: provider.{args.provider_id} ---")
        print(json.dumps(provider_block, indent=2, ensure_ascii=False))
        if existing_block is not None and existing_block != provider_block:
            print(f"\n(Wuerde bestehenden provider.{args.provider_id}-Block ersetzen)")
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

    action = "aktualisiert" if existing_block is not None else "angelegt"
    print(f"\nprovider.{args.provider_id} in {args.output} {action} "
          f"({len(models)} Modelle, baseURL={base_url}, "
          f"timeout={args.timeout}ms, chunkTimeout={args.chunk_timeout}ms).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
