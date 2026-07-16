"""Tests fuer find-shared-models.py."""
import unittest

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


class TestPrettyModelName(unittest.TestCase):
    """Regression: normalize()'s STOPWORDS-Filter ist fuer die GRUPPIERUNG
    gedacht und zu aggressiv fuer den finalen model_name -- "deepseek-v4-pro"
    wurde dadurch zu "v4", "moonshotai/Kimi-K2.5" zu "k2-5". Live beobachtet
    beim Sync vom 2026-07-16 (Modelle 'v4', 'k2-5', 'k2-7-code' im Template)."""

    def test_strips_vendor_path_prefix_not_vendor_word(self):
        # Vendor-Praefix (vor dem letzten "/") faellt weg, aber "deepseek"
        # im eigentlichen Modellnamen bleibt (kein Stopword-Filter mehr).
        self.assertEqual(fsm.pretty_model_name("deepseek-ai/DeepSeek-V4-Pro"),
                          "deepseek-v4-pro")
        self.assertEqual(fsm.pretty_model_name("deepseek-v4-pro"),
                          "deepseek-v4-pro")

    def test_keeps_dots_matching_repo_convention(self):
        # Repo-Konvention: Minor-Versionen behalten den Punkt (kimi-k2.6,
        # mistral-small-3.2), werden nicht zu Bindestrichen.
        self.assertEqual(fsm.pretty_model_name("moonshotai/Kimi-K2.5"),
                          "kimi-k2.5")
        self.assertEqual(fsm.pretty_model_name("moonshotai/Kimi-K2.7-Code"),
                          "kimi-k2.7-code")

    def test_strips_free_tag_suffix(self):
        self.assertEqual(fsm.pretty_model_name("openai/gpt-oss-120b:free"),
                          "gpt-oss-120b")

    def test_lowercased(self):
        self.assertEqual(fsm.pretty_model_name("Qwen/Qwen3-32B"), "qwen3-32b")

    def test_no_path_prefix(self):
        self.assertEqual(fsm.pretty_model_name("whisper-large-v3"),
                          "whisper-large-v3")


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


class TestPaidVendorFilter(unittest.TestCase):
    """Aggregatoren (OpenCode Zen, LLM7.io) mischen echte Open-Weight-Modelle
    mit Zugriff auf kostenpflichtige Flaggschiff-APIs unter deren Marken.
    Diese duerfen nie automatisch als 'free' uebernommen werden."""

    def test_denies_known_paid_flagships_regardless_of_provider(self):
        denied = [
            "claude-opus-4-8", "claude-sonnet-5", "claude-fable-5",
            "anthropic/claude-3-opus",
            "gpt-5.4", "gpt-5.4-mini", "gpt-5", "gpt-5-nano", "gpt-5-codex",
            "gpt-4", "gpt-4o", "openai/gpt-4-turbo",
            "gemini-3.5-flash", "gemini-3-flash-preview", "google/gemini-2.0",
            "grok-4.5", "grok-build-0.1", "x-ai/grok-2",
        ]
        # Diese Vendoren veroeffentlichen NIE offene Gewichte -> Deny ueberall,
        # auch ohne provider-Angabe und auch auf einem Open-Weight-Host wie HF.
        for m in denied:
            with self.subTest(model=m):
                self.assertTrue(fsm.is_paid_vendor_model(m))
                self.assertTrue(fsm.is_paid_vendor_model(m, "huggingface"))
                self.assertTrue(fsm.is_paid_vendor_model(m, "opencode-zen"))

    def test_denies_ambiguous_vendors_only_on_aggregators(self):
        # GLM/MiniMax veroeffentlichen TEILWEISE offene Gewichte -- nur bei
        # den API-Aggregatoren (wo unklar ist, ob's der offene Checkpoint
        # oder die kostenpflichtige Flaggschiff-API ist) wird gefiltert.
        for m in ["glm-5", "glm-5.1", "glm-5.2", "minimax-m2.7", "minimax-m3", "MiniMax-Text-01"]:
            with self.subTest(model=m):
                self.assertTrue(fsm.is_paid_vendor_model(m, "opencode-zen"))
                self.assertTrue(fsm.is_paid_vendor_model(m, "llm7io"))
                # Auf HuggingFace koennen nur echte Checkpoints liegen ->
                # nicht gefiltert.
                self.assertFalse(fsm.is_paid_vendor_model(m, "huggingface"))
                # Ohne provider-Angabe (z.B. Stale-Check) ebenfalls nicht --
                # die Ambiguitaet betrifft nur die Aggregatoren.
                self.assertFalse(fsm.is_paid_vendor_model(m))

    def test_allows_established_open_weight_models(self):
        allowed = [
            "gpt-oss-120b", "gpt-oss-20b", "gpt-oss-safeguard-20b", "gpt-oss:20b",
            "openai/gpt-oss-120b",
            "gemma-4-26b-a4b-it", "gemma-4-31b-it", "google/gemma-2-9b-it",
            "moonshotai/Kimi-K2.6", "kimi-k2.6", "kimi-k2.5",
            "meta-llama/Llama-3.3-70B-Instruct", "mistral-large",
            "deepseek-v4-flash", "deepseek-ai/DeepSeek-V4-Pro",
            "Qwen/Qwen3-32B", "nvidia/Nemotron-3-Nano-30B-A3B",
            "command-r-plus", "codestral-latest", "whisper-large-v3",
        ]
        for m in allowed:
            with self.subTest(model=m):
                self.assertFalse(fsm.is_paid_vendor_model(m, "huggingface"))
                self.assertFalse(fsm.is_paid_vendor_model(m, "opencode-zen"))


