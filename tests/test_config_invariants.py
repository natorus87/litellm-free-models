"""
Structural invariant tests for config.template.yaml.

These tests catch exactly the error classes that came up most often in
the July-2026 review: fallbacks to removed models, violations of the
>= 2-provider rule, and doc drift from hand-maintained numbers.
"""
import re
import unittest
from pathlib import Path

from tests._loader import REPO_ROOT, load_script

rc = load_script("render-config.py")

TEMPLATE = REPO_ROOT / "config.template.yaml"

# Documented exceptions to the >= 2-provider rule — single source is
# render-config.py (also used there for the single-deployment warning).
SINGLE_PROVIDER_ALLOWED = rc.SINGLE_PROVIDER_ALLOWED


def _parse_template():
    lines = TEMPLATE.read_text(encoding="utf-8").splitlines(keepends=True)
    _, _, blocks = rc.parse_blocks(lines)
    return lines, blocks


def _extract_chains(lines, section):
    """Returns {key: [targets]} for 'fallbacks' or 'context_window_fallbacks'."""
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
    """Every fallback target (and every key except '*') must be a
    model_name from model_list."""

    def setUp(self):
        self.lines, blocks = _parse_template()
        self.model_names = {b["model_name"] for b in blocks}

    def _check(self, section):
        chains = _extract_chains(self.lines, section)
        self.assertTrue(chains, f"no {section} entries found")
        for key, targets in chains.items():
            if key != "*":
                self.assertIn(key, self.model_names,
                              f"{section} key '{key}' does not exist in model_list")
            for t in targets:
                self.assertIn(t, self.model_names,
                              f"{section} target '{t}' (chain '{key}') does not "
                              f"exist in model_list")

    def test_fallback_targets(self):
        self._check("fallbacks")

    def test_context_window_fallback_targets(self):
        self._check("context_window_fallbacks")


class TestTwoProviderRule(unittest.TestCase):
    """Every model_name (except documented exceptions) has >= 2 deployments."""

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
                f"'{mn}' has only {n} deployment(s); rule: >= 2 providers "
                f"(exceptions: {sorted(SINGLE_PROVIDER_ALLOWED)})")


class TestTpmRpmInLitellmParams(unittest.TestCase):
    """tpm/rpm must live in litellm_params (usage-based-routing-v2 only
    evaluates it there), not at the deployment top level."""

    def test_no_top_level_tpm_rpm(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        offenders = re.findall(r"^    (tpm|rpm):.*$", text, flags=re.MULTILINE)
        self.assertEqual(offenders, [],
                         "tpm/rpm found at deployment top level – belongs "
                         "under litellm_params (6-space indent)")

    def test_every_deployment_has_rpm(self):
        _, blocks = _parse_template()
        for b in blocks:
            block_text = "".join(b["lines"])
            self.assertIn("      rpm:", block_text,
                          f"deployment '{b['model_name']}' ({b['model_id']}) "
                          f"has no rpm in litellm_params")


class TestSingleDeploymentWarnings(unittest.TestCase):
    """After the provider filter, the renderer should warn if a
    model_name has only 1 deployment left (exceptions excluded)."""

    def test_detects_single_deployment_models(self):
        kept = [
            {"model_name": "gpt-oss-120b"},
            {"model_name": "gpt-oss-120b"},
            {"model_name": "mistral-large"},          # only 1 -> warning
            {"model_name": "big-pickle"},             # exception -> no warning
            {"model_name": "openrouter-free"},        # exception -> no warning
        ]
        self.assertEqual(rc.single_deployment_warnings(kept), ["mistral-large"])

    def test_no_warnings_when_all_redundant(self):
        kept = [
            {"model_name": "a"}, {"model_name": "a"},
            {"model_name": "b"}, {"model_name": "b"},
        ]
        self.assertEqual(rc.single_deployment_warnings(kept), [])


class TestRedisMarkers(unittest.TestCase):
    """The # BEGIN/END REDIS markers must appear in pairs, otherwise
    render-config.py cannot conditionally remove the blocks."""

    def test_markers_balanced(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        begins = re.findall(r"^\s*# BEGIN REDIS", text, flags=re.MULTILINE)
        ends = re.findall(r"^\s*# END REDIS", text, flags=re.MULTILINE)
        self.assertEqual(len(begins), len(ends),
                         "BEGIN/END REDIS markers unbalanced")
        self.assertGreaterEqual(len(begins), 2,
                                "expected: cache block + router block marked")


class TestRenderWithoutRedis(unittest.TestCase):
    """A render without REDIS_HOST must not contain any Redis references."""

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
    """After a render with few keys, fallback chains must not contain
    targets whose deployments were removed entirely."""

    def test_targets_filtered_after_provider_removal(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            # Only Mistral + Cohere: many model_names drop out
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
                            f"render left an orphaned {section} target '{t}' "
                            f"in chain '{key}'")


if __name__ == "__main__":
    unittest.main()
