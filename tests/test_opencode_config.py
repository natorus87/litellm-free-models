"""Tests fuer opencode-config.py (nur reine Helfer, kein Netzwerk/Home-Zugriff)."""
import json
import tempfile
import unittest
from pathlib import Path

from tests._loader import load_script

oc = load_script("opencode-config.py")


class TestBuildProviderBlock(unittest.TestCase):
    def test_schema_shape(self):
        block = oc.build_provider_block(
            base_url="http://10.11.13.93:4444/v1",
            api_key="sk-test",
            models=["gpt-oss-120b", "kimi-k2.6"],
            display_name="Litellm-free-models",
            timeout_ms=900_000,
            chunk_timeout_ms=120_000,
        )
        # apiKey/baseURL/timeout/chunkTimeout MUESSEN in "options" liegen
        # (offizielles Schema: https://opencode.ai/config.json ->
        # $defs.ProviderConfig, additionalProperties: false auf oberster
        # Ebene -- apiKey dort waere schema-ungueltig).
        self.assertEqual(set(block.keys()), {"npm", "name", "options", "models"})
        self.assertEqual(
            set(block["options"].keys()),
            {"baseURL", "apiKey", "timeout", "chunkTimeout"},
        )
        self.assertEqual(block["options"]["apiKey"], "sk-test")
        self.assertEqual(block["options"]["timeout"], 900_000)
        self.assertEqual(block["models"], {"gpt-oss-120b": {}, "kimi-k2.6": {}})


class TestLoadOpencodeConfig(unittest.TestCase):
    def test_creates_skeleton_if_missing(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "opencode.json"
            cfg = oc.load_opencode_config(p)
            self.assertEqual(cfg["provider"], {})
            self.assertIn("$schema", cfg)

    def test_loads_and_preserves_other_providers(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "opencode.json"
            p.write_text(json.dumps({
                "$schema": "https://opencode.ai/config.json",
                "plugin": [],
                "provider": {"other": {"npm": "x", "options": {}}},
            }))
            cfg = oc.load_opencode_config(p)
            self.assertIn("other", cfg["provider"])


class TestModelsFromTemplate(unittest.TestCase):
    def test_parses_model_names(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "tmpl.yaml"
            p.write_text(
                "model_list:\n\n"
                "  - model_name: gpt-oss-120b\n"
                "    litellm_params:\n"
                "      model: openrouter/openai/gpt-oss-120b:free\n\n"
                "  - model_name: gpt-oss-120b\n"
                "    litellm_params:\n"
                "      model: cerebras/gpt-oss-120b\n\n"
                "  - model_name: kimi-k2.6\n"
                "    litellm_params:\n"
                "      model: openrouter/moonshotai/kimi-k2.6:free\n"
            )
            names = oc.models_from_template(p)
            self.assertEqual(names, ["gpt-oss-120b", "kimi-k2.6"])


class TestPruneBackups(unittest.TestCase):
    def test_keeps_only_last_n(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "opencode.json"
            for ts in range(10):
                (Path(d) / f"opencode.json.bak.{ts:010d}").write_text("{}")
            oc.prune_backups(target, keep=3)
            remaining = sorted((Path(d)).glob("opencode.json.bak.*"))
            self.assertEqual(len(remaining), 3)
            # Die NEUESTEN (hoechste Timestamps) bleiben erhalten
            self.assertTrue(remaining[-1].name.endswith("0000000009"))


class TestMergeBehavior(unittest.TestCase):
    """End-to-end (kein Netzwerk): main() mit --dry-run darf niemals in die
    Zieldatei schreiben und muss andere Provider unangetastet lassen."""

    def test_dry_run_does_not_write(self):
        import sys
        import unittest.mock as mock

        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "opencode.json"
            out.write_text(json.dumps({
                "$schema": "https://opencode.ai/config.json",
                "plugin": [],
                "provider": {"other": {"npm": "x", "options": {}}},
            }))
            env = Path(d) / ".env"
            env.write_text("LITELLM_MASTER_KEY=sk-test\n")
            template = Path(d) / "config.template.yaml"
            template.write_text(
                "model_list:\n\n  - model_name: gpt-oss-120b\n"
                "    litellm_params:\n      model: openrouter/openai/gpt-oss-120b:free\n"
            )
            argv = [
                "opencode-config.py", "--dry-run", "--from-template",
                "--env", str(env), "--template", str(template),
                "--output", str(out),
            ]
            before = out.read_text()
            with mock.patch.object(sys, "argv", argv):
                rc = oc.main()
            self.assertEqual(rc, 0)
            self.assertEqual(out.read_text(), before)  # unveraendert


if __name__ == "__main__":
    unittest.main()
