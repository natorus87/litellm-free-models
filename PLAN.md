# PLAN.md — Code-Review-Befunde & Behebungsplan

> ✅ **ABGEARBEITET am 2026-07-16** — Alle Findings 1–10, Kleinbefunde 1–6 und
> Verbesserungsvorschläge V1–V15 wurden umgesetzt (V15 als dokumentierte
> Positionierungs-Entscheidung, V13 als Budgets-/Doku-Lösung, da der
> Prometheus-Callback in aktuellen LiteLLM-OSS-Versionen enterprise-gated
> ist). Details: AGENTS.md §7/§8. Diese Datei bleibt als Review-Protokoll
> erhalten.

> **Stand: 2026-07-06** — Vollständiges Code-Review der uncommitteten Änderungen
> (Redis-Cache-Integration in Docker Compose & K8s, Entfernung von
> `gemma-3-12b-it` und `qwen3-next-80b-a3b`, zweite Provider für die
> LLM7.io-Modelle, Fallback-Updates, Doku-Anpassungen).
>
> Methode: 8 unabhängige Review-Winkel (Zeilen-Scan, entferntes Verhalten,
> Cross-File-Tracing, Reuse, Simplification, Efficiency, Altitude,
> Konventionen), danach je ein Verifizierer pro dedupliziertem Kandidaten.
> **Alle 10 Haupt-Findings wurden CONFIRMED** (Finding 6 empirisch per
> `redis-cli`-Test im Container verifiziert).

---

## Priorität 1 — Passwort-Verwaltung (Security)

### Finding 1: Multi-Instance-Compose ignoriert gesetzte Redis-Passwörter

**Datei:** `multi-instance/docker-compose.yaml:56` (+ Healthcheck Zeile 67, `environment:`-Blöcke Zeilen 89/121/154)

`REDIS_PASSWORD` aus den per-Instanz-.env-Dateien (`master/.env`, `slave1/.env`,
`slave2/.env`) ist wirkungslos: Docker Compose interpoliert
`${REDIS_PASSWORD:-…}` **zur Parse-Zeit** nur aus der Shell-Umgebung oder der
Projektverzeichnis-`.env` (`multi-instance/.env`) — nie aus per-Service
`env_file`. Zusätzlich überschreiben die expliziten `environment:`-Einträge
env_file-Werte ohnehin.

