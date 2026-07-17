"""Tests for render-config.py."""
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests._loader import load_script

rc = load_script("render-config.py")


class TestLoadEnv(unittest.TestCase):
    def test_basic(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("FOO=bar\nBAZ=qux\n")
            env = rc.load_env(p)
            self.assertEqual(env, {"FOO": "bar", "BAZ": "qux"})

    def test_quotes_stripped(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("FOO='bar'\nBAZ=\"qux\"\n")
            env = rc.load_env(p)
            self.assertEqual(env, {"FOO": "bar", "BAZ": "qux"})

    def test_comments_and_blanks_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("# comment\n\nFOO=bar\n")
            env = rc.load_env(p)
            self.assertEqual(env, {"FOO": "bar"})

    def test_missing_file_returns_empty(self):
        env = rc.load_env(Path("/nonexistent/.env"))
        self.assertEqual(env, {})

    def test_value_with_equals(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("TOKEN=abc=def=ghi\n")
            env = rc.load_env(p)
            self.assertEqual(env["TOKEN"], "abc=def=ghi")


class TestSubstitutePlaceholders(unittest.TestCase):
    def test_basic(self):
        text, missing = rc.substitute_placeholders("KEY={{FOO}}", {"FOO": "bar"})
        self.assertEqual(text, "KEY=bar")
        self.assertEqual(missing, [])

    def test_missing_collected(self):
        text, missing = rc.substitute_placeholders("X={{A}} Y={{B}}", {"A": "1"})
        self.assertEqual(text, "X=1 Y=")
        self.assertEqual(missing, ["B"])

    def test_only_uppercase_underscore_pattern(self):
        text, missing = rc.substitute_placeholders(
            "{{VALID}} {{_UNDER}} {{123abc}}", {"VALID": "v", "_UNDER": "u"}
        )
        # "123abc" doesn't match the pattern ([A-Z_][A-Z0-9_]*) -- the
        # pattern requires [A-Z_] as the first char (no digit), so it
        # stays literal
        self.assertEqual(text, "v u {{123abc}}")


class TestProviderFromBlock(unittest.TestCase):
    def test_openrouter(self):
        self.assertEqual(
            rc._provider_from_block("openrouter/openai/gpt-oss-120b:free", ""),
            "openrouter",
        )

    def test_cerebras(self):
        self.assertEqual(
            rc._provider_from_block("cerebras/gpt-oss-120b", ""),
            "cerebras",
        )

    def test_nvidia_double_openai(self):
        self.assertEqual(
            rc._provider_from_block("openai/openai/gpt-oss-120b",
                                    "https://integrate.api.nvidia.com/v1"),
            "nvidia",
        )

    def test_nvidia_with_vendor(self):
        # 'openai/meta/llama-...'+NVIDIA base = NVIDIA
        self.assertEqual(
            rc._provider_from_block("openai/meta/llama-3.1-8b-instruct",
                                    "https://integrate.api.nvidia.com/v1"),
            "nvidia",
        )

    def test_ovhcloud_github_disambiguation(self):
        # 'openai/Meta-Llama-...' without vendor_in_path: api_base decides
        self.assertEqual(
            rc._provider_from_block("openai/Meta-Llama-3.3-70B-Instruct",
                                    "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1"),
            "ovhcloud",
        )
        self.assertEqual(
            rc._provider_from_block("openai/Meta-Llama-3.3-70B-Instruct",
                                    "https://models.inference.ai.azure.com"),
            "github",
        )

    def test_huggingface(self):
        self.assertEqual(
            rc._provider_from_block("huggingface/meta-llama/Llama-3.1-8B-Instruct", ""),
            "huggingface",
        )

    def test_empty(self):
        self.assertEqual(rc._provider_from_block("", ""), "")
        self.assertEqual(rc._provider_from_block("noprefix", ""), "")


class TestFilterBlocks(unittest.TestCase):
    def test_removes_blocks_without_api_key(self):
        blocks = [
            {"provider": "openrouter", "model_name": "x"},
            {"provider": "cerebras", "model_name": "y"},
            {"provider": "ovhcloud", "model_name": "z"},  # anonymous, OK
            {"provider": "", "model_name": "w"},  # empty provider, OK
            {"provider": "unknown", "model_name": "q"},  # unknown provider, OK
        ]
        env = {"OPENROUTER_API_KEY": "k", "CEREBRAS_API_KEY": ""}
        kept, removed = rc.filter_blocks(blocks, env)
        self.assertEqual(len(kept), 4)
        self.assertEqual(len(removed), 1)
        self.assertIn("cerebras", removed[0])


class TestParseBlocks(unittest.TestCase):
    def test_basic_parse(self):
        text = textwrap.dedent("""\
        model_list:

          # =========
          # gpt-oss  –  2 FREE PROVIDERS
          # =========

          - model_name: gpt-oss-120b
            litellm_params:
              model: openrouter/openai/gpt-oss-120b:free
              api_key: sk-or-test

          - model_name: gpt-oss-120b
            litellm_params:
              model: cerebras/gpt-oss-120b
              api_key: cer-test

        router_settings:
          routing_strategy: simple-shuffle
        """)
        lines = text.splitlines(keepends=True)
        ml_start, ml_end, blocks = rc.parse_blocks(lines)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["model_name"], "gpt-oss-120b")
        self.assertEqual(blocks[0]["provider"], "openrouter")
        self.assertEqual(blocks[1]["provider"], "cerebras")

    def test_provider_mapping_with_api_base(self):
        text = textwrap.dedent("""\
        model_list:

          - model_name: foo
            litellm_params:
              model: openai/Meta-Llama-3.3-70B-Instruct
              api_key: github-token
              api_base: https://models.inference.ai.azure.com

          - model_name: foo
            litellm_params:
              model: openai/Meta-Llama-3.3-70B-Instruct
              api_key: ""
              api_base: https://oai.endpoints.kepler.ai.cloud.ovh.net/v1
        """)
        lines = text.splitlines(keepends=True)
        _, _, blocks = rc.parse_blocks(lines)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["provider"], "github")
        self.assertEqual(blocks[1]["provider"], "ovhcloud")


class TestUpdateFallbacks(unittest.TestCase):
    def test_openrouter_free_appended(self):
        lines = [
            'fallbacks:\n',
            '  - {"gpt-oss-120b": ["gpt-oss-20b", "llama-3.1-8b"]}\n',
        ]
        out = rc.update_fallbacks(lines, len(lines), openrouter_active=True)
        self.assertIn("openrouter-free", out[1])

    def test_openrouter_free_removed(self):
        lines = [
            'fallbacks:\n',
            '  - {"gpt-oss-120b": ["gpt-oss-20b", "openrouter-free"]}\n',
        ]
        out = rc.update_fallbacks(lines, len(lines), openrouter_active=False)
        self.assertNotIn("openrouter-free", out[1])
        # chain isn't empty, should be preserved
        self.assertIn("gpt-oss-20b", out[1])

    def test_empty_chain_removed(self):
        lines = [
            'fallbacks:\n',
            '  - {"gpt-oss-120b": ["openrouter-free"]}\n',
        ]
        out = rc.update_fallbacks(lines, len(lines), openrouter_active=False)
        # chain is empty (only openrouter-free removed), line becomes empty
        self.assertEqual(out[1], "")


class TestRemoveOrphanedFallbacks(unittest.TestCase):
    def test_keeps_valid(self):
        lines = [
            'fallbacks:\n',
            '  - {"gpt-oss-120b": ["a"]}\n',
            '  - {"*": ["x"]}\n',
        ]
        out = rc.remove_orphaned_fallbacks(lines, {"gpt-oss-120b"})
        self.assertEqual(len(out), 3)

    def test_removes_unknown_model(self):
        lines = [
            'fallbacks:\n',
            '  - {"gpt-oss-120b": ["a"]}\n',
            '  - {"deleted-model": ["a"]}\n',
            '  - {"*": ["x"]}\n',
        ]
        out = rc.remove_orphaned_fallbacks(lines, {"gpt-oss-120b"})
        # 'deleted-model' line is gone
        content = "".join(out)
        self.assertNotIn("deleted-model", content)
        self.assertIn("gpt-oss-120b", content)
        self.assertIn('"*"', content)


class TestAtomicWrite(unittest.TestCase):
    """Make sure render() doesn't leave a broken config.yaml behind on crash."""

    def test_writes_only_after_tmp_complete(self):
        # Render into a temp dir and check that output_path exists and no
        # .tmp/.bak leftovers remain
        with tempfile.TemporaryDirectory() as d:
            tmpl = Path(d) / "tmpl.yaml"
            env_p = Path(d) / ".env"
            out = Path(d) / "out.yaml"

            tmpl.write_text(textwrap.dedent("""\
                model_list:

                  - model_name: a
                    litellm_params:
                      model: openrouter/openai/a
                      api_key: {{OPENROUTER_API_KEY}}
                """))
            env_p.write_text("OPENROUTER_API_KEY=test-key\n")

            rc.render(tmpl, env_p, out)
            self.assertTrue(out.exists())
            self.assertIn("test-key", out.read_text())
            # no leftover .tmp
            self.assertFalse(out.with_suffix(out.suffix + ".tmp").exists())

    def test_existing_output_preserved_on_write(self):
        """render() must NOT move/delete the existing output_path before
        the tmp file is fully written (no data-loss window)."""
        with tempfile.TemporaryDirectory() as d:
            tmpl = Path(d) / "tmpl.yaml"
            env_p = Path(d) / ".env"
            out = Path(d) / "out.yaml"

            # existing output
            out.write_text("EXISTING CONTENT\n")
            self.assertTrue(out.exists())

            tmpl.write_text("model_list:\n")
            env_p.write_text("OPENROUTER_API_KEY=k\n")

            rc.render(tmpl, env_p, out)
            # new content is in there
            self.assertIn("model_list", out.read_text())
            # backup exists and contains the OLD content (a backup of the
            # previous version, not a copy of the new one)
            backups = list(Path(d).glob("out.yaml.bak.*"))
            self.assertEqual(len(backups), 1)
            self.assertIn("EXISTING CONTENT", backups[0].read_text())
            # no leftover .tmp
            self.assertFalse(out.with_suffix(out.suffix + ".tmp").exists())


class TestEndToEndRender(unittest.TestCase):
    def test_full_render_with_minimal_template(self):
        with tempfile.TemporaryDirectory() as d:
            tmpl = Path(d) / "tmpl.yaml"
            env_p = Path(d) / ".env"
            out = Path(d) / "out.yaml"

            tmpl.write_text(textwrap.dedent("""\
                model_list:

                  - model_name: gpt-oss-120b
                    litellm_params:
                      model: openrouter/openai/gpt-oss-120b
                      api_key: {{OPENROUTER_API_KEY}}

                  - model_name: gpt-oss-120b
                    litellm_params:
                      model: cerebras/gpt-oss-120b
                      api_key: {{CEREBRAS_API_KEY}}

                  - model_name: llama-3.1-8b
                    litellm_params:
                      model: openrouter/meta-llama/llama-3.1-8b
                      api_key: {{OPENROUTER_API_KEY}}

                  - model_name: openrouter-free
                    litellm_params:
                      model: openrouter/openrouter/free
                      api_key: {{OPENROUTER_API_KEY}}

                router_settings:
                  routing_strategy: simple-shuffle
                fallbacks:
                  - {"gpt-oss-120b": ["llama-3.1-8b", "does-not-exist"]}
                """))
            env_p.write_text(
                "OPENROUTER_API_KEY=test-or\n"
                "CEREBRAS_API_KEY=\n"  # empty -> cerebras block is removed
            )

            rc.render(tmpl, env_p, out)
            content = out.read_text()
            self.assertIn("test-or", content)
            self.assertNotIn("cerebras/gpt-oss-120b", content)
            # fallback chain should still contain "llama-3.1-8b"
            self.assertIn("llama-3.1-8b", content)
            # targets without a matching model_name are removed
            self.assertNotIn("does-not-exist", content)
            # OPENROUTER_API_KEY is set -> openrouter-free is appended
            self.assertIn("openrouter-free", content)


if __name__ == "__main__":
    unittest.main()
