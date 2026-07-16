"""
Strukturelle Invarianten-Tests fuer config.template.yaml.

Diese Tests fangen genau die Fehlerklassen, die im Juli-2026-Review am
haeufigsten auftraten: Fallbacks auf entfernte Modelle, Verletzungen der
>= 2-Provider-Regel und Doku-Drift durch handgepflegte Zahlen.
"""
import re
import unittest
from pathlib import Path

from tests._loader import REPO_ROOT, load_script

rc = load_script("render-config.py")

TEMPLATE = REPO_ROOT / "config.template.yaml"

# Dokumentierte Ausnahmen der >= 2-Provider-Regel — Single Source ist
# render-config.py (dort auch fuer die Single-Deployment-Warnung genutzt).
SINGLE_PROVIDER_ALLOWED = rc.SINGLE_PROVIDER_ALLOWED


def _parse_template():
    lines = TEMPLATE.read_text(encoding="utf-8").splitlines(keepends=True)
    _, _, blocks = rc.parse_blocks(lines)
    return lines, blocks


def _extract_chains(lines, section):
    """Liefert {key: [targets]} fuer 'fallbacks' oder 'context_window_fallbacks'."""
    chains = {}
    in_section = False
    for line in lines:
        s = line.strip()
        if s == f"{section}:":
            in_section = True
            continue
        if in_section:
            if s and not line.startswith("    "):
                break
            m = re.match(r'\s*-\s*\{"([^"]+)":\s*\[(.*?)\]\}\s*$', line)
            if m:
                targets = [x.strip().strip('"') for x in m.group(2).split(",")
                           if x.strip().strip('"')]
                chains[m.group(1)] = targets
    return chains


class TestFallbackTargetsExist(unittest.TestCase):
    """Jedes Fallback-Ziel (und jeder Key ausser '*') muss ein model_name
    der model_list sein."""

    def setUp(self):
        self.lines, blocks = _parse_template()
        self.model_names = {b["model_name"] for b in blocks}

    def _check(self, section):
        chains = _extract_chains(self.lines, section)
        self.assertTrue(chains, f"keine {section}-Eintraege gefunden")
        for key, targets in chains.items():
            if key != "*":
                self.assertIn(key, self.model_names,
                              f"{section}-Key '{key}' existiert nicht in model_list")
            for t in targets:
                self.assertIn(t, self.model_names,
                              f"{section}-Ziel '{t}' (Chain '{key}') existiert "
                              f"nicht in model_list")

    def test_fallback_targets(self):
        self._check("fallbacks")

    def test_context_window_fallback_targets(self):
        self._check("context_window_fallbacks")


class TestTwoProviderRule(unittest.TestCase):
    """Jedes model_name (ausser dokumentierte Ausnahmen) hat >= 2 Deployments."""

    def test_min_two_deployments(self):
        _, blocks = _parse_template()
        counts = {}
        for b in blocks:
            counts[b["model_name"]] = counts.get(b["model_name"], 0) + 1
        for mn, n in sorted(counts.items()):
            if mn in SINGLE_PROVIDER_ALLOWED:
                continue
            self.assertGreaterEqual(
                n, 2,
                f"'{mn}' hat nur {n} Deployment(s); Regel: >= 2 Provider "
                f"(Ausnahmen: {sorted(SINGLE_PROVIDER_ALLOWED)})")


