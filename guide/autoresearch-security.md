# /autoresearch:security — The Security Auditor

Comprehensive security audit using STRIDE threat modeling, OWASP Top 10, and 4 red-team adversarial personas. Default: 15 iterations. Every finding requires code evidence (file:line + attack scenario). No theoretical vulnerabilities — confirmed findings only.

Loads `references/security-checklist.md` automatically for STRIDE/OWASP coverage tracking.

---

## How It Works — 3 Phases

```
SETUP (once):
  1. Codebase Recon      Tech stack, deps, configs, routes
  2. Asset Identification  Data stores, auth, APIs, inputs
  3. Trust Boundary Map  Browser↔Server, Public↔Auth, User↔Admin
  4. STRIDE Threat Model  6 threat categories × every asset
  5. Attack Surface Map  Entry points, data flows, abuse paths
  6. Baseline            Run npm/pip/go audit + lint

LOOP (15 iterations by default):
  1. Select untested attack vector from threat model
  2. Deep-dive into target code
  3. Validate with code evidence (file:line + scenario)
  4. Classify: severity + OWASP category + STRIDE tag
  5. Log to security-audit-results.tsv
  6. Print STRIDE/OWASP coverage every 5 iterations

REPORT:
  Severity-ranked findings + STRIDE/OWASP coverage matrices
  Prioritized remediation roadmap
```

---

## STRIDE Threat Model

| Threat | Question | Example Findings |
|--------|----------|-----------------|
| **S**poofing | Can an attacker impersonate a user? | Weak auth, missing CSRF, forged JWTs |
| **T**ampering | Can data be modified? | Missing validation, SQL injection, mass assignment |
| **R**epudiation | Can actions be denied? | Missing audit logs, unsigned transactions |
| **I**nfo Disclosure | Can sensitive data leak? | PII in logs, verbose errors, debug endpoints |
| **D**enial of Service | Can the service be disrupted? | Missing rate limits, ReDoS, unbounded uploads |
| **E**levation of Privilege | Can a user gain higher access? | IDOR, broken access control, path traversal |

---

## 4 Red-Team Personas

| Persona | Mindset |
|---------|---------|
| **Security Adversary** | External hacker — auth bypass, injection, session hijacking |
| **Supply Chain Attacker** | Compromising dependencies or CI/CD — CVEs, typosquatting |
| **Insider Threat** | Malicious employee — privilege escalation, data exfiltration |
| **Infrastructure Attacker** | Attacking deployment — container escape, hardcoded secrets |

---

## All Flags

| Flag | Purpose |
|------|---------|
| `Iterations: N` | Override default of 15 |
| `--diff` | Only audit files changed since last audit (fast PR checks) |
| `--fix` | Auto-fix confirmed Critical/High findings after audit |
| `--fail-on <severity>` | Exit non-zero for CI/CD gating: `critical`, `high`, `medium` |
| `--evals` | Analyze security-audit-results.tsv after completion |
| `--chain <targets>` | Chain to next command(s) after completion |

Flags combine: `--diff --fix --fail-on critical`

---

## Code Evidence Format

Every finding must include:

```markdown
### [CRITICAL] JWT Algorithm Confusion
- **OWASP:** A07 — Authentication Failures
- **STRIDE:** Spoofing
- **Location:** src/middleware/auth.ts:18
- **Confidence:** Confirmed
- **Attack Scenario:**
  1. Attacker crafts JWT with "alg": "none"
  2. Server accepts token without signature verification
  3. Attacker gains access as any user including admins
- **Code Evidence:**
  const decoded = jwt.verify(token, process.env.JWT_SECRET);
  // no algorithm restriction — accepts alg:none
- **Mitigation:**
  jwt.verify(token, process.env.JWT_SECRET, { algorithms: ['HS256'] })
```

---

## Examples

### Full audit (bounded)

```
/autoresearch:security
Iterations: 15
```

### Focused on auth

```
/autoresearch:security
Scope: src/api/**/*.ts, src/middleware/**/*.ts
Focus: authentication and authorization flows
Iterations: 15
```

