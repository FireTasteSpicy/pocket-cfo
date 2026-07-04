# Security demo — the pre-commit hook blocks a hardcoded secret

This is the **remediation loop** the course teaches (block → fix → re-commit),
and a demo worth filming. Our pre-commit gate runs *two independent* secret
scanners plus a private-key check, so a leaked credential is caught before a
commit is ever created. We **never** bypass it with `--no-verify`.

> Note: the sample keys below are shown with the actual secret characters
> replaced by `<FAKE-KEY-REDACTED>` — because this very file is scanned by the
> same hook, and a real-looking key here would (correctly) block *this* commit
> too. Use any test key of the shown *format* to reproduce.

Reproduce it yourself:

```bash
# 1. Plant a FAKE secret in a file and stage it
cat > app/tools/_leaky_demo.py <<'PY'
STRIPE_SECRET  = "sk_live_<FAKE-KEY-REDACTED>"
GOOGLE_API_KEY = "AIza<FAKE-KEY-REDACTED>"
PY
git add app/tools/_leaky_demo.py

# 2. Try to commit — the hook BLOCKS it (exit code 1, no commit created)
git commit -m "try to commit a secret"
```

## What happened (actual output, secrets masked)

```
semgrep (hardcoded-secret scan)..........................................Failed
- hook id: semgrep
- exit code: 1

  1 Code Finding
    app/tools/_leaky_demo.py
   ❯❯❱ generic.secrets.security.detected-stripe-api-key
          ❰❰ Blocking ❱❱
          Stripe API Key detected
            3┆ STRIPE_SECRET = "sk_live_<FAKE-KEY-REDACTED>"

gitleaks (entropy + regex secret scan)...................................Failed
- hook id: gitleaks
- exit code: 1
    Finding:     GOOGLE_API_KEY = "REDACTED"
    RuleID:      generic-api-key
    Entropy:     4.353619
    File:        app/tools/_leaky_demo.py  Line: 4
    leaks found: 1

ruff (lint)..............................................................Passed
detect private key.......................................................Passed
```

Commit **exit code = 1** → the commit was refused. Semgrep caught the Stripe-key
format; gitleaks independently caught the high-entropy Google API key (defense in
depth — two scanners, two rulesets).

## The fix (remediation)

Remove the hardcoded value and read the credential from the environment instead:

```python
import os

STRIPE_SECRET  = os.environ["STRIPE_SECRET"]   # value lives in .env (gitignored)
GOOGLE_API_KEY = os.environ["GEMINI_API_KEY"]
```

Re-running `git commit` now passes all hooks. The secret never enters git
history — which is the whole point, because `git` history is forever.
