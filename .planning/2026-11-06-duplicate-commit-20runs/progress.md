# Progress Log

## Session: 2026-11-06

### Current Status
- **Phase:** 1 - Requirements & Discovery
- **Started:** 2026-11-06

### Actions Taken
- Inspected existing runner and clean worktree. Preserved user documentation edits.
- Planning: forty separate cases, no silent retries or treating runtime errors as collision-free runs.
- Added batch runner and single-case selection; summary tests failed as expected, then all six focused unit tests passed.
- Started batch session 34736: output experiments/duplicate_commit/evidence_20runs_20261106.
- Initial vulnerable twenty attempts finished: nineteen collisions, one environment error before scene startup.
- Fixed runs 1–10 completed with no collision, one physical start, final speed zero.
- Added an independent forty-artifact audit and separate error-rerun tooling; original attempts remain untouched.
- All twenty fixed cases completed without collision. Original error run003 rerun once in a separate folder and collided.
- verified_summary.json retains original errors and all forty selected valid results. Total attempts: 41.
- Full suite with both evidence environment variables: 46 passed in 13.39s. CARLA ports are no longer listening.
- Added REPORT_20RUNS.md and PRIOR_OBSERVATION.md; preserved all user documentation edits and original attempt logs.

### Test Results
| Test | Expected | Actual | Status |
|------|----------|--------|--------|

### Errors
| Error | Resolution |
|-------|------------|
| Vulnerable run003: Unreal RenderThread timeout and server crash before scenario start | Preserved runner/server logs; counted as environment error, not collision-free. Remaining batch continues; rerun failed cases separately after the batch. |
