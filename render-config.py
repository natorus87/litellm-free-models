#!/usr/bin/env python3
"""
Rendert config.template.yaml zu config.yaml.

  1. Liest .env und ersetzt {{ENV_VAR}} Platzhalter im Template.
  2. Filtert Provider-Deployments raus, deren API-Key fehlt (ausser
     anonymer Free-Tier wie OVHcloud).
  3. Wenn OPENROUTER_API_KEY gesetzt ist, wird `openrouter-free` an jede
     Fallback-Chain und an den Catch-All `*` angehaengt.
  4. Schreibt config.yaml atomar mit .bak.<timestamp>-Backup.

Nutzung:
    python3 render-config.py
    python3 render-config.py --env .env --template config.template.yaml
    python3 render-config.py --dry-run   # nur stdout, kein Schreiben
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

from providers_config import PROVIDERS, ProviderConfig

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_ENV = REPO_ROOT / ".env"
DEFAULT_TEMPLATE = REPO_ROOT / "config.template.yaml"
DEFAULT_OUTPUT = REPO_ROOT / "config.yaml"

# Maximale Anzahl Zeilen, die als Block-Header rueckwaerts vor einem
# Deployment-Eintrag gesucht werden. Realer Bedarf im aktuellen Template
# sind 3-4 Header-Zeilen; 12 ist grosszuegig bemessen, um auch bei
# zukuenftigen Erweiterungen robust zu sein.
MAX_HEADER_LINES = 12


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
    Leitet den internen Provider-Namen aus (model, api_base) ab.

    Diskrimination ist notwendig weil mehrere Provider das Praefix
    'openai' benutzen:
      - NVIDIA:        'openai/<vendor>/<model>' mit NVIDIA-API-Base
      - GitHub Models: 'openai/<ModelName>' (z.B. 'openai/Meta-Llama-...')
                       mit Azure-API-Base
      - OVHcloud:      'openai/<ModelName>' mit OVHcloud-API-Base
      - OpenCode Zen:  'openai/<model>' mit opencode.ai-Base
      - LLM7.io:       'openai/<model>' mit llm7.io-Base

    Wenn `model:` allein nicht eindeutig ist, wird `api_base` als
    Sekundaer-Diskriminator genutzt.

    Beispiele:
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

    # OpenAI-kompatibel. Erst Versuch via Vendor:
    vendor = parts[1] if len(parts) >= 2 else ""
    if vendor == "openai":
        return "nvidia"
    if vendor and vendor in PROVIDERS:
        return vendor

    # Kein eindeutiger Vendor. Diskrimination via api_base.
    # Wir matchen jeden OpenAI-Provider, dessen api_base_static im Block
    # vorkommt (Substring, da api_base ggf. mit/ohne Trailing-Slash).
    if api_base and not api_base.startswith("{{"):
        candidates: list[tuple[int, str]] = []
        for name, prov in PROVIDERS.items():
            if prov.prefix != "openai" or not prov.api_base_static:
                continue
            if prov.api_base_static in api_base:
                # Laengere api_base-URL = spezifischer (z.B. mit Pfad)
                candidates.append((len(prov.api_base_static), name))
        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][1]

    # Letzter Fallback: erster OpenAI-Provider ohne vendor_in_path
    for name, prov in PROVIDERS.items():
        if prov.prefix == "openai" and not prov.vendor_in_path:
            return name
    return ""


def parse_blocks(lines: list[str]) -> tuple[int, int, list[dict]]:
    """
    Liefert (model_list_start, model_list_end, [Deployment-Block]).
    Ein Block = ein - model_name: Eintrag mit allen Folge-Zeilen bis zur
    naechsten - model_name: oder einer Zeile mit weniger als 2-Space-Indent.
    """
    ml_start = -1
    for i, line in enumerate(lines):
        if line.rstrip() == "model_list:" and not line.startswith(" "):
            ml_start = i
            break
    if ml_start < 0:
        raise RuntimeError("model_list nicht gefunden")

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
                "end": i,  # wird am Ende gesetzt
                "lines": [lines[i]],
                "model_name": s.split("- model_name:", 1)[1].strip(),
                "provider": "",
                "model_id": "",
                "api_base": "",
            }
        elif current is not None:
            # Block endet vor einer Zeile mit < 2-Space-Indent (top-level key)
            if lines[i] and not lines[i].startswith("  "):
                current["end"] = i - 1
                _finalize(current)
                blocks.append(current)
                current = None
                continue
            current["lines"].append(lines[i])
            stripped = lines[i].strip()
            if stripped.startswith("model:") and " " in stripped and not current["model_id"]:
                # 'model: <praefix>/...' aus der ersten passenden Zeile
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
    Entfernt Bloecke deren API-Key fehlt.
    Liefert (gefilterte Bloecke, Liste der entfernten Provider-Keys).
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
    Ersetzt {{VAR}} durch env[VAR] (oder "" wenn nicht gesetzt).
    Liefert (neuer_text, liste_der_noch_offenen_platzhalter).
    """
    missing: list[str] = []

    def repl(m: re.Match) -> str:
        var = m.group(1)
        if var not in env:
            missing.append(var)
            return ""
        return env[var]

    return re.sub(r"\{\{([A-Z_][A-Z0-9_]*)\}\}", repl, text), missing