class TestTpmRpmInLitellmParams(unittest.TestCase):
    """tpm/rpm muessen in litellm_params liegen (usage-based-routing-v2
    wertet nur dort aus), nicht auf Deployment-Top-Level."""

    def test_no_top_level_tpm_rpm(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        offenders = re.findall(r"^    (tpm|rpm):.*$", text, flags=re.MULTILINE)
        self.assertEqual(offenders, [],
                         "tpm/rpm auf Deployment-Top-Level gefunden – gehoert "
                         "nach litellm_params (6-Space-Indent)")

    def test_every_deployment_has_rpm(self):
        _, blocks = _parse_template()
        for b in blocks:
            block_text = "".join(b["lines"])
            self.assertIn("      rpm:", block_text,
                          f"Deployment '{b['model_name']}' ({b['model_id']}) "
                          f"hat kein rpm in litellm_params")


class TestSingleDeploymentWarnings(unittest.TestCase):
    """Nach dem Provider-Filter soll der Renderer warnen, wenn ein
    model_name nur noch 1 Deployment hat (Ausnahmen ausgenommen)."""

    def test_detects_single_deployment_models(self):
        kept = [
            {"model_name": "gpt-oss-120b"},
            {"model_name": "gpt-oss-120b"},
            {"model_name": "mistral-large"},          # nur 1 -> Warnung
            {"model_name": "big-pickle"},             # Ausnahme -> keine Warnung
            {"model_name": "openrouter-free"},        # Ausnahme -> keine Warnung
        ]
        self.assertEqual(rc.single_deployment_warnings(kept), ["mistral-large"])

    def test_no_warnings_when_all_redundant(self):
        kept = [
            {"model_name": "a"}, {"model_name": "a"},
            {"model_name": "b"}, {"model_name": "b"},
        ]
        self.assertEqual(rc.single_deployment_warnings(kept), [])


class TestRedisMarkers(unittest.TestCase):
    """Die # BEGIN/END REDIS-Marker muessen paarweise vorhanden sein,
    sonst kann render-config.py die Bloecke nicht konditional entfernen."""

    def test_markers_balanced(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        begins = re.findall(r"^\s*# BEGIN REDIS", text, flags=re.MULTILINE)
        ends = re.findall(r"^\s*# END REDIS", text, flags=re.MULTILINE)
        self.assertEqual(len(begins), len(ends),
                         "BEGIN/END REDIS-Marker unbalanciert")
        self.assertGreaterEqual(len(begins), 2,
                                "Erwartet: Cache-Block + Router-Block markiert")


class TestRenderWithoutRedis(unittest.TestCase):
    """Ein Render ohne REDIS_HOST darf keine Redis-Referenzen enthalten."""

    def test_no_redis_render(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            env.write_text(
                "LITELLM_MASTER_KEY=sk-test\n"
                "OPENROUTER_API_KEY=sk-or-test\n"
            )
            out = Path(d) / "config.yaml"
            code = rc.render(TEMPLATE, env, out, dry_run=False, no_redis=True)
            self.assertEqual(code, 0)
            rendered = out.read_text(encoding="utf-8")
            self.assertNotIn("os.environ/REDIS_HOST", rendered)
            self.assertNotIn("cache: true", rendered)
            self.assertNotIn("# BEGIN REDIS", rendered)

    def test_redis_render_keeps_blocks_without_markers(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            env.write_text(
                "LITELLM_MASTER_KEY=sk-test\n"
                "OPENROUTER_API_KEY=sk-or-test\n"
                "REDIS_HOST=redis\n"
            )
            out = Path(d) / "config.yaml"
            code = rc.render(TEMPLATE, env, out, dry_run=False)
            self.assertEqual(code, 0)
            rendered = out.read_text(encoding="utf-8")
            self.assertIn("os.environ/REDIS_HOST", rendered)
            self.assertIn("cache: true", rendered)
            self.assertNotIn("# BEGIN REDIS", rendered)
            self.assertNotIn("# END REDIS", rendered)


class TestRenderedFallbackTargets(unittest.TestCase):
    """Nach einem Render mit wenigen Keys duerfen Fallback-Chains keine
    Ziele enthalten, deren Deployments komplett entfernt wurden."""

    def test_targets_filtered_after_provider_removal(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            # Nur Mistral + Cohere: viele model_names fallen weg
            env.write_text(
                "LITELLM_MASTER_KEY=sk-test\n"
                "MISTRAL_API_KEY=m-test\n"
                "COHERE_API_KEY=c-test\n"
            )
            out = Path(d) / "config.yaml"
            code = rc.render(TEMPLATE, env, out, dry_run=False, no_redis=True)
            self.assertEqual(code, 0)
            lines = out.read_text(encoding="utf-8").splitlines(keepends=True)
            _, _, blocks = rc.parse_blocks(lines)
            valid = {b["model_name"] for b in blocks}
            for section in ("fallbacks", "context_window_fallbacks"):
                for key, targets in _extract_chains(lines, section).items():
                    for t in targets:
                        self.assertIn(
                            t, valid,
                            f"Render liess verwaistes {section}-Ziel '{t}' "
                            f"in Chain '{key}' stehen")


if __name__ == "__main__":
    unittest.main()
