# Pipeline Live Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Synchronize live validation and public project docs with the current Pipeline API.

**Architecture:** The backend remains unchanged. The live script becomes the executable contract for local validation, with a deterministic `infra` suite and Pipeline-only paths. Documentation is updated to match the implemented route/config/UI names.

**Tech Stack:** Python 3.11, pytest, httpx, FastAPI, React/Vite docs.

---

## Files

- Create: `backend/tests/unit/test_api_live_script.py`
- Modify: `tests/api_live_test.py`
- Modify: `README.md`
- Modify: `HANDOFF.md`
- Modify: `docs/api.md`
- Create: `docs/superpowers/specs/2026-05-05-pipeline-live-validation-design.md`
- Create: `docs/superpowers/plans/2026-05-05-pipeline-live-validation.md`

## Task 1: Live Script Contract Tests

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_api_live_script.py` with tests that import `tests/api_live_test.py` by file path, run `run_smoke_tests()` against a fake runner, and assert no URL starts with `/api/workflows`. Add a second test requiring a `run_infra_tests()` function whose recorded URLs include `/api/pipelines/templates` and no Agent invoke endpoint.

- [ ] **Step 2: Verify red**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_api_live_script.py -q
```

Expected: at least one failure because the current script still records `/api/workflows/*` and has no `run_infra_tests()`.

## Task 2: Update Live Script

- [ ] **Step 1: Replace Workflow endpoints**

In `tests/api_live_test.py`, replace `/api/workflows/templates` with `/api/pipelines/templates`, and replace `/api/workflows/execute` with `/api/pipelines/execute`.

- [ ] **Step 2: Add infra suite**

Add `run_infra_tests(t)` that checks health, config, agents, pipeline templates, and invalid pipeline execution. Extend argparse choices to `("full", "smoke", "infra")`, and dispatch `infra` without running WebSocket or LLM-heavy checks.

- [ ] **Step 3: Verify green**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_api_live_script.py -q
```

Expected: all tests pass.

## Task 3: Documentation Sync

- [ ] **Step 1: Update README**

Replace visible Workflow-era user guidance with Pipeline names and `/api/pipelines/*` endpoints. Keep Chinese wording and current project positioning.

- [ ] **Step 2: Update HANDOFF**

Replace outdated next-step and known-issue references that say Workflow is current. Keep historical limitations only where they still apply.

- [ ] **Step 3: Update API docs**

Update task and pipeline sections so examples use `pipeline`, `template_name`, and `/api/pipelines/*`.

## Task 4: Full Verification

- [ ] **Step 1: Run backend suite**

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/ -q
```

- [ ] **Step 2: Run frontend build**

```powershell
npm run build
```

from `frontend/`.

- [ ] **Step 3: Run live infra suite**

```powershell
backend\.venv\Scripts\python.exe tests/api_live_test.py --suite infra
```

Expected: HTTP checks pass against the local backend.
