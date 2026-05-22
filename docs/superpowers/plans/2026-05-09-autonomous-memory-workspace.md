# Autonomous Memory Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current Agent Run page into a goal-driven memory workspace and extend backend Run semantics for continuous work.

**Architecture:** Reuse the existing `TaskRegistry`, `/api/runs`, transcript writer, memory retriever, and React `TaskPanel`. Add small state fields and control actions instead of reviving Workflow. Frontend changes remain scoped to navigation, API client types, and the run workspace page.

**Tech Stack:** FastAPI, Pydantic, pytest, React 18, TypeScript, Vite.

---

## Files

- Modify: `backend/src/core/task/types.py`
- Modify: `backend/src/core/task/registry.py`
- Modify: `backend/src/api/schemas.py`
- Modify: `backend/src/api/routes/tasks.py`
- Modify: `backend/tests/unit/test_task_registry.py`
- Modify: `backend/tests/unit/test_websocket_deps_schemas.py`
- Modify: `backend/tests/integration/test_api.py`
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/components/TaskPanel.tsx`
- Modify: `frontend/src/components/TaskPanel.css`
- Modify: `frontend/src/components/Sidebar.tsx`
- Modify: `frontend/src/components/Sidebar.css`

## Task 1: Backend Run State

- [ ] Add failing tests for `paused`, `pause()`, `resume()`, continuous fields, and schema control actions.
- [ ] Implement `TaskStatus.PAUSED`, `TaskState` continuous fields, and registry pause/resume helpers.
- [ ] Verify unit tests pass.

## Task 2: Run Control And Memory Context API

- [ ] Add failing API tests for `POST /api/runs/{id}/control` with `pause/resume` and `GET /api/runs/{id}/memory-context`.
- [ ] Implement schema changes and route handlers.
- [ ] Thread continuous run fields from create request into `TaskState` and Agent payload.
- [ ] Verify API tests pass.

## Task 3: Frontend Goal Workspace

- [ ] Extend TypeScript types and client functions for continuous fields, control actions, and memory context.
- [ ] Rework `TaskPanel` copy and layout around goals, completion criteria, memory context, iteration, and pause/resume/stop controls.
- [ ] Update sidebar labels so Pipeline is clearly legacy/compatibility.
- [ ] Verify `npm run build` passes.

## Task 4: Final Verification

- [ ] Run backend targeted tests.
- [ ] Run frontend build.
- [ ] Check `git status` and summarize changed files.
