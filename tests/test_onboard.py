"""Tests fuer onboard.py (nur die reinen Helfer, keine Interaktion/Netz)."""
import unittest

from tests._loader import load_script

ob = load_script("onboard.py")


class TestPlaceholderDetection(unittest.TestCase):
    def test_placeholders(self):
        for v in ["sk-or-v1-your-openrouter-key-here", "change-me-redis-password",
                  "github_pat_change_me", "sk-placeholder-replace-me"]:
            with self.subTest(value=v):
                self.assertTrue(ob.is_placeholder(v))

    def test_real_values(self):
        for v in ["sk-or-v1-a1b2c3d4", "gsk_zzz", "unused", ""]:
            with self.subTest(value=v):
                self.assertFalse(ob.is_placeholder(v))


class TestKeyState(unittest.TestCase):
    def test_states(self):
        self.assertEqual(ob.key_state("", "GROQ_API_KEY"), "leer")
        self.assertEqual(ob.key_state("gsk-change-me", "GROQ_API_KEY"), "platzhalter")
        self.assertEqual(ob.key_state("unused", "LLM7IO_API_KEY"), "default")
        self.assertEqual(ob.key_state("gsk_real", "GROQ_API_KEY"), "ok")


class TestEnvEditing(unittest.TestCase):
    def test_get_set_roundtrip(self):
        lines = ["# Kommentar", "FOO=alt", "", "BAR=bleibt"]
        self.assertEqual(ob.get_value(lines, "FOO"), "alt")
        ob.set_value(lines, "FOO", "neu")
        self.assertEqual(ob.get_value(lines, "FOO"), "neu")
        # Kommentare/andere Zeilen unangetastet
        self.assertEqual(lines[0], "# Kommentar")
        self.assertEqual(lines[3], "BAR=bleibt")

    def test_set_appends_missing_key(self):
        lines = ["FOO=1"]
        ob.set_value(lines, "NEU", "wert")
        self.assertIn("NEU=wert", lines)

    def test_env_dict_skips_comments(self):
        lines = ["# X=1", "A=2", "", "B='3'"]
        self.assertEqual(ob.env_dict(lines), {"A": "2", "B": "3"})


class TestMask(unittest.TestCase):
    def test_mask_never_reveals_full_value(self):
        v = "sk-or-v1-supersecretvalue123"
        m = ob.mask(v)
        self.assertNotEqual(m, v)
        self.assertNotIn("supersecret", m)
        self.assertEqual(ob.mask(""), "(leer)")


class TestProviderKeyTable(unittest.TestCase):
    def test_covers_all_provider_env_vars(self):
        """Jede in providers_config definierte Env-Var muss im Onboarding
        auftauchen (sonst kann man sie nicht gefuehrt eintragen)."""
        from providers_config import PROVIDERS
        onboard_vars = {var for var, _n, _u, _h in ob.PROVIDER_KEYS}
        for name, p in PROVIDERS.items():
            if p.env_var:
                with self.subTest(provider=name):
                    self.assertIn(p.env_var, onboard_vars)


if __name__ == "__main__":
    unittest.main()