**Failure-Szenario:** Nutzer folgt den Kommentaren in den `.env.example`-Dateien
(„Must match REDIS_PASSWORD on master, slave1, slave2…") und setzt ein starkes
Passwort in allen drei Dateien. Es existiert keine `multi-instance/.env` (die
Setup-Doku erwähnt keine) → Redis startet mit
`--requirepass change-me-redis-password`, alle Container erhalten ebenfalls den
Default. Das gesetzte Passwort wird stillschweigend ignoriert; der gemeinsame
Cache läuft mit öffentlich bekanntem Default-Passwort.

**Fix-Vorschlag:**
- Eine `multi-instance/.env.example` mit `REDIS_PASSWORD` einführen (Compose
  liest die Projekt-`.env` automatisch) und die irreführenden Kommentare aus
  den drei per-Instanz-`.env.example`-Dateien entfernen.
- Alternativ hart fehlschlagen statt Default:
  `${REDIS_PASSWORD:?REDIS_PASSWORD must be set}`.

### Finding 2: `make k8s-apply` überschreibt das Redis-Secret mit dem Default-Passwort

**Datei:** `Makefile:73` + `k8s/redis-secret.yaml` + `k8s/deployment.yaml:50-63`

Drei zusammenhängende Probleme:
1. `make k8s-apply` wendet unbedingt das **committete, direkt anwendbare**
   `k8s/redis-secret.yaml` mit `stringData.redis-password:
   "change-me-redis-password"` an — und überschreibt damit ein vom Operator per
   `kubectl create secret` gesetztes starkes Passwort (genau so, wie es der
   Header der Datei selbst anweist).
2. Das bricht die Repo-Konvention: `litellm-secrets` wird nie committet,
   sondern zur Deploy-Zeit via `make k8s-secret --from-env-file=.env`
   generiert; committet werden nur `*.template`-Dateien.
3. Der neue explizite `env:`-Eintrag in `k8s/deployment.yaml` zieht
   `REDIS_PASSWORD` per `secretKeyRef` aus `litellm-redis-secret` und
   **überschreibt** damit den per `envFrom`/`litellm-secrets` aus `.env`
   kommenden Wert (explizites `env:` hat Vorrang vor `envFrom`) —
   Passwortrotation über `.env` + `make k8s-secret` hat nie Wirkung.

**Failure-Szenario:** Operator erstellt `litellm-redis-secret` mit starkem
Passwort, rollt später per `make k8s-apply` eine Config-Änderung aus → Secret
wird auf den Default zurückgesetzt; nach Pod-Neustarts WRONGPASS/NOAUTH auf
jedem Cache- und Auth-Cache-Call, bzw. Produktion läuft still mit dem
veröffentlichten Default-Passwort.

**Fix-Vorschlag:**
- `k8s/redis-secret.yaml` → `k8s/redis-secret.yaml.template` umbenennen
  (Konvention) und aus `k8s-apply` entfernen.
- Redis-Passwort in das bestehende `make k8s-secret`-Flow integrieren (z. B.
  `kubectl create secret … --from-literal=redis-password=$$REDIS_PASSWORD`
  aus `.env`), oder `REDIS_PASSWORD` direkt aus `litellm-secrets` beziehen und
  das separate Secret ganz streichen.

### Finding 3: K8s-Probes können Redis-Auth-Fehler nie erkennen

**Datei:** `k8s/redis-deployment.yaml:53-72` (identisch in `multi-instance/k8s/redis-deployment.yaml`)

Die Liveness-/Readiness-Probes rufen `redis-cli -a $(REDIS_PASSWORD) ping` auf.
Kubelet expandiert `$(VAR)` in **Probe-exec-Kommandos** aber nur für env-Vars
mit statischem `value:` — `secretKeyRef`-Variablen bleiben der Literal-String
`$(REDIS_PASSWORD)` (bekanntes Upstream-Issue kubernetes/kubernetes#40846; in
Container-`args` funktioniert die Expansion dagegen, `redis-server` selbst
bekommt also das echte Passwort).

**Empirisch verifiziert** (redis:7-alpine): Die Probe authentifiziert mit dem
Literal-String, erhält NOAUTH auf das PING — und `redis-cli` exitet ohne `-e`
trotzdem mit 0. **Die Probes sind immer grün und validieren nichts.** Ein
Redis mit kaputtem Secret/Passwort wird nie erkannt.

**Fix-Vorschlag:**
```yaml
exec:
  command:
    - sh
    - -c
    - redis-cli -a "$REDIS_PASSWORD" -e ping
```
(Shell expandiert die echte Env-Var; `-e` sorgt für Exit-Code ≠ 0 bei
Error-Replies.)

---

## Priorität 2 — Betriebsrisiken

### Finding 4: Redis-Pod wird OOMKilled, sobald der Cache voll ist

**Datei:** `k8s/redis-deployment.yaml:46-52` (identisch in `multi-instance/k8s/redis-deployment.yaml`)

`resources.limits.memory: 256Mi` ist **exakt gleich** `--maxmemory 256mb`
(Redis parst das `mb`-Suffix binär) — null Headroom für
Allocator-Fragmentierung, Client-Buffer und die Copy-on-Write-Seiten des
BGSAVE-Forks (`--save 60 100` = minütlicher Snapshot). `requests.memory: 128Mi`
liegt sogar unter maxmemory.

**Failure-Szenario:** Sobald der LRU-Cache auf ~256mb gefüllt ist, treibt der
nächste BGSAVE-Fork unter Schreiblast die RSS über das cgroup-Limit → kubelet
OOMKillt den Pod, **alle** LiteLLM-Instanzen verlieren gleichzeitig den
gemeinsamen Response- und Auth-Cache, der Pod crash-loopt unter Last.

**Fix-Vorschlag:** Limit auf ≥ 2× maxmemory (z. B. `512Mi`) anheben — oder
besser: `--save ""` (keine Persistenz; ein LRU-Cache ist verzichtbar und wärmt
sich selbst wieder auf), dann entfallen Fork-COW, das 5Gi-PVC und die
`redis-data`-Volumes gleich mit (siehe Kleinbefunde).

### Finding 5: Unbedingtes `cache: true` bricht `make check-config` und `make docker-run`

**Datei:** `config.template.yaml:958-974` + `Makefile:35-40, 109-116`

Der Cache-Block mit `os.environ/REDIS_*` ist **unbedingt** ins
Single-Source-of-Truth-Template hartkodiert. Jeder Konsument der gerenderten
`config.yaml` außerhalb der aktualisierten Compose/K8s-Stacks hängt jetzt an
einem nicht erreichbaren Redis:

- `make check-config`: nacktes `docker run` nur mit gemounteter Config (keine
  REDIS_*-Env, kein Redis) → Cache-Client fällt auf localhost zurück,
  `/health/readiness` meldet unhealthy — das dokumentierte Validierungs-Target
  schlägt für eine valide Config fehl.
- `make docker-run`: `--env-file .env` mit `REDIS_HOST=redis`, außerhalb des
  Compose-Netzes unauflösbar → Connection-Error-Spam und Latenz auf jedem
  Request und jedem Virtual-Key-Lookup (`enable_redis_auth_cache`).

LiteLLM failt dabei nicht hart, sondern degradiert (lazy connect, Fehler
werden pro Request geloggt).

**Fix-Vorschlag:** `render-config.py` hat bereits den passenden
Conditional-Mechanismus (`filter_blocks` entfernt Provider-Blöcke bei leeren
API-Keys): den Cache-Block analog nur rendern, wenn `REDIS_HOST` (oder ein
dediziertes `ENABLE_REDIS_CACHE`) gesetzt ist. Zusätzlich `check-config` und
`docker-run` die REDIS_*-Variablen mitgeben oder dort explizit ohne Cache
rendern.

### Finding 6: Globaler Response-Cache ist eine stille Verhaltensänderung

**Datei:** `config.template.yaml:958-974`

Mit `cache: true`, `ttl: 3600` und `acompletion` in `supported_call_types`
liefern **identische Requests eine Stunde lang die byte-identische gecachte
Antwort** — über Master und alle Slaves hinweg. LiteLLM hasht die Call-kwargs
(model, messages, temperature, …) als Cache-Key; ein absichtlicher Re-Roll mit
gleichen Parametern (temperature > 0) trifft also den Cache.

Der Opt-out (`"cache": {"no-cache": true}` bzw. Cache-Control-Header) ist eine
LiteLLM-Extension außerhalb der OpenAI-API — Standard-Clients und
Coding-Agents senden ihn nicht. Das in AGENTS.md dokumentierte „Live-validiert
via `GET /cache/ping`" prüft nur Konnektivität, nicht diese Semantik.

**Fix-Vorschlag:** Bewusste Entscheidung treffen und dokumentieren. Optionen:
TTL deutlich senken, Cache nur für Auth (`enable_redis_auth_cache`) nutzen und
Response-Caching abschalten, oder das Verhalten + Opt-out prominent in README
und AGENTS.md dokumentieren.

### Finding 7: `REDIS_PORT` ist scheinbar konfigurierbar, wird aber ignoriert

**Datei:** `docker-compose.yaml:34-44, 86` (analog `multi-instance/docker-compose.yaml`)

`.env.example` führt `REDIS_PORT=6379` als Variable, die Proxy-Container
erhalten `REDIS_PORT=${REDIS_PORT:-6379}` und die Config nutzt
`port: os.environ/REDIS_PORT` — aber das redis-Kommando setzt nie `--port`,
Redis lauscht immer auf 6379.

**Failure-Szenario:** Nutzer setzt `REDIS_PORT=6380` → alle Proxies wählen
`redis:6380`, connection refused auf jeder Cache-Operation. Der Healthcheck
läuft im Redis-Container gegen localhost:6379 und bleibt grün — der Fehler ist
still.

**Fix-Vorschlag:** `--port "${REDIS_PORT:-6379}"` ins redis-Kommando (Command
+ Healthcheck) aufnehmen — oder die Variable aus den .env-Dateien entfernen
und als fix dokumentieren.

### Finding 8: `find-shared-models.py` hartkodiert das entfernte `gemma-3-12b-it`

**Datei:** `find-shared-models.py:964-965`

Die Auto-Apply-Logik fügt, wenn kein `"*"`-Key in den Fallbacks existiert,
eine Catch-All-Chain ein, die `gemma-3-12b-it` enthält — das Modell wurde in
diesem Diff aber komplett entfernt. `render-config.py`s
`remove_orphaned_fallbacks` validiert nur Fallback-**Keys**, nie
Chain-**Ziele**, und nimmt `"*"` explizit aus — der dangling Target würde
durchgereicht.

**Failure-Szenario:** Wird der `"*"`-Eintrag im Template je entfernt, fügt
`find-shared-models.py --apply` einen Fallback auf ein model_name mit null
Deployments wieder ein → Routing-Fehler statt Ausweichen auf
`deepseek-v4-flash`/`openrouter-free`. Aktuell schlafend (der Guard `"*"
existiert` hält), aber scharf.

**Fix-Vorschlag:** Hartkodierte Chain auf die aktuellen Modelle aktualisieren
(`gemma-4-26b-a4b-it` statt `gemma-3-12b-it`) — besser: Chain-Ziele beim
Rendern generell gegen die model_list validieren.

---

## Priorität 3 — Dokumentation

### Finding 9: AGENTS.md ist in sich widersprüchlich

**Datei:** `AGENTS.md`

- **Zeile 94 + 97:** `llama-3.3-70b-instruct` doppelt in der
  Deployment-Matrix (einmal „5-6" mit OVHcloud, einmal „5" ohne) — 23 Zeilen
  bei behaupteten 22 model_names. Die Zeile 97 ist der stale Duplikat-Rest und
  gehört gelöscht.
- **Zeilen 50, 179, 204:** alte Zahlen (118/70/24) widersprechen dem in diesem
  Diff aktualisierten Abschnitt 3 (22 model_names, 59 base + 44 Slave = 103).
- **Zeilen 150-168:** der Fallback-Beispielblock referenziert noch die
  entfernten `gemma-3-12b-it` und `qwen3-next-80b-a3b` — wer ihn kopiert,
  führt Fallbacks auf nicht existente model_names wieder ein.
- **Zeilen 183, 196:** „14 Variablen"/„alle 14 Keys" (real: 20 inkl.
  REDIS_*); die Dateistruktur listet die neuen `redis-*.yaml` nicht.

### Finding 10: README.md und multi-instance/README.md nicht mitaktualisiert

**Dateien:** `README.md`, `multi-instance/README.md`

- `README.md` Zeilen 107, 168, 316: weiterhin „24 model_names / 70
  deployments"; Zeile 32: „24+ models".
- `README.md` Zeile 178: listet das entfernte `gemma-3-12b-it`; Zeile 188:
  `qwen3-next-80b-a3b`.
- `README.md` Zeilen 192-195: LLM7.io-Modelle als Single-Provider, obwohl
  dieser Diff jeweils einen zweiten Provider ergänzt.
- `multi-instance/README.md` Zeilen 25-27, 33, 37, 135, 221, 231: weiterhin
  „118 Deployments" (real: 103).

**Failure-Szenario:** Nutzer requesten dokumentierte, aber entfernte Modelle
(laufen nur noch über den `"*"`-Catch-All oder erhalten Fehler); Operatoren,
die nach Regenerierung 103 statt 118 Deployments sehen, vermuten eine kaputte
Generierung statt der beabsichtigten Modell-Entfernung.

---

## Kleinbefunde (unterhalb des 10er-Cuts, alle verifiziert)

1. **TTL-Kommentar widerspricht Wert** — `config.template.yaml:966`: Kommentar
   sagt „5 min for in-memory tier", gesetzt ist `default_in_memory_ttl: 60`
   (= 1 min). Die „5 min" gehören vermutlich zu `user_api_key_cache_ttl: 300`.
2. **`GEMINI_API_KEY` ist tote Konfiguration** — nach Entfernen von
   `gemma-3-12b-it` nutzt kein Deployment mehr `{{GEMINI_API_KEY}}`, der Key
   wird aber weiter injiziert/dokumentiert (docker-compose.yaml:75,
   .env.example:67, beide k8s-Secret-Templates, README-Provider-Tabelle).
   `find-shared-models.py` verlangt ihn nicht hart (skippt google-ai bei
   fehlendem Key) — Aufräumen oder als „für zukünftige Syncs" kennzeichnen.
3. **5Gi-PVC + RDB-Persistenz für einen 256mb-LRU-Cache** —
   `k8s/redis-pvc.yaml` (×2) und `--save 60 100`: minütliche Fork+Disk-Writes
   für verzichtbare Cache-Daten; ~95 % des Volumes dauerhaft ungenutzt.
   Einfacher: `--save ""` + emptyDir, PVC-Dateien und Volume-Referenzen
   streichen.
4. **`supported_call_types` mit toten Einträgen** — `aembedding`/
   `atranscription` gelistet, obwohl alle 69 Deployments `mode: chat` sind.
5. **Byte-identische Redis-Manifeste doppelt** — `k8s/redis-*.yaml` vs.
   `multi-instance/k8s/redis-*.yaml`: gleicher Namespace, gleiche
   Ressourcennamen (`litellm-redis`, `redis-data`, `litellm-redis-secret`) →
   beide Apply-Pfade überschreiben sich gegenseitig, Tuning-Änderungen driften.
   Die Kustomization referenziert bereits `../namespace.yaml` und könnte
   `../../k8s/redis-*.yaml` nutzen. (Postgres ist bewusst NICHT dupliziert —
   Konventionsbruch.)
6. **`#version: "3.9"`** in `docker-compose.yaml:1` auskommentiert statt
   gelöscht; identischer 3-Zeilen-Redis-Kommentar doppelt in
   `multi-instance/k8s/secret.yaml.template` (Zeilen 96-99 + 130-133).

---

## Weitere Verbesserungsvorschläge (außerhalb des Review-Scopes)

Repo-weite Punkte, die beim Nachfassen aufgefallen sind — unabhängig vom
aktuellen Diff, aber teils direkt damit verzahnt.

### V1: `make test` maskiert Testfehler — CI kann nie rot werden

**Datei:** `Makefile:145, 148` + `.github/workflows/ci.yml:44`

`python3 -m unittest discover -s tests -v 2>&1 | tail -5` — der Exit-Code des
Targets ist der von `tail` (immer 0), nicht der von unittest; `make` nutzt
`/bin/sh` ohne `pipefail`. **Fehlschlagende Unit-Tests lassen `make test` und
damit den CI-Job trotzdem grün durchlaufen.**

**Fix:** `set -o pipefail` geht in POSIX-sh nicht — stattdessen z. B.
`@python3 -m unittest discover -s tests -v 2>&1 | tail -5; exit $${PIPESTATUS[0]}`
mit `SHELL := /bin/bash` im Makefile, oder schlicht ohne `| tail -5` laufen
lassen (CI-Logs dürfen lang sein).

### V2: `make check-config` ist unabhängig vom Redis-Thema doppelt kaputt

**Datei:** `Makefile:109-116`

1. `docker run` ohne `-p 4000:4000` → das anschließende
   `curl http://localhost:4000/health/readiness` kann den Container nie
   erreichen; das Target „validiert" gegen nichts.
2. Jede Make-Rezeptzeile läuft in einer eigenen Shell: `kill %1` in Zeile 116
   hat keine Job-Table mit dem in Zeile 111 gestarteten Prozess →
   fehlschlägt still (`|| true`), der Container läuft **verwaist weiter**.

**Fix:** Einzeiliges Rezept mit `docker run -d --name`, `-p 4000:4000`,
`curl --retry`, `docker rm -f` im `trap`/Abschluss — oder besser: LiteLLM bietet
keinen echten Dry-Run, daher YAML-Schema-Validierung lokal (siehe V4) plus
optionalem Smoke-Test.

### V3: CI ist vorhanden, aber weich gestellt — und AGENTS.md leugnet sie

**Dateien:** `.github/workflows/ci.yml`, `AGENTS.md` („Offen: ❌ Kein CI/CD")

- AGENTS.md listet „Kein CI/CD (Lint/Test-Pipeline)" als offen — **stale**:
  `ci.yml` (Test-Matrix 3.10-3.13, ruff, render-Dry-Run) und `sync-models.yml`
  existieren. Bei der Doku-Synchronisierung (Finding 9) mitkorrigieren.
- ruff ist doppelt entschärft: `pip install ruff || true` und
  `ruff check . || echo "::warning::…"` — Lint kann nie fehlschlagen.
  Entweder blockierend machen oder aus der CI entfernen (Halb-Checks
  erzeugen falsches Vertrauen).
- Kombiniert mit V1 prüft die CI effektiv nur, dass `render-config.py --dry-run`
  nicht crasht.

### V4: Keine Validierung der K8s-Manifeste und Compose-Dateien

Es gibt keinen Check, der die 13 K8s-YAMLs (+ multi-instance) oder die
Compose-Dateien validiert — genau die Dateiklasse, in der dieses Review die
meisten Fehler fand.

**Vorschlag:** In CI + pre-commit ergänzen:
- `kubeconform`/`kubectl apply --dry-run=client` über `k8s/` und
  `multi-instance/k8s/` (hätte z. B. Schema-Fehler gefangen),
- `docker compose config -q` für beide Compose-Dateien (validiert
  Interpolation und Syntax),
- `yamllint` liegt als pre-commit nahe.

### V5: Fehlende strukturelle Tests für die Config-Invarianten

`tests/` deckt die Skripte ab, aber nicht die Invarianten des Templates.
Genau die hätten mehrere Findings automatisch gefangen:

- **Fallback-Ziele existieren**: jedes Ziel in `fallbacks` /
  `context_window_fallbacks` ist ein model_name der model_list (fängt
  Finding 8 und künftige Modell-Entfernungen).
- **≥ 2-Provider-Regel**: jedes model_name außer den dokumentierten
  Ausnahmen (OpenCode Zen, Catch-All) hat ≥ 2 Deployments.
- **Doku-Sync**: Deployment-Zahlen in AGENTS.md/README gegen das Template
  zählen (fängt Findings 9/10) — oder besser die Tabelle generieren (V8).

### V6: Rolling-Tag `main-latest` überall + `imagePullPolicy: IfNotPresent`

**Dateien:** `k8s/deployment.yaml:39-40`, beide Compose-Dateien, `Makefile:112`

`ghcr.io/berriai/litellm:main-latest` ist ein täglich wanderndes Tag:
- Nicht reproduzierbar — ein Redeploy kann eine andere LiteLLM-Version ziehen
  als gestern getestet.
- Mit `IfNotPresent` läuft zudem jeder Node auf einem anderen Stand fest,
  bis das Image dort manuell erneuert wird.

**Vorschlag:** Auf ein versioniertes Tag (oder Digest) pinnen und Updates via
Dependabot/Renovate (Dependabot ist schon konfiguriert) heben.

### V7: K8s-Security-Hardening fehlt komplett

**Dateien:** `k8s/*.yaml`, `multi-instance/k8s/**`

Kein Container hat einen `securityContext` (runAsNonRoot,
readOnlyRootFilesystem, `capabilities: drop: [ALL]`, seccompProfile), es gibt
keine NetworkPolicy (Redis + Postgres sind im Namespace für jeden Pod
erreichbar — relevant, da Redis nur passwort-, Postgres default-gesichert
ist) und kein PodDisruptionBudget. Die podAntiAffinity in
`k8s/deployment.yaml` ist bei `replicas: 1` zudem wirkungslos — entweder
Replicas erhöhen (Redis-Auth-Cache macht das jetzt möglich, das ist ja der
Zweck des Diffs) oder die Affinity streichen.

### V8: AGENTS.md-Modelltabelle generieren statt pflegen

Die Deployment-Matrix wird von Hand gepflegt und ist schon beim ersten Edit
gebrochen (Finding 9). `find-shared-models.py` parst das Template bereits und
kennt die Provider-Sets pro Modell — ein `--emit-matrix`-Modus (Markdown nach
stdout oder direkt in AGENTS.md/README zwischen Marker-Kommentare) macht die
Zahlen dauerhaft korrekt. Analog die „X Variablen"-Zählungen streichen.

### V9: Gleiche Default-Passwort-Schwäche bei Postgres

**Dateien:** `docker-compose.yaml` (`POSTGRES_PASSWORD:-litellm`), K8s-Postgres

Das Review-Muster von Finding 1/2 gilt vorbestehend auch für Postgres:
Default-Credentials `litellm/litellm` als Fallback in der DATABASE_URL. Beim
Umbau des Passwort-Flows (Schritt 1) Postgres gleich mitziehen
(`:?`-Interpolation oder generierte Secrets).

### V10: Hygiene-Kleinigkeiten

- **Backup-Inflation**: 10× `config.yaml.bak.*` im Arbeitsverzeichnis
  (gitignored, aber Clutter) — `make clean`-Target bzw. Auto-Prune auf die
  letzten N Backups in `render-config.py`.
- **`make k8s-secret` kippt die komplette `.env`** (inkl. Kommentar-Kontext
  aller 20 Variablen) in `litellm-secrets` — funktioniert, aber ein
  explizite Key-Liste würde verhindern, dass lokale Zusatzvariablen im
  Cluster-Secret landen.
- **Prometheus-Annotations** ohne dokumentiertes Scrape-Setup/ServiceMonitor —
  entweder dokumentieren oder entfernen.
- **`.dockerignore`/`Dockerfile`**: prüfen, ob `config.yaml` (echte Keys!)
  versehentlich ins Build-Image kopiert werden kann — der `docker-build`-Pfad
  baut aus dem Repo-Root.

### V11: Auto-Model-Update — den Sync-Workflow von Report auf PR-Pipeline heben

**Dateien:** `.github/workflows/sync-models.yml`, `find-shared-models.py`, `.opencode/skill/sync-free-models/`

**Ist-Zustand:** Der wöchentliche Workflow erzeugt nur ein Artefakt
(`providers-overlap.txt`, 7 Tage Retention) — kein `--apply`, kein PR, keine
Benachrichtigung. Und er läuft **ohne Provider-Keys**: `find-shared-models.py`
überspringt Provider mit fehlendem Key („Key fehlt"), der CI-Report ist also
systematisch unvollständig. Effektiv existiert der Auto-Update-Pfad nur als
manueller OpenCode-Skill (`sync-free-models`).

**Vorschlag — gestufte Automatisierung (nie Auto-Merge):**
1. **Provider-Keys als GitHub Secrets** hinterlegen (Free-Tier-Keys,
   least-privilege; nur die read-only Katalog-Abfragen brauchen sie), damit
   der Report überhaupt vollständig wird.
2. **PR statt Artefakt:** Bei erkannten Änderungen `find-shared-models.py
   --apply` + `render-config.py` + `multi-instance/generate-config.py`
   ausführen und per `peter-evans/create-pull-request` einen PR öffnen —
   Overlap-Report als PR-Beschreibung, Provider-Diff als Changelog.
3. **Gates im selben Workflow:** die Invarianten-Tests aus V5
   (Fallback-Ziele existieren, ≥ 2-Provider-Regel), `make test`
   (nach V1-Fix), Manifest-/Compose-Validierung aus V4. Nur grüne PRs
   erreichen den Reviewer.
4. **Doku im selben PR:** mit dem Matrix-Generator aus V8 AGENTS.md/README
   automatisch mitregenerieren — genau die Drift aus Findings 9/10 kann dann
   nicht mehr entstehen.
5. **Flapping-Schutz:** Kataloge wackeln (Modelle erscheinen/verschwinden
   wochenweise, vgl. gemma-3-12b-it). Entfernungen erst vorschlagen, wenn ein
   Modell N aufeinanderfolgende Läufe fehlt (Zustand z. B. als committete
   Status-Datei oder via Cache-Artefakt); Neuzugänge sofort, Entfernungen
   konservativ und im PR laut markieren.
6. **Fallback ohne Keys:** Wenn Secrets fehlen, statt still unvollständig zu
   reporten ein Issue öffnen/den Run failen — der heutige Modus (leiser,
   lückenhafter Report) ist die schlechteste Variante.

**Risiken/Grenzen:** Free-Tier-Keys in CI sind ein (kleines) Leak-Risiko —
separate Keys nur für den Sync verwenden; Rate-Limits der Katalog-APIs beim
wöchentlichen Lauf sind unkritisch. Auto-Merge bleibt aus: Modell-Änderungen
betreffen Routing/Fallbacks und brauchen einen menschlichen Blick.

### V12: Die größte ungenutzte Redis-Chance — Rate-Limit-bewusstes Routing

**Datei:** `config.template.yaml:911` (`routing_strategy: simple-shuffle`)

Der Diff führt Redis ein, nutzt es aber nur für Response- und Auth-Caching.
Das Kernproblem eines **Free-Tier**-Proxys sind aber die Provider-Rate-Limits —
und genau dafür bleibt Redis ungenutzt:

- `simple-shuffle` würfelt Deployments zufällig und **ignoriert die im
  Template gepflegten `tpm`/`rpm`-Werte komplett**. Die 59 Deployments mit
  sorgfältig dokumentierten Limits (rpm: 1 bei OpenRouter bis rpm: 40 bei
  LLM7) werden gleichverteilt angesprochen — ein rpm:1-Deployment bekommt
  gleich viel Traffic wie ein rpm:40-Deployment und läuft ständig in 429s,
  die dann nur durch Retries/Fallbacks aufgefangen werden.
- Mit `routing_strategy: usage-based-routing-v2` + Redis in den
  `router_settings` (redis_host/port/password analog zu cache_params) trackt
  LiteLLM den tpm/rpm-Verbrauch **instanzübergreifend** (Master + Slaves +
  Replicas!) und routet Deployments an, die noch Budget haben — inklusive
  geteilter Cooldowns über alle Instanzen.
- Dabei prüfen: `tpm`/`rpm` liegen im Template auf Deployment-Top-Level
  (Geschwister von `litellm_params`) — für Router-Awareness gehören sie nach
  `litellm_params.tpm`/`litellm_params.rpm`. Bei simple-shuffle fällt der
  Unterschied nicht auf; beim Strategiewechsel wird er relevant.

Das wäre der Punkt, an dem der Redis-Aufwand des aktuellen Diffs den größten
funktionalen Gewinn abwirft — mehr als der Response-Cache (Finding 6 zeigt,
dass der sogar zweischneidig ist).

### V13: Observability & Alerting — nichts konfiguriert

**Dateien:** `config.template.yaml` (keine callbacks/alerting), `k8s/deployment.yaml:20-22`

Es gibt keinerlei `success_callback`/`failure_callback`, kein Alerting, keine
Budgets. Für einen Proxy, dessen Daseinszweck das Ausreizen von Free-Tiers
ist, fehlt damit genau die Sicht auf: Welche Provider werfen 429s? Welche
Deployments sind im Cooldown? Wie ist die Fallback-Quote?

- **Metriken:** Prometheus-Callback konfigurieren (prüfen, ob im
  OSS-Tier der gepinnten LiteLLM-Version enthalten — war zeitweise
  Enterprise-gated); Alternative: Spend-Logs liegen ohnehin in Postgres →
  Grafana-Dashboard direkt auf die DB. Die vorhandenen
  `prometheus.io/scrape`-Annotations sind bislang Dekoration (vgl. V10).
- **Alerting:** LiteLLM-Webhook-Alerting (z. B. Slack/Discord) für
  Provider-Ausfälle, Cooldown-Häufungen und DB-Fehler.
- **Budgets/Limits pro Virtual Key:** `max_budget`, `tpm_limit`/`rpm_limit`
  pro Key nutzen, damit ein einzelner Consumer nicht alle Free-Tiers für
  alle anderen leerzieht.

### V14: Postgres ist der einzige persistente Zustand — und hat kein Backup

**Dateien:** `k8s/postgres-pvc.yaml`, beide Compose-Dateien

Virtual Keys, Spend-Tracking und Team-/User-Zuordnungen leben ausschließlich
in Postgres. Es gibt weder einen Backup-Mechanismus (pg_dump-CronJob,
Volume-Snapshots) noch eine dokumentierte Restore-Prozedur; in Compose hängt
alles an einem lokalen Docker-Volume. Ein kaputtes PVC/Volume bedeutet:
alle ausgegebenen API-Keys sind weg, alle Clients müssen neue Keys bekommen.
Minimallösung: täglicher `pg_dump` als K8s-CronJob in ein zweites PVC (oder
Objekt-Storage) + Restore-Abschnitt im README. (Das Redis-PVC dagegen kann
weg — siehe Kleinbefund 3.)

### V15: Architekturfrage — braucht es das Master/Slave-Setup überhaupt?

**Dateien:** `multi-instance/**`

Das Multi-Instance-Setup existiert, um pro Provider 3 API-Keys zu nutzen
(3× Rate-Limit). LiteLLM kann aber **mehrere Deployments desselben Providers
mit unterschiedlichen Keys in einer einzigen Instanz** führen — dieselben
59 base Deployments einfach 3× mit key1/key2/key3 ergäben denselben Effekt
ohne: zweite Config-Pipeline (`generate-config.py`), 3 Proxy-Container,
Master-Hop (Latenz + doppelte Auth), SLAVE?_API_KEY-Verwaltung und die
gesamte multi-instance/-Duplikation (vgl. Kleinbefund 5). Mit V12
(usage-based-routing) würden die Keys sogar limit-bewusst ausbalanciert.

**Einzige echte Rechtfertigung für getrennte Instanzen:** Provider mit
**IP-basierten** Limits (OVHcloud: 2 RPM pro IP, anonym) — die profitieren
nur, wenn die Instanzen auf getrennten Egress-IPs laufen. Im
Single-Cluster-K8s-Setup (ein NAT/Egress) bringt das Master/Slave-Setup dort
aber ohnehin nichts. Empfehlung: dokumentiert entscheiden — entweder
Multi-Key-Deployments in einer Instanz (Vereinfachung) oder Multi-Instance
bewusst nur für getrennte Hosts/IPs positionieren.

---

## Vorgeschlagene Reihenfolge der Behebung

| Schritt | Findings | Aufwand |
|---|---|---|
| 1. Passwort-Flow reparieren (Compose-Projekt-.env, Secret-Template-Konvention, env-Vorrang auflösen; Postgres mitziehen) | 1, 2, V9 | mittel |
| 2. Probes fixen (`sh -c` + `-e`) | 3 | klein |
| 3. Redis-Betrieb härten (`--save ""` oder Limit 512Mi; PVC-Frage klären) | 4, Kleinbefund 3 | klein |
| 4. Cache konditional rendern + Targets `check-config`/`docker-run` reparieren | 5, V2 | mittel |
| 5. Cache-Verhalten entscheiden & dokumentieren | 6 | klein |
| 6. `REDIS_PORT` konsistent machen | 7 | klein |
| 7. `find-shared-models.py`-Hardcode aktualisieren | 8 | klein |
| 8. Doku synchronisieren (AGENTS.md inkl. CI-Status, READMEs) | 9, 10, Kleinbefunde 1, 2, V3 | mittel |
| 9. Aufräumen (Manifest-Duplikate, tote Config) | Kleinbefunde 4-6 | klein |
| 10. Test-/CI-Härtung (`make test`-Exit-Code, ruff blockierend, Manifest-Validierung, Invarianten-Tests) | V1, V3, V4, V5 | mittel |
| 11. Deployment-Härtung (Image-Pinning, securityContext, NetworkPolicy, Replicas/PDB) | V6, V7 | mittel |
| 12. Tooling-Komfort (Matrix-Generator, make clean, Secret-Key-Liste) | V8, V10 | klein |
| 13. Auto-Model-Update-Pipeline (Sync-Workflow → PR mit Gates, Flapping-Schutz, Doku-Regeneration) | V11 | mittel-groß (baut auf 10 + 12 auf) |
| 14. Rate-Limit-bewusstes Routing über Redis (usage-based-routing-v2, tpm/rpm nach litellm_params) | V12 | mittel |
| 15. Observability, Budgets & Postgres-Backup | V13, V14 | mittel |
| 16. Architektur-Entscheidung Multi-Instance vs. Multi-Key-Deployments | V15 | Evaluation |
