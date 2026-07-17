# Contributing to `litellm-free-models`

Thanks for your interest in contributing to the project! This document
describes the workflow for issues, pull requests, and local testing.

---

## 1. Issue Workflow

Before you change code, **always open an issue first** (except for
typo fixes in docs/comments).

### Bug Reports

Use the template `.github/ISSUE_TEMPLATE/bug_report.md`. A good bug
report includes:

- A clear description of the problem
- Reproduction steps (commands, `.env` state, Docker/K8s setup)
- Expected vs. actual behavior
- Relevant log excerpts (`docker logs`, `kubectl logs`, `python3 …`)
- Environment (Python version, OS, LiteLLM version)

> **Important:** **Never post API keys!** Sanitize logs before posting
> with `sed 's/\(KEY=\).*/\1***REDACTED***/' .env` or similar.

### Feature Requests

Use `.github/ISSUE_TEMPLATE/feature_request.md`. Describe:

- What problem is being solved
- The concrete idea / mock API
- Alternatives you considered
- For new providers: free-tier link, RPM, auth method

### Configuration Questions

For "How do I configure X?" → `.github/ISSUE_TEMPLATE/config_question.md`.

---

## 2. Pull Request Workflow

```text
1.  Fork   the repo
2.  Clone  your fork
3.  Branch feat/<short-name>  or  fix/<short-name>
4.  Write  code + write tests
5.  make test              # all tests green
6.  make render-config     # pipeline runs error-free
7.  Commit with a Conventional Commits prefix
8.  Push   → open a pull request → CI must be green
```

### Branch Naming

- `feat/<name>` — new feature
- `fix/<name>` — bug fix
- `docs/<name>` — docs-only
- `chore/<name>` — refactoring, tooling
- `test/<name>` — tests only

### Commit Messages (English)

Use [Conventional Commits](https://www.conventionalcommits.org/):

```text
feat: add OVHcloud as 13th provider
fix: cloudflare deepseek-v4-flash does not exist
docs: clarify OVHcloud anonymous free tier
test: add render-config orphan-cleanup test
chore: bump litellm version in dockerfile
```

Mark breaking changes with `!`:

```text
feat!: rename openrouter-free to openrouter-default
```

---

## 3. Code Style

### Python

- **Version:** Python 3.10+ (CI tests 3.10, 3.11, 3.12, 3.13)
- **Dependencies:** **Standard library only** (`json`, `os`, `re`, `urllib`,
  `pathlib`, `argparse`, `dataclasses`, …). **No PyYAML, no requests,
  no httpx.** The project runs everywhere without `pip install`.
- **Style:** PEP 8, 4 spaces, `snake_case`, type hints
  (`from __future__ import annotations`).
- **Docstrings:** English.
- **No comments** that just repeat obvious code. Only justify
  non-obvious decisions.
- **Print instead of logging:** CLI scripts may use `print()`.

### YAML (`config.template.yaml`)

- 2-space indent
- Provider header as a `# === Provider: <Name> ===` comment
- Models sorted alphabetically by `model_name`
- Always set `rpm:` / `api_key:` explicitly
- Comments in English

### Tests

- `pytest` with filenames `test_<module>.py` in `tests/`
- Tests for **new features are mandatory**
- Existing tests must not be removed — only extended
- `make test` must stay green

---

## 4. Local Verification

Before opening a PR:

```bash
# 1. All tests green
make test

# 2. Render pipeline runs
make render-config

# 3. Dry run shows no unwanted diff
git diff config.yaml
```

CI on GitHub Actions runs **identically** (Python 3.10–3.13,
`make test` + `python3 render-config.py --dry-run`). If CI is red,
the PR won't be merged.

---

## 5. Naming Conventions

### Providers

- Key in `providers_config.py`: `lowercase`, no special characters
  (e.g. `"openrouter"`, `"ovhcloud"`, `"huggingface"`).
- Display name: official brand name (e.g. `"OpenRouter"`, `"OVHcloud"`).
- API prefix in LiteLLM: `openrouter/`, `cerebras/`, `groq/`,
  `cloudflare/`, `gemini/`, `mistral/`, `cohere/`, `huggingface/`.
  For OpenAI-compatible providers (`openai/`), the prefix is replaced
  by `api_base` (NVIDIA, GitHub Models, OpenCode Zen, LLM7.io,
  OVHcloud).

### Models

- `model_name` (LiteLLM-public): `lowercase`, hyphens
  (e.g. `gpt-oss-120b`, `llama-3.3-70b-instruct`).
- Version suffixes: `-it`, `-instruct`, `-fp8`, `-fp8-fast`.
- No provider name in the `model_name` (the provider is mapped via
  `litellm_params.model`).

### Deployments

- Exactly **one** deployment per provider per `model_name`
  (load balancing runs via `simple-shuffle`).
- Different `model_name` values allowed per provider
  (e.g. `gpt-oss-120b` from OpenRouter and `gpt-oss-120b` from OVHcloud
  → 2 deployments, 1 `model_name`).

### Fallback Chains

- Order: similar quality first, lighter models last
- Maximum 4–5 entries per chain
- Catch-all `*` as the last chain

---

## 6. What Won't Be Merged

- Providers without a genuine free tier (e.g. paid-only with a trial)
- Reverse proxies with questionable legality/reliability
  (e.g. Pollinations.ai, UncloseAI, G4F.dev)
- Code that introduces new external dependencies
- Direct changes to `config.yaml` (always edit `config.template.yaml`
  and run `make render-config`)

---

## 7. License

By contributing, you agree that your contribution will be licensed
under the project's [MIT license](./LICENSE).
