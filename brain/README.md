# 🧠 Brain: project memory

This is the single source of truth for the hackathon build. Read it before writing code; update it as you go.
Humans and AI agents both read from here.

| File | What's in it | Update when |
|---|---|---|
| [00-context.md](00-context.md) | Problem, users, what makes us different (1 page) | Pitch changes |
| [01-scope.md](01-scope.md) | Base + 3 pillars (True/Cuts/Yours): what's in, what's roadmap | Scope changes |
| [02-architecture.md](02-architecture.md) | Architecture, data model, API contract, algorithms | An interface changes |
| [03-implementation-plan.md](03-implementation-plan.md) | Phased build plan for coding round 2, acceptance checks | Every phase |
| [04-decisions.md](04-decisions.md) | Decision log (why X, not Y) | Every non-obvious choice |
| [05-environment.md](05-environment.md) | Machine facts, setup commands, gotchas | Something breaks |
| [06-demo-script.md](06-demo-script.md) | Exact demo flow + backup plan | Before rehearsal |
| [07-progress-log.md](07-progress-log.md) | Live checklist + timestamps | Every 20–30 min |
| [12-editor-plan.md](12-editor-plan.md) | Editor mode: upload video → auto B-roll → preview → render MP4 | Editor changes |
| [11-results.md](11-results.md) | YOURS + integration + ablation table + what is NOT done | Any pillar changes |
| [10-cuts.md](10-cuts.md) | CUTS pillar as built: transition terms, optimiser, measured weights, limits | CUTS logic changes |
| [09-truth.md](09-truth.md) | TRUE pillar as built: verdict rules, thresholds, traps, known limits | TRUE logic changes |
| [08-sources.md](08-sources.md) | Own footage + Pexels/Pixabay/Commons/Archive; tiers, lazy hydration, licences | A source is added |

Long-form docs: [problem statement](../FINAL_PROBLEM_STATEMENT.md) · [full system design](../docs/design/broll-search.md) (the v1 design; the 3-hour build is a subset of it).

## Rules
1. **Working > complete.** Every phase ends with something runnable.
2. **The API contract in `02-architecture.md` is frozen** once the UI starts. Change it only together.
3. **Hit a cut line? Cut, don't extend.** Cut lines are listed in the plan.
4. Log decisions in one line each. Future-you will forget why.

| [15-libraries.md](15-libraries.md) | Domain libraries | Library logic changes |
| [16-architecture-and-flows.md](16-architecture-and-flows.md) | Architecture and full data flow, as built | Onboarding, demos, any structural change |
| [18-landing-page-plan.md](18-landing-page-plan.md) | Landing page, palette reset, GSAP hero scrub (plan) | Any landing or theme work |
