"""Tests fuer find-shared-models.py."""
import unittest
from pathlib import Path

from tests._loader import load_script

fsm = load_script("find-shared-models.py")


class TestNormalize(unittest.TestCase):
    def test_strip_free_suffix(self):
        self.assertEqual(fsm.normalize("gpt-oss-120b:free"), "gpt-oss-120b")
        self.assertEqual(fsm.normalize("gpt-oss-120b-free"), "gpt-oss-120b")

    def test_strip_size_qualifier(self):
        self.assertEqual(fsm.normalize("model-fast"), "model")
        self.assertEqual(fsm.normalize("model.pro"), "model")
        # 'b' (Param-Count wie 7b, 70b) bleibt erhalten
        self.assertEqual(fsm.normalize("gpt-oss-70b"), "gpt-oss-70b")
        # 'k' am Ende (Context-Window wie 128k) wird gestrippt, wenn direkt
        # am Stringende: 'model-128k' endet auf '-128k', nicht '-k', bleibt
        self.assertEqual(fsm.normalize("model-128k"), "model-128k")
        # Aber: 'model-128-k' endet auf '-k' und wird gestrippt
        self.assertEqual(fsm.normalize("model-128-k"), "model-128")

    def test_strip_stopwords(self):
        # 'meta', 'llama', 'instruct' etc. werden rausgefiltert
        result = fsm.normalize("Meta-Llama-3.3-70B-Instruct")
        # 'meta', 'llama' und 'instruct' sind stopwords; '3-3' und '70b' bleiben
        self.assertNotIn("meta", result)
        self.assertNotIn("llama", result)

    def test_idempotent(self):
        s = "Meta-Llama-3.3-70B-Instruct-128k"
        self.assertEqual(fsm.normalize(s), fsm.normalize(fsm.normalize(s)))


class TestShortKey(unittest.TestCase):
    def test_strips_path(self):
        self.assertEqual(fsm.short_key("openrouter/openai/gpt-oss-120b"),
                         "gpt-oss-120b")


class TestZenGroups(unittest.TestCase):
    """Tests fuer den Include-Bug (big-pickle vs big-pickle-extra)."""

    def test_excludes_unrelated_substring_match(self):
        # Zen = 'big-pickle'. 'big-pickle-extra' darf NICHT matchen.
        raw = {"p1": ["big-pickle"], "p2": ["big-pickle-extra"]}
        out = fsm.find_zen_groups(raw)
        self.assertIn("big-pickle", out)
        self.assertNotIn("big-pickle-extra", out)
        self.assertEqual(set(out["big-pickle"].keys()), {"p1"})

    def test_includes_word_boundary_match(self):
        # Zen = 'big-pickle', Modell 'big-pickle-mini' SOLL matchen (boundary)
        raw = {"p1": ["big-pickle"], "p2": ["big-pickle-mini"]}
        out = fsm.find_zen_groups(raw)
        # Beide normalisieren zu 'big-pickle' und 'big-pickle-mini'.
        # 'big-pickle' und 'big-pickle-mini' sind durch '-' boundary getrennt,
        # daher sollte 'big-pickle-mini' im Set sein.
        # (Hauptkey in `out` ist 'big-pickle' via exakten Match.)
        # Beide Modelle sollten unter dem key 'big-pickle' oder
        # 'big-pickle-mini' einsortiert sein.
        all_keys = set()
        for provs in out.values():
            for models in provs.values():
                all_keys.update(models)
        self.assertIn("big-pickle", all_keys)
        self.assertIn("big-pickle-mini", all_keys)

    def test_empty_input(self):
        out = fsm.find_zen_groups({})
        self.assertEqual(out, {})

    def test_does_not_match_unrelated_substring(self):
        # 'deepseek-v4-flash' darf nicht 'deepseek-v3-flash' aufnehmen
        raw = {"p1": ["deepseek-v4-flash"], "p2": ["deepseek-v3-flash"]}
        out = fsm.find_zen_groups(raw)
        all_keys = set()
        for provs in out.values():
            for models in provs.values():
                all_keys.update(models)
        self.assertIn("deepseek-v4-flash", all_keys)
        self.assertNotIn("deepseek-v3-flash", all_keys)


