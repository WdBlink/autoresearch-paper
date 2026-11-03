# /autoresearch:ship — The Shipping Workflow

Ship anything through 8 phases: **Identify → Inventory → Checklist → Prepare → Dry-run → Ship → Verify → Log**. Linear — no loop, no iterations. Requires explicit approval unless `--auto` is set.

---

## The 8 Phases

| Phase | What Happens |
|-------|-------------|
| **1. Identify** | Detect what you're shipping (auto or via `--type`) |
| **2. Inventory** | Enumerate all artifacts, dependencies, and targets |
| **3. Checklist** | Generate type-specific readiness checklist |
| **4. Prepare** | Run pre-ship tasks (build, lint, bump version, etc.) |
| **5. Dry-run** | Simulate the ship action without executing it |
| **6. Ship** | Execute the actual ship action |
| **7. Verify** | Confirm successful delivery |
| **8. Log** | Record ship event with timestamp and artifact details |

---

## Auto-Detection

When no `--type` is given, `:ship` inspects context to detect what you're shipping:

- **Git state** — uncommitted changes, branch name, open PRs
- **Target file** — `.md` → content, `Dockerfile` → deployment
- **Directory structure** — `content/`, `campaigns/`, `decks/`
- **CI config** — presence of workflow files, deploy scripts
- **Conversation context** — what you said most recently

If it cannot determine type with confidence, it asks one clarifying question.

---

## 8 Supported Types

| Type | Ship Action |
|------|-------------|
| `code-pr` | Create PR with full description, reviewers, and labels |
| `code-release` | Git tag + GitHub release with changelog |
| `deployment` | CI/CD trigger, kubectl apply, or deploy branch push |
| `content` | Publish via CMS or merge content branch |
| `marketing-email` | Send via ESP (SendGrid, Mailchimp, etc.) |
| `marketing-campaign` | Activate ads, launch landing page, notify channels |
| `sales` | Send proposal email, share deck link with prospect |
| `research` | Upload preprint, submit paper, publish report |
| `design` | Export assets, upload to shared drive, notify stakeholders |

---

## All Flags

| Flag | Purpose |
|------|---------|
| `--dry-run` | Validate without executing the ship action |
| `--auto` | Auto-approve checklist if no blockers found |
| `--force` | Skip non-critical warnings (blockers always enforced) |
| `--rollback` | Undo the last ship action |
| `--monitor N` | Post-ship monitoring for N minutes |
| `--type <type>` | Override auto-detection |
| `--checklist-only` | Generate readiness checklist without shipping |
| `--chain <targets>` | Chain to next command(s) after completion |

---

## Examples

### Auto-detect and ship (interactive)

```
/autoresearch:ship
```

### Ship a code PR with auto-approve

```
/autoresearch:ship --auto
```

### Ship a code release

```
/autoresearch:ship --type code-release
```

### Dry-run a deployment

```
/autoresearch:ship --type deployment --dry-run
```

### Ship with post-deploy monitoring

```
/autoresearch:ship --type deployment --monitor 10
```

### Checklist only

```
/autoresearch:ship --checklist-only
```

### Ship a blog post

```
/autoresearch:ship --type content
Target: content/blog/2026-q1-retrospective.md
```

### Ship a marketing email

```
/autoresearch:ship --type marketing-email
Target: campaigns/march-launch/email-final.html
```

### Ship a sales proposal

```
/autoresearch:ship --type sales
Target: decks/q1-enterprise-proposal.pdf
```

### Rollback

```
/autoresearch:ship --rollback
```

Reads the last ship log, identifies rollback target, executes the undo action.

---

## Checklists by Type

### code-pr
- [ ] Branch is up to date with base branch
- [ ] All CI checks passing
- [ ] No merge conflicts
- [ ] PR description describes the change and why
- [ ] Tests added or updated for new behavior
- [ ] No secrets or credentials in diff

### code-release
- [ ] Version bumped in package.json / pyproject.toml
- [ ] CHANGELOG updated with release notes
- [ ] All tests passing on main
- [ ] No open blocking issues tagged for this milestone

### deployment
- [ ] Build artifact exists and is current
- [ ] Environment variables confirmed for target env
- [ ] Database migrations ready (if needed)
- [ ] Rollback plan documented
- [ ] On-call engineer notified

### content
- [ ] Front-matter complete (title, date, tags, description)
- [ ] All internal links valid
- [ ] Images optimized with alt text
- [ ] SEO title and meta description present

### marketing-email
- [ ] Unsubscribe link present
- [ ] "From" name and address configured
- [ ] HTML renders in major email clients
- [ ] Send list verified — no test addresses in production list

---

## Post-Ship Monitoring

When `--monitor N` is set, `:ship` enters a watch loop after shipping:

- Polls health endpoints or deploy status URLs
- Watches for error rate spikes vs baseline
- Checks response time p95 against pre-ship baseline
- Reports at 1-minute intervals for N minutes
- Triggers rollback recommendation if anomaly threshold exceeded

| Environment | Recommended |
|-------------|-------------|
| Staging deploys | `--monitor 5` |
| Production deploys | `--monitor 15` |
| High-traffic production | `--monitor 30` |

---

## Chain Patterns

### loop → ship

```
/autoresearch
Goal: Reduce p95 API latency below 100ms
Verify: npm run bench:api | grep "p95"
Guard: npm test
Iterations: 20

/autoresearch:ship --type code-pr --auto
```

### fix → ship

```
/autoresearch:fix
Iterations: 25

/autoresearch:ship --type deployment --monitor 10
```

### security → fix → ship

```
/autoresearch:security
Iterations: 15

/autoresearch:fix --from-debug
Iterations: 20

/autoresearch:ship --type deployment --monitor 15
```

### Full pipeline (single command)

```
/autoresearch:predict --chain scenario,debug,security,fix,ship
Scope: src/**
Goal: Complete quality pipeline for v2.0 release
```

---

## Tips

- **Use `--dry-run`** when shipping to production for the first time, or after changing deploy config.
- **Use `--checklist-only`** for a readiness score without committing to ship.
- **Use `--force` sparingly.** It skips warnings but not blockers. Fix blockers — they are blockers for a reason.
- **Log entries** are written to `ship-log.md`: timestamp, type, artifacts, git hash, verification status.

---

## Related Guides

- [/autoresearch:fix](autoresearch-fix.md) — fix everything before shipping
- [/autoresearch:security](autoresearch-security.md) — audit before shipping
- [Chains & Combinations](chains-and-combinations.md) — full lifecycle pipelines