### Delta mode — PR check

```
/autoresearch:security --diff
Iterations: 5
```

### Auto-fix Critical/High

```
/autoresearch:security --fix
Iterations: 15
```

### CI/CD gate — fail on Critical

```
/autoresearch:security --fail-on critical
Iterations: 10
```

### Combined: delta + fix + gate

```
/autoresearch:security --diff --fix --fail-on critical
Iterations: 15
```

### Python/Flask

```
/autoresearch:security
Scope: app/**/*.py, tests/**/*.py
Focus: Flask routes, SQLAlchemy models, auth decorators
Iterations: 15
```

### Infrastructure/DevOps

```
/autoresearch:security
Scope: Dockerfile, docker-compose.yml, .github/workflows/**/*.yml, k8s/**/*.yaml
Focus: container configuration, secrets management, CI/CD pipeline
Iterations: 12
```

---

## CI/CD Integration

```yaml
# .github/workflows/security-audit.yml
name: Security Audit
on:
  pull_request:
    branches: [main]
  schedule:
    - cron: '0 2 * * 1'  # Weekly Monday 2am

jobs:
  security-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Run Security Audit
        run: |
          if [ "${{ github.event_name }}" = "pull_request" ]; then
            claude -p "/autoresearch:security --diff --fail-on critical --iterations 5"
          else
            claude -p "/autoresearch:security --fail-on high --iterations 15"
          fi

      - name: Upload Report
        uses: actions/upload-artifact@v4
        with:
          name: security-report
          path: security/
          retention-days: 90
```

---

## Output Structure

```
security/{YYMMDD}-{HHMM}-{slug}/
├── overview.md                 Executive summary + links
├── threat-model.md             STRIDE analysis per asset + trust boundaries
├── attack-surface-map.md       Entry points, data flows, abuse paths
├── findings.md                 All findings ranked by severity with code evidence
├── owasp-coverage.md           OWASP Top 10 coverage matrix
├── dependency-audit.md         npm/pip/go audit results + CVE details
├── recommendations.md          Prioritized fix roadmap with code examples
└── security-audit-results.tsv  Machine-readable iteration log
```

---

## OWASP Top 10 Coverage

| ID | Category | Key Checks |
|----|----------|-----------|
| A01 | Broken Access Control | IDOR, missing auth middleware, privilege escalation |
| A02 | Cryptographic Failures | Plaintext secrets, weak hashing, missing encryption |
| A03 | Injection | SQL, NoSQL, command, XSS, template injection |
| A04 | Insecure Design | Missing rate limits, CSRF gaps, business logic flaws |
| A05 | Security Misconfiguration | Debug mode on, default credentials, missing headers |
| A06 | Vulnerable Components | Known CVEs in npm/pip/go dependencies |
| A07 | Auth Failures | JWT flaws, session fixation, weak password policies |
| A08 | Data Integrity Failures | Unsigned webhooks, insecure deserialization |
| A09 | Logging Failures | Missing audit logs, sensitive data in logs |
| A10 | SSRF | Unvalidated URLs in server-side requests |

---

## Chain Patterns

### security → fix → re-audit → ship

```
/autoresearch:security --fail-on high
Iterations: 15

/autoresearch:fix --from-debug
Iterations: 20

/autoresearch:security --diff
Iterations: 10

/autoresearch:ship --auto
```

### predict → security

```
/autoresearch:predict --adversarial --chain security
Scope: src/auth/**, src/api/**, src/middleware/**
Goal: Pre-deployment security review
```

---

## When to Run

| Scenario | Recommendation |
|----------|---------------|
| Before a major release | `Iterations: 15` |
| PR review (changed files) | `--diff --iterations 5` |
| Overnight comprehensive sweep | `Iterations: unlimited` |
| CI/CD gate | `--fail-on critical --iterations 10` |
| After auth/API changes | `--diff --fix` |
| Compliance preparation | `Iterations: 20` |
