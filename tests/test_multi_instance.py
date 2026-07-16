"""Tests fuer multi-instance/generate-config.py."""
import importlib.util
import sys
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# Lade das Modul
gc = load_module("multi_instance_gc", REPO_ROOT / "multi-instance" / "generate-config.py")


class TestParseModelList(unittest.TestCase):
    def test_basic(self):
        text = textwrap.dedent("""\
        model_list:

          - model_name: foo
            litellm_params:
              model: openrouter/foo

          - model_name: bar
            litellm_params:
              model: cerebras/bar

          - model_name: foo
            litellm_params:
              model: openai/foo

        router_settings:
          routing_strategy: simple-shuffle
        """)
        entries, ml_start, ml_end = gc.parse_model_list(text.splitlines(keepends=True))
        self.assertEqual(len(entries), 3)
        self.assertEqual(ml_start, 0)
        # ml_end ist die Position von router_settings:
        self.assertEqual(ml_end, 14)

    def test_extract_model_name(self):
        entry = [
            "  - model_name: hello\n",
            "    litellm_params:\n",
            "      model: openrouter/hello\n",
        ]
        self.assertEqual(gc.extract_model_name(entry), "hello")

    def test_slave_entries_count(self):
        # 2 Modelle, 2 Slaves = 4 Slave-Entries, je 5 Zeilen = 20 Zeilen total
        slaves = [
            ("slave1", "http://slave1:4000", "S1"),
            ("slave2", "http://slave2:4000", "S2"),
        ]
        entries = gc.generate_slave_entries(["foo", "bar"], slaves)
        self.assertEqual(len(entries), 20)
        # Jeder Block hat 5 Zeilen: - model_name, litellm_params, model,
        # api_key, api_base
        # 4 Bloecke = 20 Zeilen


if __name__ == "__main__":
    unittest.main()