class TestHttpGetJsonUserAgent(unittest.TestCase):
    """Regression: Cerebras/Groq/OpenCode Zen sitzen hinter Cloudflares
    Bot-Schutz, der urllib's Default-User-Agent mit 403 ("error code: 1010",
    ein WAF-Block, kein Auth-Fehler) blockiert. Ein browser-aehnlicher
    User-Agent muss auf jedem Request gesetzt werden."""

    def test_default_user_agent_is_sent(self):
        import io
        import unittest.mock as mock

        captured = {}

        # http_get_json nutzt `with urlopen(...) as resp`, also braucht das
        # Fake ein __enter__/__exit__ (io.BytesIO allein reicht nicht).
        class FakeResp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=30):
            captured["headers"] = dict(req.header_items())
            return FakeResp(b'{"data": []}')

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            fsm.http_get_json("https://example.invalid/v1/models", {"Authorization": "Bearer x"})

        self.assertIn("User-agent", captured["headers"])
        self.assertEqual(captured["headers"]["User-agent"], fsm.DEFAULT_USER_AGENT)

    def test_caller_header_not_overridden(self):
        import io
        import unittest.mock as mock

        captured = {}

        class FakeResp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=30):
            captured["headers"] = dict(req.header_items())
            return FakeResp(b'{"data": []}')

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            fsm.http_get_json("https://example.invalid", {"User-Agent": "custom/1.0"})

        self.assertEqual(captured["headers"]["User-agent"], "custom/1.0")


class TestOpenRouterFreeFilter(unittest.TestCase):
    """OpenRouter listet den Gesamtkatalog — nur Free-Modelle duerfen durch,
    sonst kann --apply ein PAID-Modell in die Config schreiben."""

    def test_filters_paid_models(self):
        data = {"data": [
            {"id": "openai/gpt-oss-120b:free",
             "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "zero-priced/model",
             "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "anthropic/claude-paid",
             "pricing": {"prompt": "0.000003", "completion": "0.000015"}},
            {"id": "broken/pricing", "pricing": {"prompt": "n/a"}},
            {"id": "no-pricing-field"},
        ]}
        out = fsm._filter_free_openrouter(data)
        self.assertIn("openai/gpt-oss-120b:free", out)
        self.assertIn("zero-priced/model", out)
        self.assertNotIn("anthropic/claude-paid", out)
        self.assertNotIn("broken/pricing", out)
        # Kein pricing-Feld -> prompt/completion 0 -> gilt als free
        self.assertIn("no-pricing-field", out)

    def test_free_suffix_always_included(self):
        data = {"data": [
            {"id": "x/y:free", "pricing": {"prompt": "0.001", "completion": "0.001"}},
        ]}
        self.assertEqual(fsm._filter_free_openrouter(data), ["x/y:free"])


