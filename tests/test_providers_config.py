"""Tests for providers_config.py."""
import unittest

from providers_config import PROVIDERS, ProviderConfig, get


class TestProviderConfigShape(unittest.TestCase):
    def test_all_providers_have_required_fields(self):
        for name, p in PROVIDERS.items():
            with self.subTest(provider=name):
                self.assertIsInstance(p, ProviderConfig)
                self.assertTrue(p.name)
                self.assertTrue(p.prefix)
                self.assertGreater(p.rpm, 0)
                self.assertGreater(p.tpm, 0)
                self.assertTrue(p.litellm_key)
                self.assertIn(p.prefix, {"openrouter", "cerebras", "groq",
                                          "cloudflare", "gemini", "openai",
                                          "mistral", "cohere", "huggingface",
                                          "zai", "elevenlabs"})
                # Either env_var or anonymous (required=False)
                if p.required:
                    self.assertIsNotNone(p.env_var,
                        f"{name} is required=True but env_var=None")
                if p.api_base_env is None and p.needs_api_base:
                    self.assertIsNotNone(p.api_base_static,
                        f"{name} needs api_base but has neither env nor static")

    def test_unique_names(self):
        names = [p.name for p in PROVIDERS.values()]
        self.assertEqual(len(names), len(set(names)), "duplicate provider names")

    def test_unique_litellm_keys(self):
        keys = [p.litellm_key for p in PROVIDERS.values()]
        self.assertEqual(len(keys), len(set(keys)),
            "duplicate LiteLLM keys")

    def test_get_unknown_raises(self):
        with self.assertRaises(KeyError):
            get("does-not-exist")


class TestOVHcloudAnonymous(unittest.TestCase):
    def test_ovhcloud_is_optional(self):
        ovh = get("ovhcloud")
        self.assertFalse(ovh.required, "OVHcloud must be optional (anonymous free tier)")
        self.assertEqual(ovh.env_var, "OVHCLOUD_API_KEY")
        self.assertIsNotNone(ovh.api_base_static)

    def test_all_other_required(self):
        for name, p in PROVIDERS.items():
            if name == "ovhcloud":
                continue
            with self.subTest(provider=name):
                self.assertTrue(p.required,
                    f"{name} should be required=True (no anonymous tier)")


class TestProviderLookup(unittest.TestCase):
    def test_find_nvidia_by_double_openai(self):
        # 'openai/openai/<model>' is the NVIDIA convention
        nvidia = PROVIDERS["nvidia"]
        self.assertEqual(nvidia.prefix, "openai")
        self.assertTrue(nvidia.vendor_in_path)
        self.assertEqual(nvidia.name, "nvidia")

    def test_poolside_openai_compatible_base(self):
        poolside = PROVIDERS["poolside"]
        self.assertEqual(poolside.prefix, "openai")
        self.assertEqual(poolside.env_var, "POOLSIDE_API_KEY")
        self.assertEqual(poolside.api_base_static, "https://inference.poolside.ai/v1")
        self.assertTrue(poolside.vendor_in_path)

    def test_hetzner_openai_compatible_base(self):
        hetzner = PROVIDERS["hetzner"]
        self.assertEqual(hetzner.prefix, "openai")
        self.assertEqual(hetzner.env_var, "HETZNER_VLLM_API_KEY")
        self.assertEqual(
            hetzner.api_base_static,
            "https://inference.hetzner.com/api/v1",
        )
        self.assertFalse(hetzner.vendor_in_path)

    def test_zai_and_elevenlabs_native_providers(self):
        zai = PROVIDERS["zai"]
        elevenlabs = PROVIDERS["elevenlabs"]
        self.assertEqual(zai.prefix, "zai")
        self.assertEqual(zai.env_var, "ZAI_API_KEY")
        self.assertFalse(zai.needs_api_base)
        self.assertEqual(elevenlabs.prefix, "elevenlabs")
        self.assertEqual(elevenlabs.env_var, "ELEVENLABS_API_KEY")
        self.assertFalse(elevenlabs.needs_api_base)

    def test_opencode_and_ovhcloud_share_openai_prefix(self):
        # Both use 'openai/<ModelName>' -- discriminated via api_base
        opencode = PROVIDERS["opencode-zen"]
        ovh = PROVIDERS["ovhcloud"]
        self.assertEqual(opencode.prefix, "openai")
        self.assertEqual(ovh.prefix, "openai")
        self.assertNotEqual(opencode.api_base_static, ovh.api_base_static)
        self.assertFalse(opencode.vendor_in_path)
        self.assertFalse(ovh.vendor_in_path)


if __name__ == "__main__":
    unittest.main()
