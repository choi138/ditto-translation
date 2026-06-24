# AGENTS

## Environment

- Use `uv` for Python commands and dependency management.
- The project targets Python 3.11+ and normally runs through the local `.venv`.
- Do not hardcode or commit secrets, API tokens, webhook signing keys, or `.env`
  values.
- Treat `.env` as local-only configuration. Keep `.env.example` safe to commit.

## Code Conventions

| Convention | Location | When |
|-----------|----------|------|
| Git Workflow | `.agents/conventions/git-workflow.md` | Branch / commit / PR |
| Python Tooling | `pyproject.toml` | Format / lint / type / test |
| OpenSpec | `openspec/` | Behavior / contract / config changes |

## Workflow (OpenSpec-first)

This repo uses OpenSpec as the source of truth for behavior and contract
changes.

### How to work

1. Check the relevant spec in `openspec/specs/**` before changing behavior.
2. For webhook, API, retry, security, configuration, locale, or Ditto contract
   changes, update code, tests, and OpenSpec together.
3. Keep `spec.md` normative and testable. Put broader rationale or examples in
   context docs only when they are needed.
4. Validate touched specs with the strict OpenSpec command for the capability,
   for example `openspec validate ditto-webhook-auto-translation --strict`.
5. Do not archive OpenSpec changes unless the user explicitly asks and the
   implementation has been verified.

### Source of Truth

- Main specs: `openspec/specs/<capability>/spec.md`
- Active changes: `openspec/changes/<change>/`
- Archived changes: `openspec/changes/archive/YYYY-MM-DD-<change>/`

## Documentation

- Do not add separate behavior docs when OpenSpec should be the source of truth.
- Keep stable requirements in `openspec/specs/**/spec.md`.
- Keep README changes focused on running, configuring, and verifying the service.
- Do not edit release notes or changelogs unless the user explicitly requests it.

## PR Workflow

Create branches, commits, pushes, and PRs only when explicitly requested by the
user.

Branch names, commit messages, and PR titles MUST follow
`.agents/conventions/git-workflow.md`.

Before opening or updating a PR:

- Inspect `git status` and `git diff` so the PR contains only intended changes.
- Run the local checks that match the touched code:
  - `uv run ruff format --check .`
  - `uv run ruff check .`
  - `uv run ty check`
  - `uv run pytest`
- If OpenSpec files changed, run the strict OpenSpec validation command for the
  touched capability.
- Include verification results in the PR body, or explicitly report any checks
  that could not be run.

## Merge Readiness Gates

A PR can be described as merge-ready only after checking the actual current
GitHub PR state, not only local history.

Before saying a PR is merge-ready or merging it, verify:

- GitHub CI/checks are passing, or failing checks are reported clearly.
- The PR is mergeable, or merge blockers/conflicts are reported clearly.
- Blocking Codex or human review findings are addressed, or unresolved findings
  are reported clearly.
- Behavior changes include matching tests.
- Behavior/spec changes keep OpenSpec in sync.
- The PR title follows Conventional Commits.

Do not merge PRs unless the user explicitly asks.

## Ditto Translation Review Trapdoors

When changing webhook or translation behavior, pay special attention to:

- Ditto webhook signature verification and `ALLOW_UNSIGNED_WEBHOOKS` behavior.
- Idempotency for repeated Ditto webhook deliveries.
- Retryable failure handling.
- Self-generated Ditto update echo skipping.
- Locale-to-variant mapping, especially base text versus configured variant IDs.
- Source locale preservation.
- Target locale ordering when the order is observable in tests or API calls.
- Redaction of overlapping sensitive values in logs and error excerpts.
- `Authorization` headers, Ditto API tokens, codex-lb API keys, and webhook
  signing keys never being logged or committed.
- OpenAI/codex-lb request and response error handling.