class TestCohereModelParsing(unittest.TestCase):
    """Regression: fruehere Version sammelte die ENDPOINT-Namen
    ("chat"/"embed") statt der Modellnamen ein."""

    def test_parses_model_names_not_endpoints(self):
        data = {"models": [
            {"name": "command-r-plus", "endpoints": ["generate", "chat"]},
            {"name": "embed-english-v3.0", "endpoints": ["embed"]},
            {"name": "command-a-03-2025", "endpoints": ["chat"]},
        ]}
        out = fsm._parse_cohere_models(data)
        self.assertEqual(out, ["command-r-plus", "command-a-03-2025"])
        self.assertNotIn("chat", out)
        self.assertNotIn("embed", out)

    def test_models_without_endpoints_kept(self):
        data = {"models": [{"name": "command-r"}]}
        self.assertEqual(fsm._parse_cohere_models(data), ["command-r"])


class TestGoogleModelParsing(unittest.TestCase):
    def test_filters_non_chat_models(self):
        data = {"models": [
            {"name": "models/gemma-4-31b-it",
             "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/embedding-001",
             "supportedGenerationMethods": ["embedContent"]},
            {"name": "models/no-methods-field"},
        ]}
        out = fsm._parse_google_models(data)
        self.assertEqual(out, ["gemma-4-31b-it", "no-methods-field"])


class TestGithubModelParsing(unittest.TestCase):
    def test_handles_bare_list_response(self):
        data = [{"name": "Meta-Llama-3.3-70B-Instruct"}, {"id": "Mistral-large-2411"}]
        out = fsm._parse_github_models(data)
        self.assertEqual(out, ["Meta-Llama-3.3-70B-Instruct", "Mistral-large-2411"])

    def test_handles_dict_response(self):
        data = {"data": [{"id": "model-a"}]}
        self.assertEqual(fsm._parse_github_models(data), ["model-a"])