def update_fallbacks(
    lines: list[str],
    ml_end: int,
    openrouter_active: bool,
) -> list[str]:
    """
    - Wenn OPENROUTER_API_KEY gesetzt ist: 'openrouter-free' an jede
      Fallback-Chain und an den Catch-All '*' anhaengen (idempotent).
    - Wenn OPENROUTER_API_KEY fehlt: 'openrouter-free' aus allen
      Fallback-Chains entfernen, damit LiteLLM nicht versucht einen
      OpenRouter-Aufruf ohne Key zu machen.
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
        if not in_fallbacks:
            continue
        m = re.match(r'\s*-\s*\{"([^"]+)":\s*\[(.*?)\]\}\s*$', line)
        if not m:
            continue
        chain_str = m.group(2)
        items = [x.strip().strip('"') for x in chain_str.split(",") if x.strip().strip('"')]

        if openrouter_active:
            if "openrouter-free" not in items:
                items.append("openrouter-free")
        else:
            if "openrouter-free" in items:
                items = [x for x in items if x != "openrouter-free"]

        if not items:
            # Chain ist leer, Zeile loeschen
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
    Entfernt Fallback-Eintraege die auf model_names zeigen, die es in
    model_list nicht (mehr) gibt.
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
                    continue  # verwaist, ueberspringen
        new_lines.append(line)
    return new_lines


def render(
    template_path: Path,
    env_path: Path,
    output_path: Path,
    dry_run: bool = False,
) -> int:
    if not template_path.exists():
        print(f"FEHLER: Template nicht gefunden: {template_path}", file=sys.stderr)
        return 2
    if not env_path.exists():
        print(f"FEHLER: .env nicht gefunden: {env_path}", file=sys.stderr)
        return 2

    env = load_env(env_path)
    text = template_path.read_text(encoding="utf-8")

    # 1) Platzhalter ersetzen
    text, missing = substitute_placeholders(text, env)
    if missing:
        # Bei OVHcloud etc. ist das OK; bei anderen sollte es den Block-Filter treffen
        pass

    lines = text.splitlines(keepends=True)

    # 2) Bloecke parsen + filtern
    ml_start, ml_end, blocks = parse_blocks(lines)
    kept, removed = filter_blocks(blocks, env)

    valid_names = {b["model_name"] for b in kept}

    if removed:
        print(f"Entfernte Provider-Deployments (kein API-Key): {len(removed)}")
        for r in removed:
            print(f"  - {r}")

    # 3) Entfernte Bloecke (inkl. Header-Kommentare davor) rausnehmen
    new_lines = list(lines)
    removed_indices: set[int] = set()
    for b in blocks:
        if b in kept:
            continue
        # Header-Kommentar: Zeilen mit 2-Space-Indent die '#' enthalten,
        # direkt vor dem Block. Max. MAX_HEADER_LINES Zeilen rueckwaerts suchen.
        header_start = b["start"]
        for j in range(b["start"] - 1, max(b["start"] - MAX_HEADER_LINES, ml_start), -1):
            line = new_lines[j]
            if line is None:
                continue
            stripped = line.strip()
            if not stripped:
                continue  # Leerzeile, nicht in Header-Definition
            if stripped.startswith("#") and line.startswith("  "):
                header_start = j
            else:
                break
        for j in range(header_start, b["end"] + 1):
            removed_indices.add(j)
    new_lines = [ln for i, ln in enumerate(new_lines) if i not in removed_indices]

    # 4) ml_end neu berechnen (durch Bloecke-Entfernung verschoben sich Indizes)
    #    Wir suchen wieder nach 'model_list:' und dem ersten top-level-Key danach
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

    # 5) Fallback-Chains bereinigen + OpenRouter-Free ergaenzen
    new_lines = remove_orphaned_fallbacks(new_lines, valid_names)
    openrouter_active = bool(env.get("OPENROUTER_API_KEY"))
    new_lines = update_fallbacks(new_lines, new_ml_end, openrouter_active)

    # 6) Valid model_names-Liste ausgeben
    print(f"Behaltene Deployments: {len(kept)}")
    print(f"Verfuegbare model_names: {len(valid_names)}")
    if openrouter_active:
        print("OPENROUTER_API_KEY gesetzt -> 'openrouter-free' wird an alle Fallback-Chains angehaengt.")
    else:
        print("OPENROUTER_API_KEY fehlt -> 'openrouter-free' wird NICHT als Fallback eingebaut.")

    if dry_run:
        print("\n--- DRY-RUN: erste 40 Zeilen der generierten config.yaml ---")
        for ln in new_lines[:40]:
            print(ln, end="")
        print("---")
        return 0

    # Header ersetzen: der Template-Warn-Block ("DIESE DATEI IST DIE SINGLE
    # SOURCE OF TRUTH") soll nicht in der gerenderten config.yaml landen.
    rendered = "".join(new_lines)
    rendered = re.sub(
        r"^# =+\n# LiteLLM Proxy Configuration.*?# =+\n# DIESE DATEI.*?# =+\n",
        ("# =============================================================================\n"
         "# LiteLLM Proxy Configuration – Free Models Only\n"
         "# =============================================================================\n"
         "# GERENDERT aus config.template.yaml via render-config.py.\n"
         "# Direkte Edits an config.yaml werden beim naechsten Render ueberschrieben.\n"
         "# =============================================================================\n"),
        rendered,
        count=1,
        flags=re.DOTALL | re.MULTILINE,
    )

    # 7) Atomic write: erst tmp schreiben, dann os.replace() (atomar auf POSIX).
    #    Backup wird NACH erfolgreichem Replace erstellt -- bei Crash bleibt
    #    die alte Datei unberuehrt, kein Datenverlust-Fenster mehr.
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp.write_text(rendered, encoding="utf-8")
    os.replace(tmp, output_path)

    if output_path.exists():
        backup = output_path.with_suffix(output_path.suffix + f".bak.{int(time.time())}")
        import shutil
        shutil.copy2(output_path, backup)
        print(f"Backup: {backup}")

    print(f"config.yaml geschrieben: {output_path} ({rendered.count(chr(10))} Zeilen)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--env", type=Path, default=DEFAULT_ENV)
    ap.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--dry-run", action="store_true",
                    help="Nur Diff/Preview anzeigen, nicht schreiben")
    args = ap.parse_args()
    return render(args.template, args.env, args.output, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
