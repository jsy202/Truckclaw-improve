# Findings & Decisions

## Requirements
- User personally observed one agent duplicate call in 20 prior tests; this motivated the task.
- Execute 20 vulnerable cases and 20 fixed cases, offscreen, saving individual evidence.
- Keep prior observed agent calls distinct from deliberate repeated HTTP inputs in this batch.

## Research Findings
- Existing runner starts a fresh CARLA process per case; one comparison completed previously.
- User documentation commit 22e3413 exists after our prior commit; preserve it.
- Final valid cases: vulnerable twenty collisions in twenty; fixed zero collisions in twenty.
- Forty-one actual attempts: forty valid cases plus one CARLA startup RenderThread crash. Vulnerable run003 rerun separately and collided.
- Independent full pytest verification: 46 passed in 13.39s; no skips. All forty artifact sets audited.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|

## Issues Encountered
| Issue | Resolution |
|-------|------------|

## Resources
-