class TestParseConfigBlockBoundaries(unittest.TestCase):
    """Regression: parse_config() darf beim Block-Ende NIE ueber die
    Leerzeile hinaus in den naechsten Kommentar-Header hineinlesen. Sonst
    wird line_end zu gross berechnet und apply_to_config() fuegt neue
    Deployments MITTEN in den falsch begrenzten Vorgaenger-Block ein
    (live beobachtet: deepseek-r1-0528 (llm7io) wurde durch eine neue
    gemma-4-31b-it-Insertion zerrissen, weil der HF-Nachbar-Block faelschlich
    bis in den Kommentar-Header von 'qwen3-235b' hinein geparst wurde)."""

    def _write(self, tmpdir, text):
        from pathlib import Path
        p = Path(tmpdir) / "config.yaml"
        p.write_text(text)
        return p

    def test_block_end_stops_at_blank_line_before_comment_header(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            text = (
                "model_list:\n"
                "\n"
                "  - model_name: deepseek-r1-0528\n"
                "    litellm_params:\n"
                "      model: openai/deepseek-r1-0528\n"
                "      api_key: unused\n"
                "      tpm: 200000\n"
                "      rpm: 40\n"
                "    model_info:\n"
                "      input_cost_per_token: 0\n"
                "      output_cost_per_token: 0\n"
                "      mode: chat\n"
                "\n"
                "  - model_name: deepseek-r1-0528\n"
                "    litellm_params:\n"
                "      model: huggingface/deepseek-ai/DeepSeek-R1-0528\n"
                "      api_key: hf-test\n"
                "      tpm: 200000\n"
                "      rpm: 30\n"
                "    model_info:\n"
                "      input_cost_per_token: 0\n"
                "      output_cost_per_token: 0\n"
                "      mode: chat\n"
                "\n"
                "  # ===========================================================================\n"
                "  # qwen3-235b  – 2 FREE PROVIDERS\n"
                "  # ===========================================================================\n"
                "  - model_name: qwen3-235b\n"
                "    litellm_params:\n"
                "      model: openai/qwen3-235b\n"
                "      api_key: unused\n"
                "\n"
                "router_settings:\n"
                "  routing_strategy: usage-based-routing-v2\n"
            )
            p = self._write(d, text)
            lines, ml_start, ml_end, existing = fsm.parse_config(p)
            entries = existing["deepseek-r1-0528"]
            self.assertEqual(len(entries), 2)
            hf_entry = next(e for e in entries if e["provider"] == "huggingface")
            # line_end MUSS bei "mode: chat" enden (12 Zeilen nach dem
            # Leerzeilen-Trenner), NICHT bei den Kommentar-Header-Zeilen von
            # qwen3-235b.
            self.assertEqual(lines[hf_entry["line_end"]].strip(), "mode: chat")
            self.assertNotIn("qwen3-235b", lines[hf_entry["line_end"]])


class TestApplyToConfigOrdering(unittest.TestCase):
    """Regression: apply_to_config() muss new_blocks (komplett neue
    model_names) VOR den Insertions in bestehende Bloecke einfuegen. ml_end
    wird einmalig aus dem unveraenderten Text berechnet -- wuerden zuerst
    die Insertions angewendet, waere der Index bei der new_blocks-Splice
    stale und die neuen Bloecke landeten mitten im model_list statt am
    Ende (live beobachtet: zerrissener deepseek-r1-0528-Block)."""

    def _write_template(self, tmpdir):
        from pathlib import Path
        p = Path(tmpdir) / "tmpl.yaml"
        p.write_text(
            "model_list:\n"
            "\n"
            "  - model_name: existing-a\n"
            "    litellm_params:\n"
            "      model: openrouter/existing-a\n"
            "      api_key: unused\n"
            "      tpm: 1\n"
            "      rpm: 1\n"
            "    model_info:\n"
            "      input_cost_per_token: 0\n"
            "      output_cost_per_token: 0\n"
            "      mode: chat\n"
            "\n"
            "  - model_name: existing-a\n"
            "    litellm_params:\n"
            "      model: groq/existing-a\n"
            "      api_key: unused\n"
            "      tpm: 1\n"
            "      rpm: 1\n"
            "    model_info:\n"
            "      input_cost_per_token: 0\n"
            "      output_cost_per_token: 0\n"
            "      mode: chat\n"
            "\n"
            "  # ===========================================================================\n"
            "  # existing-b  – 2 FREE PROVIDERS\n"
            "  # ===========================================================================\n"
            "  - model_name: existing-b\n"
            "    litellm_params:\n"
            "      model: mistral/existing-b\n"
            "      api_key: unused\n"
            "    model_info:\n"
            "      input_cost_per_token: 0\n"
            "      output_cost_per_token: 0\n"
            "      mode: chat\n"
            "\n"
            "router_settings:\n"
            "  routing_strategy: usage-based-routing-v2\n"
            "  fallbacks:\n"
            "    - {\"existing-a\": [\"existing-b\"]}\n"
        )
        return p

    def test_new_and_existing_additions_do_not_corrupt_structure(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            p = self._write_template(d)
            plan = [
                # Neuer Provider fuer ein BESTEHENDES model_name (Insertion)
                {"model_name": "existing-a", "provider": "cohere",
                 "model_id": "existing-a", "ic": 0.0, "oc": 0.0, "action": "add"},
                # Komplett NEUES model_name (new_blocks)
                {"model_name": "brand-new", "provider": "huggingface",
                 "model_id": "org/brand-new", "ic": 0.0, "oc": 0.0, "action": "add"},
            ]
            added, _costs, _fallbacks = fsm.apply_to_config(p, plan, {}, {}, pricing=None)
            self.assertEqual(added, 2)

            result_text = p.read_text()
            # Kein Deployment-Block darf abgeschnitten sein: jedes
            # 'litellm_params:' muss noch sein zugehoeriges 'model_info:'
            # mit 'mode: chat' im selben Block haben, bevor der naechste
            # '- model_name:'/'router_settings:' beginnt.
            lines = result_text.splitlines(keepends=True)
            ml_start, ml_end = fsm._find_model_list_bounds(lines)
            existing = fsm._scan_existing_blocks(lines, ml_start, ml_end)

            self.assertIn("existing-a", existing)
            self.assertIn("existing-b", existing)
            self.assertIn("brand-new", existing)
            self.assertEqual(len(existing["existing-a"]), 3)  # openrouter+groq+cohere
            self.assertEqual({e["provider"] for e in existing["existing-a"]},
                              {"openrouter", "groq", "cohere"})

            # Jeder gescannte Block muss vollstaendig sein: model_info.mode
            # ist das LETZTE Feld, das build_deployment() schreibt. Fehlt
            # es, wurde der Block von einer Einfuegung abgeschnitten (die
            # blosse Anwesenheit von "model:" reicht NICHT als Check, da
            # diese Zeile schon frueh im Block steht und auch in
            # abgeschnittenen Bloecken vorhanden ist).
            for mn, entries in existing.items():
                for e in entries:
                    block_text = "".join(lines[e["line_start"]:e["line_end"] + 1])
                    self.assertIn("mode: chat", block_text,
                                  f"{mn}/{e['provider']}: Block wirkt abgeschnitten "
                                  f"(model_info.mode fehlt)")

            # router_settings + die urspruengliche Fallback-Chain muessen
            # unversehrt und NACH dem model_list stehen.
            self.assertIn("router_settings:", result_text)
            self.assertIn('"existing-a": ["existing-b"]', result_text)
            router_idx = result_text.index("router_settings:")
            brand_new_idx = result_text.index("brand-new")
            self.assertLess(brand_new_idx, router_idx,
                             "neuer Block muss VOR router_settings stehen")

            # Der urspruengliche Kommentar-Header von existing-b (oeffnende
            # Trennlinie + Titel + schliessende Trennlinie) darf nicht durch
            # neue Bloecke auseinandergerissen werden -- er muss als
            # zusammenhaengender 4-Zeilen-Block direkt vor dessen
            # '- model_name:'-Zeile stehen. (Bei der fehlerhaften Einfuege-
            # Reihenfolge blieb genau die OEFFNENDE Trennlinie zurueck und
            # wurde vom Rest des Headers getrennt -- die Block-
            # Vollstaendigkeits-Checks oben erkennen das nicht, da der
            # Blockinhalt selbst intakt bleibt, nur der davorstehende
            # Header zerrissen wird.)
            self.assertIn(
                "  # ===========================================================================\n"
                "  # existing-b  – 2 FREE PROVIDERS\n"
                "  # ===========================================================================\n"
                "  - model_name: existing-b\n",
                result_text,
                "Kommentar-Header von existing-b wurde durch neue Bloecke zerrissen",
            )


class TestGenerateApplyPlan(unittest.TestCase):
    """Regression: Gruppen sind normalisiert benannt ("3-3-70b"), das
    Template nutzt sprechende Namen ("llama-3.3-70b-instruct"). Ohne
    Mapping wurden bestehende Deployments als "add" unter dem
    normalisierten Namen geplant -> Duplikat-Bloecke."""

    def _existing(self):
        return {
            "llama-3.3-70b-instruct": [
                {"provider": "openrouter",
                 "model_id": "openrouter/meta-llama/llama-3.3-70b-instruct:free",
                 "ic": 0.0, "oc": 0.0, "line_start": 0, "line_end": 0},
            ],
        }

    def test_existing_deployment_is_skipped_not_added(self):
        group_norm = fsm.normalize("meta-llama/llama-3.3-70b-instruct:free")
        groups = {group_norm: {
            "openrouter": ["meta-llama/llama-3.3-70b-instruct:free"],
        }}
        plan = fsm.generate_apply_plan(groups, {}, self._existing(), None)
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["action"], "skip")
        # Und unter dem TEMPLATE-Namen, nicht dem normalisierten
        self.assertEqual(plan[0]["model_name"], "llama-3.3-70b-instruct")

    def test_new_provider_added_under_template_name(self):
        group_norm = fsm.normalize("meta-llama/llama-3.3-70b-instruct:free")
        groups = {group_norm: {
            "openrouter": ["meta-llama/llama-3.3-70b-instruct:free"],
            "groq": ["llama-3.3-70b-versatile"],
        }}
        plan = fsm.generate_apply_plan(groups, {}, self._existing(), None)
        adds = [p for p in plan if p["action"] == "add"]
        self.assertEqual(len(adds), 1)
        self.assertEqual(adds[0]["provider"], "groq")
        self.assertEqual(adds[0]["model_name"], "llama-3.3-70b-instruct")

    def test_globally_existing_deployment_never_readded(self):
        # Gleiches Deployment taucht in einer ANDERS normalisierten Gruppe
        # auf -> darf trotzdem nicht erneut vorgeschlagen werden.
        groups = {"some-other-norm": {
            "openrouter": ["meta-llama/llama-3.3-70b-instruct:free"],
        }}
        plan = fsm.generate_apply_plan(groups, {}, self._existing(), None)
        self.assertTrue(all(p["action"] == "skip" for p in plan))

    def test_new_group_gets_pretty_name_not_raw_grouping_key(self):
        # Regression: eine komplett NEUE Gruppe (kein existing-Match) bekam
        # frueher den aggressiv STOPWORDS-bereinigten Grouping-Key als
        # model_name ("v4" statt "deepseek-v4-pro"). generate_apply_plan
        # muss stattdessen pretty_model_name() auf einer Original-ID
        # anwenden.
        group_norm = fsm.normalize("deepseek-v4-pro")
        self.assertEqual(group_norm, "v4")  # zur Doku: das war der Bug
        groups = {group_norm: {
            "opencode-zen": ["deepseek-v4-pro"],
            "huggingface": ["deepseek-ai/DeepSeek-V4-Pro"],
        }}
        plan = fsm.generate_apply_plan(groups, {}, {}, None)
        adds = [p for p in plan if p["action"] == "add"]
        self.assertEqual(len(adds), 2)
        for p in adds:
            self.assertEqual(p["model_name"], "deepseek-v4-pro")
            self.assertNotEqual(p["model_name"], "v4")

    def test_new_kimi_group_keeps_dotted_version(self):
        group_norm = fsm.normalize("moonshotai/Kimi-K2.5")
        groups = {group_norm: {
            "opencode-zen": ["kimi-k2.5"],
            "huggingface": ["moonshotai/Kimi-K2.5"],
        }}
        plan = fsm.generate_apply_plan(groups, {}, {}, None)
        adds = [p for p in plan if p["action"] == "add"]
        self.assertEqual(len(adds), 2)
        self.assertTrue(all(p["model_name"] == "kimi-k2.5" for p in adds))


class TestNativeModelId(unittest.TestCase):
    def test_prefix_stripping(self):
        cases = {
            "openrouter/openai/gpt-oss-120b:free": "openai/gpt-oss-120b:free",
            "cerebras/gpt-oss-120b": "gpt-oss-120b",
            "openai/openai/gpt-oss-120b": "openai/gpt-oss-120b",
            "huggingface/meta-llama/Llama-3.3-70B-Instruct": "meta-llama/Llama-3.3-70B-Instruct",
            "cloudflare/@cf/openai/gpt-oss-120b": "@cf/openai/gpt-oss-120b",
            "no-prefix": "no-prefix",
        }
        for model_id, expected in cases.items():
            with self.subTest(model_id=model_id):
                self.assertEqual(fsm._native_model_id(model_id), expected)


class TestFindStaleDeployments(unittest.TestCase):
    def _template(self, tmpdir):
        from pathlib import Path
        p = Path(tmpdir) / "tmpl.yaml"
        p.write_text(
            "model_list:\n"
            "\n"
            "  - model_name: gpt-oss-120b\n"
            "    litellm_params:\n"
            "      model: cerebras/gpt-oss-120b\n"
            "      api_key: {{CEREBRAS_API_KEY}}\n"
            "\n"
            "  - model_name: gpt-oss-120b\n"
            "    litellm_params:\n"
            "      model: groq/openai/gpt-oss-120b\n"
            "      api_key: {{GROQ_API_KEY}}\n"
            "\n"
            "  - model_name: openrouter-free\n"
            "    litellm_params:\n"
            "      model: openrouter/openrouter/free\n"
            "      api_key: {{OPENROUTER_API_KEY}}\n"
        )
        return p

    def test_detects_missing_model(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tmpl = self._template(d)
            raw = {
                "cerebras": ["llama-4-maverick"],          # gpt-oss fehlt -> stale
                "groq": ["openai/gpt-oss-120b"],           # vorhanden
                "openrouter": ["whatever:free"],           # exempt (openrouter-free)
            }
            stale = fsm.find_stale_deployments(tmpl, raw, partial=set())
            self.assertEqual(len(stale), 1)
            self.assertEqual(stale[0]["provider"], "cerebras")
            self.assertEqual(stale[0]["native_id"], "gpt-oss-120b")

    def test_skips_partial_and_empty_and_failed_catalogs(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tmpl = self._template(d)
            raw = {
                "cerebras": [],                      # leer -> uebersprungen
                "groq": ["something-else"],          # partial -> uebersprungen
                # openrouter fehlt (Fetch fehlgeschlagen) -> uebersprungen
            }
            stale = fsm.find_stale_deployments(tmpl, raw, partial={"groq"})
            self.assertEqual(stale, [])

    def test_case_insensitive_match(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tmpl = self._template(d)
            raw = {"cerebras": ["GPT-OSS-120B"]}
            stale = fsm.find_stale_deployments(tmpl, raw, partial=set())
            self.assertEqual(stale, [])


if __name__ == "__main__":
    unittest.main()
