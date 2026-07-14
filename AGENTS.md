# BulkAddWithAI repository rules

## Product invariants

- Keep Torob and Basalam workspaces, assets, jobs, and publish state isolated.
- Never expose another seller's data or attach one seller to another seller's booth.
- Preserve uploads and drafts when AI or platform operations fail.
- User-facing errors must be actionable Persian and must not expose raw provider text.
- Never log tokens, OAuth code/state, mobile numbers, voice transcripts, images, query strings, or complete product payloads.

## Development workflow

- Use TDD for behavior changes. AI behavior starts with deterministic fake-provider tests.
- Backend: `cd backend; .\.venv\Scripts\python.exe -m pytest --basetemp .pytest-tmp\run`.
- Frontend: `cd frontend; npm test; npm run build; npm run e2e`.
- Run `git diff --check` before proposing a merge.
- Follow `docs/RELEASE.md`; do not expand the current milestone implicitly.

## Autonomous-agent restrictions

- Never merge, deploy, publish to a marketplace, rotate secrets, or modify production data.
- Authentication, OAuth, migrations, dependencies, workflows, Docker, and agent policy require human-owned changes.
- An autonomous fix needs production evidence, a regression test that fails on the base revision, green gates, and an independent review.
