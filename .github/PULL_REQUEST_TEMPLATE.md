## What Changes?

Short description of the change (1–3 sentences). Link relevant issues
with `Closes #123` or `Fixes #456`.

## Why?

Motivation, context, related issues. Why is this change needed?

## Test Plan

How was the change tested?

- [ ] `make test` is green
- [ ] `make render-config` runs error-free
- [ ] `python3 find-shared-models.py --no-pricing` shows no unwanted
      diff hints
- [ ] Manual smoke test (if applicable):
      `curl -X POST http://localhost:4000/v1/chat/completions …`

## Checklist

- [ ] **Tests** green (`make test`)
- [ ] **render-config** runs (`make render-config`)
- [ ] **Docs updated** (`README.md` / `AGENTS.md` / `PRICING.md`,
      if providers/models/env vars changed)
- [ ] **`config.template.yaml`** edited (not `config.yaml` directly!)
- [ ] **Multi-instance** regenerated if applicable
      (`cd multi-instance && python3 generate-config.py`)
- [ ] **Commit message** follows Conventional Commits
      (`feat: …`, `fix: …`, `docs: …`, `test: …`, `chore: …`)
- [ ] **No secrets** in the diff (no API keys, no tokens)
- [ ] **No external dependencies** added (stdlib only)

## Screenshots / Logs

Attach here if relevant.