class TestBuildGroups(unittest.TestCase):
    def test_only_groups_with_multiple_providers(self):
        raw = {
            "p1": ["gpt-oss-120b", "unique-thing-99"],
            "p2": ["gpt-oss-120b"],
        }
        groups = fsm.build_groups(raw)
        # gpt-oss-120b hat 2 Provider, also in groups
        self.assertIn("gpt-oss-120b", groups)
        # unique-thing-99 nur 1 Provider, also draussen
        self.assertNotIn("unique-thing-99", groups)


class TestLookupPrice(unittest.TestCase):
    def setUp(self):
        fsm._reset_pricing_index()
        self.pricing = {
            "sample_spec": {},
            "openrouter/openai/gpt-oss-120b": {
                "input_cost_per_token": 3.9e-08,
                "output_cost_per_token": 1.8e-07,
            },
            "cerebras/gpt-oss-120b": {
                "input_cost_per_token": 3.5e-08,
                "output_cost_per_token": 1.7e-07,
            },
            "nvidia_nim/openai/gpt-oss-120b": {
                "input_cost_per_token": 4e-08,
                "output_cost_per_token": 2e-07,
            },
        }

    def test_direct_hit(self):
        e, k = fsm.lookup_price(self.pricing, "openrouter",
                                "openai/gpt-oss-120b:free",
                                with_fallback=True)
        self.assertEqual(k, "openrouter/openai/gpt-oss-120b")

    def test_fallback_picks_cheapest(self):
        e, k = fsm.lookup_price(self.pricing, "groq",
                                "openai/gpt-oss-120b",
                                with_fallback=True)
        # cerebras hat niedrigere Kosten als openrouter und nvidia_nim
        self.assertEqual(k, "cerebras/gpt-oss-120b")

    def test_no_fallback_returns_none(self):
        e, k = fsm.lookup_price(self.pricing, "groq",
                                "openai/gpt-oss-120b",
                                with_fallback=False)
        self.assertIsNone(e)
        self.assertIsNone(k)

    def test_vendor_strip(self):
        # 'meta-llama/foo' sollte nach strip zu 'foo' werden
        e, k = fsm.lookup_price(self.pricing, "openrouter",
                                "openai/gpt-oss-120b",
                                with_fallback=False)
        self.assertEqual(k, "openrouter/openai/gpt-oss-120b")


class TestBuildDeployment(unittest.TestCase):
    def test_basic_openrouter(self):
        lines = fsm.build_deployment("gpt-oss-120b", "openrouter",
                                      "openai/gpt-oss-120b:free")
        text = "".join(lines)
        self.assertIn("- model_name: gpt-oss-120b", text)
        self.assertIn("model: openrouter/openai/gpt-oss-120b:free", text)
        self.assertIn("api_key: os.environ/OPENROUTER_API_KEY", text)

    def test_nvidia_double_openai(self):
        lines = fsm.build_deployment("foo", "nvidia", "openai/gpt-oss-120b")
        text = "".join(lines)
        # openai/openai/... ist die NVIDIA-Konvention
        self.assertIn("model: openai/openai/gpt-oss-120b", text)
        self.assertIn("api_key: os.environ/NVIDIA_API_KEY", text)
        self.assertIn("api_base: https://integrate.api.nvidia.com/v1", text)

    def test_ovhcloud_anonymous(self):
        lines = fsm.build_deployment("foo", "ovhcloud", "gpt-oss-120b")
        text = "".join(lines)
        # OVHcloud ist "required=False" -- wenn der User die Env-Variable
        # setzt (z.B. fuer hoehere Limits), wird sie benutzt.
        # Im anonymen Fall rendert render-config.py spaeter "" hin.
        self.assertIn("api_key: os.environ/OVHCLOUD_API_KEY", text)
        self.assertIn("api_base: https://oai.endpoints.kepler.ai.cloud.ovh.net/v1", text)

    def test_cloudflare_uses_api_base_env(self):
        lines = fsm.build_deployment("foo", "cloudflare", "@cf/openai/foo")
        text = "".join(lines)
        self.assertIn("api_key: os.environ/CLOUDFLARE_API_KEY", text)
        self.assertIn("api_base: os.environ/CLOUDFLARE_API_BASE", text)


class TestProviderToLitellmMapping(unittest.TestCase):
    def test_uses_centralized_config(self):
        # Wenn providers_config.py geaendert wird, muss die Map mitziehen
        for name in fsm.PROVIDER_CONFIGS:
            with self.subTest(provider=name):
                self.assertIn(name, fsm.PROVIDER_TO_LITELLM)


if __name__ == "__main__":
    unittest.main()
