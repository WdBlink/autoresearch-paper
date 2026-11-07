# Examples by Domain — Real-World Configurations

Copy-paste configurations organized by domain. Every example uses v2.1.0 syntax with bounded defaults.

[Software (TypeScript/JS)](#software-typescriptjavascript) · [Python](#python) · [Go](#go) · [Rust](#rust) · [Sales & Lead Gen](#sales--lead-generation) · [SEO & Content](#seo--content-marketing) · [Marketing & Growth](#marketing--growth) · [Web Scraping](#web-scraping) · [DevOps & Infrastructure](#devops--infrastructure) · [Data Science & ML](#data-science--ml) · [Design & Accessibility](#design--accessibility) · [HR & People Ops](#hr--people-operations) · [Documentation](#documentation)

---

## Software (TypeScript/JavaScript)

### Increase test coverage

```
/autoresearch
Iterations: 20
Goal: Increase test coverage from 72% to 90%
Scope: src/**/*.test.ts, src/**/*.ts
Metric: coverage % (higher is better)
Verify: npm test -- --coverage | grep "All files"
```

### Reduce bundle size

```
/autoresearch
Iterations: 15
Goal: Reduce production bundle size below 200KB
Scope: src/**/*.tsx, src/**/*.ts
Metric: bundle size in KB (lower is better)
Verify: npm run build 2>&1 | grep "First Load JS"
Guard: npm test
```

### API performance (p95 latency)

```
/autoresearch
Iterations: 20
Goal: API response time under 100ms (p95)
Scope: src/api/**/*.ts, src/services/**/*.ts
Metric: p95 response time in ms (lower is better)
Verify: npm run bench:api | grep "p95"
Guard: npm test
```

### Eliminate TypeScript `any` types

```
/autoresearch
Iterations: 25
Goal: Eliminate all TypeScript `any` types
Scope: src/**/*.ts
Metric: count of `any` occurrences (lower is better)
Verify: grep -r ":\s*any" src/ --include="*.ts" | wc -l
Guard: tsc --noEmit
```

### Fix flaky tests

```
/autoresearch
Iterations: 10
Goal: Zero flaky tests — all tests pass 5 consecutive runs
Scope: src/**/*.test.ts
Metric: failure count across 5 runs (lower is better)
Verify: for i in {1..5}; do npm test 2>&1; done | grep -c "FAIL"
```

### Lighthouse performance score

```
/autoresearch
Iterations: 20
Goal: Lighthouse performance score 95+
Scope: src/components/**/*.tsx, src/app/**/*.tsx
Metric: Lighthouse performance score (higher is better)
Verify: npx lighthouse http://localhost:3000 --output=json --quiet | jq '.categories.performance.score * 100'
Guard: npx playwright test
```

### Debug → fix → ship (incident pipeline)

```
/autoresearch:debug --fix --severity high
Scope: src/**/*.ts
Symptom: Payment confirmations silently failing
Iterations: 20

/autoresearch:ship --type code-pr --auto
```

### Security audit + auto-fix

```
/autoresearch:security --diff --fix --fail-on critical
Iterations: 15
```

---

## Python

### Increase pytest coverage

```
/autoresearch
Iterations: 30
Goal: Increase pytest coverage from 68% to 90%
Scope: tests/**/*.py, app/**/*.py
Metric: coverage % (higher is better)
Verify: pytest --cov=app --cov-report=term-missing 2>&1 | grep "TOTAL" | awk '{print $4}'
```

### Reduce Django N+1 queries

```
/autoresearch
Iterations: 15
Goal: Eliminate N+1 queries — reduce total DB queries per request
Scope: app/views/**/*.py, app/models/**/*.py
Metric: total query count per request (lower is better)
Verify: python manage.py test --settings=settings.test 2>&1 | grep "queries" | awk '{print $1}'
Guard: pytest
```

### Fix mypy strict errors

```
/autoresearch:fix --target "mypy app/ --strict"
Guard: pytest
Iterations: 25
```

### FastAPI response time

```
/autoresearch
Iterations: 20
Goal: Reduce p95 response time to under 50ms
Scope: app/routers/**/*.py, app/services/**/*.py
Metric: p95 response time in ms (lower is better)
Verify: python scripts/bench_api.py | grep "p95"
Guard: pytest
```

---

## Go

### Increase test coverage

```
/autoresearch
Iterations: 25
Goal: Increase test coverage to 85%
Scope: **/*.go
Metric: coverage % (higher is better)
Verify: go test ./... -coverprofile=cover.out && go tool cover -func=cover.out | grep "total:" | awk '{print $3}'
```

### Benchmark optimization

```
/autoresearch
Iterations: 20
Goal: Improve hot-path benchmark by 2x
Scope: internal/parser/**/*.go
Metric: ns/op from benchmark (lower is better)
Verify: go test -bench=BenchmarkParse -benchmem ./internal/parser/ | grep "BenchmarkParse" | awk '{print $3}'
Guard: go test ./...
```

### Fix vet + staticcheck errors

```
/autoresearch:fix --target "go vet ./... && staticcheck ./..."
Guard: go test ./...
Iterations: 15
```

---

## Rust

### Increase test coverage

```
/autoresearch
Iterations: 20
Goal: Increase test coverage to 80%
Scope: src/**/*.rs
Metric: coverage % (higher is better)
Verify: cargo tarpaulin --out Stdout 2>&1 | grep "coverage" | awk '{print $2}'
```

### Criterion benchmark optimization

```
/autoresearch
Iterations: 25
Goal: Reduce p95 request handling time
Scope: src/handlers/**/*.rs
Metric: ns/iter from criterion (lower is better)
Verify: cargo bench -- --output-format bencher 2>&1 | grep "bench:" | awk '{print $5}'
Guard: cargo test
```

### Fix clippy warnings

```
/autoresearch:fix --target "cargo clippy -- -D warnings"
Guard: cargo test
Iterations: 20
```

---

## Sales & Lead Generation

### Cold email optimization

```
/autoresearch
Iterations: 15
Goal: Improve cold email reply rate prediction score
Scope: content/email-templates/*.md
Metric: readability score + personalization token count (higher is better)
Verify: node scripts/score-email-template.js
```

### Objection handling docs

```
/autoresearch
Iterations: 20
Goal: Cover all 20 common objections with responses under 50 words each
Scope: content/objection-responses.md
Metric: objections covered (higher is better)
Verify: node scripts/score-objections.js
```

### Ship a sales proposal

```
/autoresearch:ship --type sales
Target: proposals/enterprise-q1.md
```

### Sales edge case scenarios

```
/autoresearch:scenario --domain business --depth deep
Scenario: Enterprise customer evaluates SaaS during procurement with 5 stakeholders
Iterations: 25
```

---

## SEO & Content Marketing

### Blog SEO score

```
/autoresearch
Iterations: 25
Goal: Maximize SEO score for target keywords
Scope: content/blog/*.md
Metric: SEO score (higher is better)
Verify: node scripts/seo-score.js --file content/blog/target-post.md
```

### Readability optimization

```
/autoresearch
Iterations: 15
Goal: Maximize Flesch readability + keyword density for "AI automation"
Scope: content/landing-pages/ai-automation.md
Metric: readability_score * 0.7 + keyword_density_score * 0.3 (higher is better)
Verify: node scripts/content-score.js content/landing-pages/ai-automation.md
```

### Meta descriptions batch

```
/autoresearch
Iterations: 20
Goal: All blog posts have meta descriptions under 160 chars with target keyword
Scope: content/blog/*.md
Metric: posts meeting criteria (higher is better)
Verify: node scripts/meta-description-audit.js
```

### Ship blog content

```
/autoresearch:ship --type content
Target: content/blog/my-new-post.md
```

---

## Marketing & Growth

### Email campaign optimization

```
/autoresearch
Iterations: 20
Goal: Optimize 7-day nurture sequence for clarity and CTA strength
Scope: content/email-sequences/onboarding/*.md
Metric: avg readability + CTA score per email (higher is better)
Verify: node scripts/score-email-sequence.js onboarding
```

### Landing page CRO

```
/autoresearch
Iterations: 15
Goal: Maximize landing page quality score
Scope: content/landing-pages/product-launch.md
Metric: CRO checklist score (higher is better)
Verify: node scripts/cro-score.js content/landing-pages/product-launch.md
```

### Google Ads headlines

```
/autoresearch
Iterations: 30
Goal: Generate 50 ad headline variants (max 30 chars) with power words + CTA
Scope: content/ads/google-search/*.md
Metric: headlines meeting criteria (higher is better)
Verify: node scripts/google-ads-validator.js --type headlines
```

### Ship email campaign

```
/autoresearch:ship --type marketing-email
Target: content/emails/product-launch-campaign.html
```

---

## Web Scraping

### Improve scraper success rate

```
/autoresearch
Iterations: 25
Goal: Increase scraper success rate from 85% to 99%
Scope: scrapers/**/*.py
Metric: success rate % (higher is better)
Verify: python scripts/scraper-test.py --sample 100 | grep "success_rate"
Guard: python -m pytest tests/scrapers/
```

### Scraping edge cases

```
/autoresearch:scenario --domain software --focus edge-cases
Scenario: Web scraper encounters anti-bot measures, dynamic content, and rate limiting
Iterations: 20
```

### Debug scraper failures

```
/autoresearch:debug
Scope: scrapers/**/*.py
Symptom: Scraper fails on paginated results after page 5 with 403 errors
Iterations: 10
```

---

## DevOps & Infrastructure

### Reduce Docker image size

```
/autoresearch
Iterations: 10
Goal: Reduce Docker image size below 100MB
Scope: Dockerfile, .dockerignore
Metric: image size in MB (lower is better)
Verify: docker build -t bench . 2>&1 && docker images bench --format "{{.Size}}"
```

### Optimize CI/CD pipeline duration

```
/autoresearch
Iterations: 15
Goal: Reduce CI/CD pipeline from 12 minutes to under 5 minutes
Scope: .github/workflows/*.yml, Dockerfile
Metric: pipeline duration in minutes (lower is better)
Verify: gh run list --limit 1 --json durationMs --jq '.[0].durationMs / 60000'
Guard: docker compose up -d && sleep 5 && curl -sf http://localhost:3000/health
```

### Infrastructure security audit

```
/autoresearch:security
Scope: Dockerfile, docker-compose.yml, .github/workflows/**/*.yml, k8s/**/*.yaml
Focus: exposed secrets, container privileges, network policies
Iterations: 12
```

### Ship a deployment

```
/autoresearch:ship --type deployment --monitor 10
```

### Nightly optimization (GitHub Actions)

```yaml
name: Nightly Optimization
on:
  schedule:
    - cron: '0 1 * * *'
jobs:
  optimize:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm ci
      - name: Run overnight loop
        run: |
          claude -p "/autoresearch
          Iterations: 50
          Goal: Improve test coverage and reduce bundle size
          Scope: src/**/*.ts
          Verify: npm test -- --coverage | grep 'All files'
          Guard: npm run build
          --evals"
      - name: Create PR with improvements
        run: claude -p "/autoresearch:ship --type code-pr --auto"
```

---

## Data Science & ML

### Training loss reduction

```
/autoresearch
Iterations: unlimited
Goal: Reduce validation loss (val_bpb)
Scope: train.py, model.py
Metric: val_bpb (lower is better)
Verify: uv run train.py --epochs 1 2>&1 | grep "val_bpb" | tail -1 | awk '{print $NF}'
```

### ML model accuracy

```
/autoresearch
Iterations: 25
Goal: Improve classification accuracy from 85% to 95%
Scope: model.py, config.yaml, data/augmentation.py
Verify: python train.py --eval-only 2>&1 | grep 'val_accuracy' | awk '{print $NF}'
Guard: python -m pytest tests/test_model.py -q
```

### SQL query optimization

```
/autoresearch
Iterations: 15
Goal: Reduce total query execution time for dashboard queries
Scope: queries/dashboard/*.sql
Metric: total execution time in ms (lower is better)
Verify: psql -f scripts/bench-queries.sql | grep "total_ms"
```

---

## Design & Accessibility

### WCAG 2.1 AA compliance

```
/autoresearch
Iterations: 25
Goal: Reach WCAG 2.1 AA — zero axe violations
Scope: src/components/**/*.tsx
Metric: axe violation count (lower is better)
Verify: npx playwright test a11y.spec.ts | grep "violations"
```

### Replace hardcoded colors with design tokens

```
/autoresearch
Iterations: 20
Goal: Replace all hardcoded colors/spacing with design tokens
Scope: src/**/*.tsx, src/**/*.css
Metric: hardcoded values count (lower is better)
Verify: grep -rE "#[0-9a-fA-F]{3,6}|px\b" src/ --include="*.tsx" --include="*.css" | wc -l
```

---

## HR & People Operations

### Job description clarity

```
/autoresearch
Iterations: 15
Goal: Improve job descriptions — bias-free language, clear requirements, inclusive tone
Scope: content/job-descriptions/*.md
Metric: inclusivity score (higher is better)
Verify: node scripts/jd-inclusivity-score.js
```

### Policy readability

```
/autoresearch
Iterations: 10
Goal: Reduce average reading level of HR policies to grade 8
Scope: content/policies/*.md
Metric: Flesch-Kincaid grade level (lower is better)
Verify: node scripts/readability.js content/policies/
```

### Hiring process scenarios

```
/autoresearch:scenario --domain business --depth deep
Scenario: Candidate moves through interview process from application to offer
Iterations: 25
```

---

## Documentation

### Generate docs for a new codebase

```
/autoresearch:learn --mode init --depth deep
```

### Update docs after a sprint

```
/autoresearch:learn --mode update
```

### Check docs health before release

```
/autoresearch:learn --mode check
```

### Docs → security pipeline

```
/autoresearch:learn --mode init
/autoresearch:security
Iterations: 15
```

---

## Domain Adaptation Reference

| Domain | Metric | Scope | Verify | Guard |
|--------|--------|-------|--------|-------|
| Node.js/TS | Coverage % | `src/**/*.ts` | `npm test -- --coverage` | — |
| Python | pytest coverage % | `app/**/*.py` | `pytest --cov=app` | `mypy app/` |
| Go | Test coverage % | `**/*.go` | `go test ./... -cover` | `go vet ./...` |
| Rust | Test coverage % | `src/**/*.rs` | `cargo tarpaulin` | `cargo clippy` |
| Frontend | Lighthouse score | `src/components/**` | `npx lighthouse` | `npm test` |
| ML | val_bpb / loss | `train.py` | `uv run train.py` | — |
| Blog/content | Readability score | `content/*.md` | Custom script | — |
| Performance | Benchmark (ms) | Target files | `npm run bench` | `npm test` |
| DevOps | Pipeline minutes | `*.yml` | `gh run list` | Health check |
| Security | OWASP + STRIDE | API/auth | `/autoresearch:security` | — |
