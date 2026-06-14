# Security Policy

## Supported Versions

Only the **latest main branch** receives security updates. Older versions
are not patched.

| Version | Supported          |
| ------- | ------------------ |
| `main`  | :white_check_mark: |
| older   | :x:                |

## Reporting a Vulnerability

Please report security issues **privately** — do **not** open a public
GitHub issue.

### Channels

- **Email:** `security@example.com` (placeholder — replace with the
  project's actual security contact)
- **GitHub Security Advisories:** Use the "Report a vulnerability" button
  on the [Security tab](../../security/advisories/new) of the repository

### What to include

- Description of the vulnerability and potential impact
- Steps to reproduce (or a proof-of-concept)
- Affected versions / commits
- Your name / handle for the advisory credits (optional)

### Response targets

- **Initial acknowledgement:** within 7 days
- **Status update / fix timeline:** within 30 days

## What to Report

| Severity | Examples                                                                                |
| -------- | --------------------------------------------------------------------------------------- |
| High     | **API-Key leaks** in committed files, logs, error messages, or rendered `config.yaml`   |
| High     | **Code-execution bugs** in `render-config.py` / `find-shared-models.py` (e.g. unsafe YAML / shell) |
| High     | **Provider-config bugs** that route traffic to a paid endpoint or wrong model           |
| Medium   | Rate-limit / quota bypasses that affect upstream providers                              |
| Medium   | SSRF / open-redirect in HTTP probes used by `find-shared-models.py`                     |
| Low      | Information disclosure (e.g. `python --version` in banner), missing input validation     |

## What NOT to Report via Security Advisories

The following are **not** security issues — please open a regular
[bug report](../../issues/new?template=bug_report.md) instead:

- Changes to a provider's **free-tier rate limits** (RPM/RPD changes by
  OpenRouter, Cerebras, Groq, etc. — these are operational, not security)
- Provider deprecations or model removals
- Documentation errors
- Feature requests
- General configuration questions

## Disclosure Policy

We follow **coordinated disclosure**:

1. Reporter contacts us privately
2. We acknowledge and start investigating
3. We develop and test a fix
4. We release the fix and publish a CVE / GHSA advisory
5. After the fix is public, the original report can be disclosed

Please give us a reasonable time (typically 90 days) before public disclosure.

## Acknowledgements

We are grateful to the security community for responsible disclosure.
Reporters are credited in the published advisory (unless they prefer to
remain anonymous).
