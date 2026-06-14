## Was ändert sich?

Kurze Beschreibung der Änderung (1–3 Sätze). Verlinke relevante Issues
mit `Closes #123` oder `Fixes #456`.

## Warum?

Motivation, Kontext, verwandte Issues. Warum ist diese Änderung nötig?

## Test-Plan

Wie wurde die Änderung getestet?

- [ ] `make test` ist grün
- [ ] `make render-config` läuft fehlerfrei
- [ ] `python3 find-shared-models.py --no-pricing` zeigt keine ungewollten
      Diff-Hinweise
- [ ] Manueller Smoke-Test (falls zutreffend):
      `curl -X POST http://localhost:4000/v1/chat/completions …`

## Checkliste

- [ ] **Tests** grün (`make test`)
- [ ] **render-config** läuft (`make render-config`)
- [ ] **Doku aktualisiert** (`README.md` / `AGENTS.md` / `PRICING.md`,
      falls Provider/Modelle/Env-Vars geändert)
- [ ] **`config.template.yaml`** bearbeitet (nicht `config.yaml` direkt!)
- [ ] **Multi-Instance** ggf. neu generiert
      (`cd multi-instance && python3 generate-config.py`)
- [ ] **Commit-Message** folgt Conventional Commits
      (`feat: …`, `fix: …`, `docs: …`, `test: …`, `chore: …`)
- [ ] **Keine Secrets** im Diff (keine API-Keys, keine Tokens)
- [ ] **Keine externen Dependencies** hinzugefügt (nur stdlib)

## Screenshots / Logs

Falls relevant, hier anhängen.
