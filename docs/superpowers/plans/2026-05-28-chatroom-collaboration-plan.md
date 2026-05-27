# Chatroom Collaboration Refactor Implementation Plan — 2026-05-28

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each Task follows the 5-step TDD loop: write failing test → run failing → implement → run passing → commit.

**Goal:** Refactor chatroom multi-agent collaboration per spec `docs/superpowers/specs/2026-05-28-chatroom-collaboration-design.md`. Replace text-protocol host_directive with a real `chatroom_dispatch` tool, fix role assignment in context build, inject runtime-state via `<system-reminder>` blocks, add `chatroom_get_goal` / `chatroom_update_goal` / `chatroom_todo` tools, default-block `dispatch_agent` inside chatrooms, and surface todos + new events in the React panel.

**Architecture:** Reuse the existing `ChatroomStore` JSON persistence, `dispatch_speaking_task` orchestrator, `CapabilityRegistry`, ContextVar-driven tool gating in `core/task/context.py`, WebSocket fan-out via `broadcast_chatroom_event`, and `core/prompts.py` for prompt fragments. New tool files follow the `chatroom_set_goal.py` pattern. The chatroom collaboration protocol prefix is layered into `build_room_context` only (Agent Run / ChatPanel paths are untouched).

**Tech Stack:** Python 3.10+, FastAPI, Pydantic, pytest + pytest-asyncio, React 18, TypeScript 5, Vite 5.

---

## Files

### Backend — modify

- `backend/src/core/prompts.py` — add `CHATROOM_COLLABORATION_PROTOCOL` constant
- `backend/src/core/chatroom.py` — refactor `_format_history_message` (XML, role fix), refactor `build_room_context` system block to XML, add `todos` / `goal_subgoals` fields + helpers, add `apply_goal_subgoal_op` and `add_todo / update_todo / list_todos / delete_todo` store methods, register `chatroom_todo` payload schema
- `backend/src/core/chatroom_orchestrator.py` — delete `_parse_host_directive` and its caller, add `build_system_reminders`, append reminder block in `_run_speaking_task`, strip `dispatch_agent` from chatroom payload (A21), auto-create-then-auto-complete `chatroom_todo` rows linked to dispatch task ids, broadcast new WS events
- `backend/src/api/routes/chatrooms.py` — delete the `host_prompt` injection block (lines 184-198), keep the `host_agent` membership warning fallback
- `backend/src/api/main.py` — add new tool names to `_CHATROOM_AUTONOMY_TOOLS`
- `backend/src/core/task/context.py` — (optional) confirm existing ContextVars cover what new tools need (no new vars expected)

### Backend — create

- `backend/src/capabilities/tools/chatroom_get_goal.py`
- `backend/src/capabilities/tools/chatroom_update_goal.py`
- `backend/src/capabilities/tools/chatroom_dispatch.py`
- `backend/src/capabilities/tools/chatroom_todo.py`
- `backend/tests/unit/test_chatroom_get_goal.py`
- `backend/tests/unit/test_chatroom_update_goal.py`
- `backend/tests/unit/test_chatroom_dispatch.py`
- `backend/tests/unit/test_chatroom_todo.py`
- `backend/tests/unit/test_chatroom_collaboration_protocol.py`
- `backend/tests/unit/test_chatroom_history_format.py`
- `backend/tests/unit/test_chatroom_system_reminders.py`

### Backend — modify (tests)

- `backend/tests/unit/test_chatroom.py` — add XML system block + role fix coverage; remove obsolete assertions
- `backend/tests/unit/test_chatroom_orchestrator.py` — drop host_directive coverage, add reminder + payload tools coverage, A21 default-block coverage
- `backend/tests/integration/test_chatroom_pipeline.py` — replace JSON-text e2e with `chatroom_dispatch` e2e + parallel + todo lifecycle

### Frontend — modify

- `frontend/src/types/index.ts` — add `ChatroomTodo`, `ChatroomGoalSubgoal`, new WS event types, extend `Chatroom` with `todos[]` / `goal_subgoals[]` / `settings.allow_subagent_dispatch`
- `frontend/src/api/client.ts` — no new endpoints needed (todos are read from `Chatroom`); keep types in sync
- `frontend/src/components/ChatroomPanel.tsx` — render `<TodoBanner>` above messages, render subgoal list inside the goal banner, subscribe to new WS events (`chatroom_dispatch_called`, `chatroom_todo_*`, `chatroom_goal_subgoal_*`, `chatroom_system_reminder`)
- `frontend/src/components/ChatroomPanel.css` — add styles for `.chatroom-todos`, `.chatroom-todo`, `.chatroom-subgoals`

### Documentation — modify

- `agentic-system/CLAUDE.md` §3.10 — update chatroom feature list (new tools, XML context, system-reminder, todos), update WebSocket event list and tool description block

---

## Phase 1 — Foundation Refactor (independent, parallelizable)

### Task 1: Add chatroom collaboration protocol constant

- [ ] Write a failing unit test `backend/tests/unit/test_chatroom_collaboration_protocol.py::test_protocol_constant_exists_and_lists_required_tools` that imports `CHATROOM_COLLABORATION_PROTOCOL` from `core.prompts` and asserts: (a) the string contains the literal `[聊天室协作模式]`, (b) it mentions every tool name `chatroom_dispatch`, `chatroom_get_goal`, `chatroom_update_goal`, `chatroom_invite`, `chatroom_create_agent`, `chatroom_todo`, (c) it contains both the `✅` and `❌` example markers (CC behavior-examples format), (d) it explicitly states the JSON-output override rule ("即使你的本体 prompt 要求").
- [ ] Run `python3 -m pytest backend/tests/unit/test_chatroom_collaboration_protocol.py -q` and confirm `ImportError`/assertion failure.
- [ ] Add `CHATROOM_COLLABORATION_PROTOCOL` to `backend/src/core/prompts.py` after `CHATROOM_SUMMARY_PROMPT`. Use the full text from spec §6.2 verbatim (output style / dispatch style / behavior examples / safety sections). Keep it as a module-level string constant, no f-string.
- [ ] Run `python3 -m pytest backend/tests/unit/test_chatroom_collaboration_protocol.py -q` until green.
- [ ] `git commit -m "feat(chatroom): add CHATROOM_COLLABORATION_PROTOCOL prompt constant"`.

### Task 2: Reality-check current history-format role assignment

- [ ] Write a failing unit test `backend/tests/unit/test_chatroom_history_format.py::test_current_state_other_agents_use_assistant_role` that imports `_format_history_message` from `core.chatroom`, builds a fake message dict with `sender="agent:reviewer"`, `status="done"`, `content="hello"`, calls `_format_history_message(msg, target_agent_name="coder")`, and asserts the returned `role == "user"` (this **must fail** against current code). Add an inline comment explaining: "Current implementation incorrectly returns role=assistant for other agents, which causes LM role confusion (multi-turn training data assumes assistant role only contains the model's own previous turns). Test asserts the desired post-fix behavior; running it before Task 5 should fail and prove the bug exists."
- [ ] Run `python3 -m pytest backend/tests/unit/test_chatroom_history_format.py::test_current_state_other_agents_use_assistant_role -q` and confirm failure showing `AssertionError: assert 'assistant' == 'user'`. Capture the failing output in the commit message body so the review trail records the bug.
- [ ] Mark the test with `@pytest.mark.xfail(strict=True, reason="will be fixed in Task 5 / A15 history rewrite")`. (Reality-check test stays xfail until Task 5 flips it.)
- [ ] Run `python3 -m pytest backend/tests/unit/test_chatroom_history_format.py -q` to confirm xfail collected as expected fail.
- [ ] `git commit -m "test(chatroom): document current role-confusion bug as xfail before A15 rewrite"`.

### Task 3: Rewrite _format_history_message with XML metadata + role fix

- [ ] Add failing tests in `backend/tests/unit/test_chatroom_history_format.py`:
  - `test_self_agent_uses_assistant_role_no_prefix` — sender=`agent:reviewer`, target=`reviewer` → role=assistant, content equals raw text (no `[reviewer]:` prefix).
  - `test_other_agent_uses_user_role_with_xml_metadata` — sender=`agent:reviewer`, target=`coder`, msg has `id`/`created_at`/`mentions`/`parent_message_id` → role=user, content matches regex `^<msg id="[^"]+" from="reviewer" at="[^"]+" mentions="[^"]+" parent="[^"]+">hello</msg>$`.
  - `test_user_message_xml_includes_mentions_when_present` — sender=`user`, mentions=["coder"] → role=user, content contains `from="user"` and `mentions="coder"`.
  - `test_user_message_xml_omits_mentions_when_absent` — no mentions → attribute missing.
  - `test_system_message_uses_system_event_tag` — sender=`system` → role=user, content matches `^<system_event at="[^"]+">.*</system_event>$`.
  - `test_pending_streaming_failed_status_skipped` — three messages with status pending/streaming/failed → all return `None`.
  - `test_unknown_sender_falls_back_to_unknown_msg` — sender=`weird` → role=user, content starts `<unknown_msg from="weird"`.
- [ ] Run the suite, confirm all new tests fail and the xfail from Task 2 still xfails.
- [ ] Rewrite `_format_history_message` in `backend/src/core/chatroom.py` per spec §7.3. Pull `id` / `created_at` / `mentions` / `parent_message_id` off the message dict, escape inner content with `xml.sax.saxutils.escape` (only `<`, `>`, `&` — quotes are inside attribute values which we control). Self-agent path returns `{role: "assistant", content: raw}`; other branches build attribute lists and join with single spaces.
- [ ] Run `python3 -m pytest backend/tests/unit/test_chatroom_history_format.py -q`. The xfail from Task 2 should now flip to **xpass**; remove its `@pytest.mark.xfail` decorator and re-run to confirm it passes as a regular test.
- [ ] `git commit -m "refactor(chatroom): use XML-tagged user messages and fix role assignment for other agents"`.

### Task 4: Refactor build_room_context system block to XML

- [ ] Add failing tests in `backend/tests/unit/test_chatroom.py`:
  - `test_build_room_context_system_block_uses_chatroom_context_xml` — call `build_room_context(room, "coder")` → first message role=system, content starts with `<chatroom_context>` and ends with `</chatroom_context>`.
  - `test_build_room_context_system_block_contains_protocol_section` — content includes the `<protocol>` tag and contains `chatroom_dispatch` (sourced from `CHATROOM_COLLABORATION_PROTOCOL`).
  - `test_build_room_context_system_block_lists_members_with_self_attribute` — content includes `<members self="coder">` and lists every member name (comma-separated).
  - `test_build_room_context_system_block_protocol_constant_unchanged_across_targets` — call twice with different targets → the substring between `<protocol>` and `</protocol>` is identical.
  - `test_build_room_context_system_block_uses_xml_escape_for_topic_goal` — set room topic=`A & B <test>` → topic block contains `A &amp; B &lt;test&gt;` (proves we escape).
- [ ] Run the suite and confirm failures.
- [ ] Replace the existing `system_blocks` list in `build_room_context` (chatroom.py around lines 647-661) with an XML composition. Use `xml.sax.saxutils.escape` on user-supplied fields (topic / goal / summary / members csv / target name). Embed `CHATROOM_COLLABORATION_PROTOCOL` inside `<protocol>...</protocol>` (do not escape — it is a trusted constant). Keep the function signature and return type identical.
- [ ] Run `python3 -m pytest backend/tests/unit/test_chatroom.py -q` until green. Also run the orchestrator + integration suites to catch any unrelated string-matching tests that broke (`test_chatroom_orchestrator.py`, `test_chatroom_pipeline.py`); update any that asserted on the old `[房间主题]` plain-text headers to use the new `<chatroom_context>` shape.
- [ ] `git commit -m "refactor(chatroom): structure build_room_context system block as XML with protocol section"`.

### Task 5: Add ChatPanel-isolation regression test

- [ ] Write a failing test `backend/tests/unit/test_chatroom_collaboration_protocol.py::test_protocol_does_not_leak_to_chat_panel_path` that simulates an Agent Run / ChatPanel invocation (call any non-chatroom code path that builds messages — for example, instantiate the generic Agent capability with a synthetic prompt) and asserts the resulting system message **does not** contain the literal `[聊天室协作模式]` / `<chatroom_context>` strings. The test ensures `build_room_context` is the **only** entry point that injects the protocol prefix.
- [ ] Run the test; confirm it passes already (no fix needed if §6.1 holds), or surface a leak path to fix.
- [ ] If leak found: trace the source (likely a shared prompt assembler) and gate the protocol injection behind a chatroom-only branch.
- [ ] Run `python3 -m pytest backend/tests/unit/test_chatroom_collaboration_protocol.py -q` until green.
- [ ] `git commit -m "test(chatroom): regression-pin protocol prefix to chatroom path only"`.

---

## Phase 2 — New Tools (depend on Phase 1)

### Task 6: Implement chatroom_get_goal tool

- [ ] Create `backend/tests/unit/test_chatroom_get_goal.py` with failing tests:
  - `test_returns_topic_goal_summary_members_and_role` — set up room with topic / goal / summary / members / dynamic_members, set ContextVars (`set_current_room_id`, `set_current_speaker_name`), call `await ChatroomGetGoalCapability().execute()` → returns dict with all keys, `your_role` matches the speaker name.
  - `test_includes_goal_revisions_count` — preset `goal_history` of length 3 → `goal_revisions == 3`.
  - `test_includes_goal_subgoals_when_set` — preset 2 subgoals → returned dict has `goal_subgoals` list of len 2 with `id/content/status` keys.
  - `test_outside_room_returns_permission_denied_error` — leave ContextVars unset → returns `{"error": "must be called inside a chatroom speaking task"}`.
  - `test_unknown_room_returns_error` — set ContextVar to a room id that does not exist → returns `{"error": "chatroom '...' not found"}`.
- [ ] Run the suite; confirm `ModuleNotFoundError`.
- [ ] Create `backend/src/capabilities/tools/chatroom_get_goal.py` mirroring `chatroom_set_goal.py`'s file shape: import `CapabilityBase`, `ChatroomStore`, `get_current_room_id`, `get_current_speaker_name`. The class `ChatroomGetGoalCapability` overrides `name` to `"chatroom_get_goal"`, `description` to the long-form spec §3.2 description (CC tool-description-as-prompt style with "什么时候用" / "返回什么" sections), `get_schema` returns `parameters={"type":"object","properties":{},"required":[]}`. `execute` reads ContextVars, calls `ChatroomStore().get_room(room_id)`, assembles return dict per spec §3.2.
- [ ] Run `python3 -m pytest backend/tests/unit/test_chatroom_get_goal.py -q` until green.
- [ ] `git commit -m "feat(chatroom): add chatroom_get_goal tool for reading room state"`.

### Task 7: Implement chatroom_update_goal tool with subgoal data model

- [ ] Create `backend/tests/unit/test_chatroom_update_goal.py` with failing tests:
  - `test_add_subgoal_appends_to_goal_subgoals` — room with goal "X", call execute(operation="add_subgoal", content="Y") → room.goal_subgoals length 1, status="pending", broadcast `chatroom_goal_subgoal_added` event.
  - `test_mark_done_updates_status_and_done_at` — preset subgoal id=`s1`, call execute(operation="mark_done", subgoal_id="s1") → subgoal.status=="done", `done_at` set, broadcast `chatroom_goal_subgoal_done`.
  - `test_remove_subgoal_drops_entry` — preset 2 subgoals, remove one → length 1.
  - `test_revise_replaces_main_goal_and_archives_old` — execute(operation="revise", content="brand new goal") → room.goal updated, old goal pushed to `goal_history`.
  - `test_missing_subgoal_id_returns_error` — `mark_done` without `subgoal_id` → returns error.
  - `test_unknown_subgoal_id_returns_error` — `mark_done` with id not in subgoals → returns error.
  - `test_outside_room_returns_error` — no ContextVar → permission_denied error.
- [ ] Run the suite; confirm import / attribute errors.
- [ ] Add `goal_subgoals` field to `Chatroom` data model in `backend/src/core/chatroom.py`: extend `_DEFAULT_ROOM`, the to-dict serializer, and the from-dict loader; default empty list. Add helper `ChatroomStore.apply_goal_subgoal_op(room_id, operation, *, content=None, subgoal_id=None, by=None)` that mutates `goal_subgoals` (and pushes to `goal_history` for `revise`). Use `uuid.uuid4().hex[:8]` for new subgoal ids.
- [ ] Create `backend/src/capabilities/tools/chatroom_update_goal.py` modeled on `chatroom_set_goal.py`. Description follows the spec §3.2 "什么时候用 / 什么时候不用" CC pattern. Schema enums match spec §3.2. `execute` validates required pairs (`mark_done` / `remove_subgoal` need `subgoal_id`; `add_subgoal` / `revise` need `content`), calls `ChatroomStore.apply_goal_subgoal_op`, and broadcasts the right event per operation.
- [ ] Run `python3 -m pytest backend/tests/unit/test_chatroom_update_goal.py -q` until green. Run `python3 -m pytest backend/tests/unit/test_chatroom.py -q` to confirm the existing serialization tests still pass with the new field defaults.
- [ ] `git commit -m "feat(chatroom): add chatroom_update_goal tool with subgoal data model"`.

### Task 8: Delete host_directive text protocol (single-purpose Task)

- [ ] Add a regression test `backend/tests/unit/test_chatroom_orchestrator.py::test_legacy_host_directive_parser_removed` that runs `import importlib; m = importlib.import_module("core.chatroom_orchestrator")` and asserts both `not hasattr(m, "_parse_host_directive")` and `not hasattr(m, "_extract_json_object")`. Also add `test_routes_chatrooms_no_host_prompt_injection` that imports `api.routes.chatrooms` source via `inspect.getsource` and asserts the literal substring `'"actions": [{"agent"'` is **not** present.
- [ ] Run the tests; confirm they fail because the symbols still exist.
- [ ] In `backend/src/core/chatroom_orchestrator.py`: delete the `directive_actions = _parse_host_directive(...)` block at ~lines 745-769 (the `if directive_actions:` branch including the broadcast and dispatch loop). Keep the `elif mentions:` branch but promote it to plain `if mentions:`. Delete the entire `_parse_host_directive` function (~838-883) and its helper `_extract_json_object` (~886+, scan to confirm it's only used here; if reused elsewhere — e.g. `chatroom_set_goal` — it's not, leave it only if still cited). Also drop the `import re` if it becomes unused after the helper is gone.
- [ ] In `backend/src/api/routes/chatrooms.py`: delete lines 184-207 (the `if host_in_members: host_prompt = ...; ticket = dispatch_speaking_task(...)` block) but **keep** the `else:` arm (208-222) that emits the "auto_host 已开启但主持 Agent ... 不在房间成员里" system message — that warning still applies once mentions are absent. Convert the surviving fallback into `if not mentions and bool(settings.get("auto_host")):  host_agent = settings.get("host_agent") ...; if host_agent in valid_names: dispatch_speaking_task(host_agent, parent_message_id=message["id"], store=store); else: store.add_message(...warning...)`. Drop the `host_prompt` variable entirely.
- [ ] In `backend/src/core/prompts.py` `CHATROOM_COLLABORATION_PROTOCOL` constant from Task 1, ensure no "主持人例外" clause exists (it should not — Spec 1 sub-agent had pre-warned to drop that clause; this Task is the enforcement). If anyone reintroduced it, remove it now.
- [ ] Run `python3 -m pytest backend/tests/unit/test_chatroom_orchestrator.py -q` and `python3 -m pytest backend/tests/integration/test_chatroom_pipeline.py -q`. Existing tests that asserted on the JSON-text protocol need to be deleted or rewritten to assert the new fallback (host gets called with no special prompt). List them at the top of the commit message.
- [ ] `git commit -m "refactor(chatroom): remove host_directive text protocol and JSON injection"`.

### Task 9: Implement chatroom_dispatch tool

- [ ] Create `backend/tests/unit/test_chatroom_dispatch.py` with failing tests:
  - `test_dispatch_single_agent_creates_speaking_task` — set ContextVars, room with `reviewer` member, call execute(actions=[{"agent":"reviewer"}]) → returns `{"dispatched":[{"agent":"reviewer","task_id":"...","status":"dispatched"}], "failed":[]}`. Assert `dispatch_speaking_task` was called once (use `unittest.mock.patch`).
  - `test_dispatch_multiple_agents_returns_all_dispatched` — actions for `reviewer` and `coder` → both in `dispatched`, two `dispatch_speaking_task` calls.
  - `test_dispatch_unknown_agent_lands_in_failed_with_reason` — agent `nonexistent` (not in members) → `failed: [{"agent":"nonexistent","reason":"member_not_in_room"}]`, return value still `ok` overall but reason surfaces back to LM.
  - `test_dispatch_passes_prompt_through` — action with `prompt="评一下"` → `dispatch_speaking_task` was called with `prompt="评一下"`.
  - `test_dispatch_outside_room_returns_permission_denied` — no ContextVar → error.
  - `test_dispatch_empty_actions_returns_error` — `actions=[]` → error "actions must be a non-empty array".
  - `test_dispatch_includes_parent_message_id_when_available` — set ContextVar for parent_message_id (via a new ContextVar or reuse — see notes below) → call dispatch_speaking_task with that parent.
- [ ] Run the suite; confirm import errors.
- [ ] Decide on parent_message_id propagation: the spec says use ContextVar. Add `_current_parent_message_id_cv` to `backend/src/core/task/context.py` with `get_/set_/reset_current_parent_message_id` helpers. In `chatroom_orchestrator._run_speaking_task`, set this ContextVar to `message_id` of the placeholder right after it is created (and reset in finally). Tools can read it to attach `parent_message_id` to dispatched relays.
- [ ] Create `backend/src/capabilities/tools/chatroom_dispatch.py`. Description per spec §5.3: identity short, behavior examples detailed (CC pattern), explicitly listing `✅ multi-action parallel` and `❌ wait-and-see serial` cases. Schema per §5.3. `execute` walks `actions`, validates each agent name against `members + dynamic_members`, calls `dispatch_speaking_task` for valid ones (passing `parent_message_id` from ContextVar), accumulates `dispatched` / `failed`, broadcasts `chatroom_dispatch_called` once at the end.
- [ ] Run `python3 -m pytest backend/tests/unit/test_chatroom_dispatch.py -q` until green.
- [ ] `git commit -m "feat(chatroom): add chatroom_dispatch tool replacing host_directive text protocol"`.

### Task 10: Wire chatroom_dispatch / get_goal / update_goal into autonomy tool list

- [ ] Add a failing test `backend/tests/unit/test_chatroom_orchestrator.py::test_chatroom_payload_includes_new_autonomy_tools` that builds a chatroom payload via the orchestrator entry path and asserts the resulting capability list passed to the Agent contains `chatroom_get_goal`, `chatroom_update_goal`, `chatroom_dispatch`, `chatroom_todo` (todo will be added in Task 11; for now skip with `pytest.mark.xfail` on `chatroom_todo` line).
- [ ] Run the test; confirm failure.
- [ ] Edit `backend/src/api/main.py` `_CHATROOM_AUTONOMY_TOOLS` tuple to extend with the four new tool names (drop `chatroom_todo` if Task 11 deferred). Confirm registration site `_register_dynamic_capabilities` reads this tuple OR add explicit `cap_registry.register_native(ChatroomGetGoalCapability())` etc. in the same place where `ChatroomSetGoalCapability` is registered today (search `register_native` for the chatroom_set_goal call site to find the spot).
- [ ] Run `python3 -m pytest backend/tests/unit/test_chatroom_orchestrator.py -q` until green.
- [ ] `git commit -m "feat(chatroom): register chatroom_get_goal / chatroom_update_goal / chatroom_dispatch tools"`.

### Task 11: Implement chatroom_todo tool with data model

- [ ] Create `backend/tests/unit/test_chatroom_todo.py` with failing tests:
  - `test_create_appends_todos_to_room` — execute(action="create", todos=[{"content":"X"},{"content":"Y","assignee":"reviewer"}]) → room.todos len 2, broadcast `chatroom_todo_added` once with both rows.
  - `test_create_assigns_pending_status_and_timestamps` — created todo has `status="pending"`, `created_at` / `updated_at` ISO strings, `id` is 8+ chars.
  - `test_complete_sets_status_completed_and_timestamp` — preset todo, execute(action="complete", todo_id="...") → status="completed", `updated_at` greater than initial. Broadcast `chatroom_todo_completed`.
  - `test_block_sets_status_and_optional_notes` — execute(action="block", todo_id="...", notes="waiting on X") → status="blocked", notes saved. Broadcast `chatroom_todo_updated`.
  - `test_update_modifies_content_or_assignee` — execute(action="update", todo_id="...", content="Z") → content="Z", broadcast updated event.
  - `test_delete_removes_todo` — delete → todos length -1, broadcast `chatroom_todo_deleted`.
  - `test_list_returns_all_todos_grouped_by_status` — preset mixed → returns `{"todos": [...]}` with all rows; ordering = creation order.
  - `test_unknown_todo_id_returns_error` — operations referencing nonexistent ids fail cleanly.
  - `test_outside_room_returns_permission_denied` — no ContextVar → error.
- [ ] Run the suite; confirm failures.
- [ ] Add `todos` field to `Chatroom` data model in `backend/src/core/chatroom.py`: default empty list, serialize / deserialize the same way `goal_history` is handled. Add `ChatroomStore.add_todo(room_id, content, assignee=None, parent_dispatch_id=None)`, `update_todo(room_id, todo_id, **fields)`, `list_todos(room_id)`, `delete_todo(room_id, todo_id)` methods. Use the same atomic-write JSON path.
- [ ] Create `backend/src/capabilities/tools/chatroom_todo.py`. Description follows CC tool-as-prompt style with "什么时候用" / "设计哲学：写下来你才不会忘" sentences. Schema per spec §9.3. `execute` dispatches on `action`, validates required keys per action, calls Store methods, broadcasts the corresponding WS event.
- [ ] Add `chatroom_todo` to `_CHATROOM_AUTONOMY_TOOLS` tuple. Remove the xfail mark in Task 10's test (now both `chatroom_dispatch` and `chatroom_todo` should be present).
- [ ] Run `python3 -m pytest backend/tests/unit/test_chatroom_todo.py backend/tests/unit/test_chatroom.py backend/tests/unit/test_chatroom_orchestrator.py -q` until green.
- [ ] `git commit -m "feat(chatroom): add chatroom_todo tool and Chatroom.todos data model"`.

### Task 12: Auto-create todos on chatroom_dispatch and auto-complete on speak-task done

- [ ] Add failing tests in `backend/tests/integration/test_chatroom_pipeline.py`:
  - `test_dispatch_auto_creates_pending_todos_with_parent_dispatch_id` — call chatroom_dispatch for 2 actions → 2 new todos with `assignee=action.agent`, `parent_dispatch_id=task_id`, `status=pending`.
  - `test_speak_task_done_auto_completes_associated_todo` — dispatch agent → orchestrator finishes speaking task → matching todo flipped to `status=completed`. Broadcast `chatroom_todo_completed` on completion.
- [ ] Run; confirm failure.
- [ ] In `chatroom_dispatch.execute`, after calling `dispatch_speaking_task` for each successful action, also call `ChatroomStore().add_todo(room_id, content=action.prompt or f"Speak as {agent}", assignee=action.agent, parent_dispatch_id=task_id)` and broadcast `chatroom_todo_added` with the created list.
- [ ] In `chatroom_orchestrator._run_speaking_task` finally-block (after `mark_done` succeeds with status==COMPLETED, before ContextVar resets), look up todos with `parent_dispatch_id == task_id` and call `ChatroomStore().update_todo(room_id, todo_id, status="completed")` for each, broadcasting `chatroom_todo_completed`.
- [ ] Run the integration suite until green.
- [ ] `git commit -m "feat(chatroom): auto-create todos on dispatch and auto-complete on speak-task done"`.

---

## Phase 3 — Runtime Refinements

### Task 13: build_system_reminders helper + injection into payload

- [ ] Create `backend/tests/unit/test_chatroom_system_reminders.py` with failing tests:
  - `test_build_system_reminders_returns_empty_when_nothing_changed` — fresh room, target speaker has no prior message → returns `""`.
  - `test_includes_goal_change_when_goal_modified_after_last_speech` — prev message of speaker has timestamp T1, goal_history shows update at T2 > T1 → returns string contains "目标在你上次发言后被" and the new goal text.
  - `test_includes_new_member_added_after_last_speech` — `dynamic_members[0].joined_at > T1` → string contains "新成员".
  - `test_includes_at_mention_marker_when_parent_message_mentions_speaker` — parent message mentions=[speaker_name] → string contains "你刚被 @ 了".
  - `test_truncates_to_first_three_when_too_many_signals` — synthesize 5 distinct change signals → result has at most 3 lines.
  - `test_no_reminder_when_first_speech` — speaker has no prior messages → returns "".
- [ ] Run the suite; confirm failures.
- [ ] Add a new module `backend/src/core/chatroom_reminders.py` (or place inside `core/chatroom.py` if smaller). Implement `build_system_reminders(room: Dict, target_agent: str, parent_message_id: Optional[str]) -> str`. Logic: compute speaker's last `created_at`; collect signals (goal change, new member, mentioned, last-tool-failure if recoverable); render each as one short line. Truncate to 3.
- [ ] In `chatroom_orchestrator._run_speaking_task`, after `context_messages = build_room_context(...)` (~line 577), call `reminders = build_system_reminders(room_snapshot, agent_name, parent_message_id)` and if non-empty, append `{"role":"user","content": f"<system-reminder>\n{reminders}\n</system-reminder>"}` to `context_messages` **after** the history (so it is the last user message before the dispatch prompt). Broadcast `chatroom_system_reminder` with the reminders list for debugging.
- [ ] Run `python3 -m pytest backend/tests/unit/test_chatroom_system_reminders.py backend/tests/unit/test_chatroom_orchestrator.py -q` until green.
- [ ] `git commit -m "feat(chatroom): inject runtime <system-reminder> blocks for goal/member/mention changes"`.

### Task 14: A21 — Default-block dispatch_agent in chatroom payload

- [ ] Add failing tests in `backend/tests/unit/test_chatroom_orchestrator.py`:
  - `test_chatroom_default_blocks_dispatch_agent` — build payload for default settings room → tool list does **not** include `dispatch_agent`.
  - `test_chatroom_with_allow_subagent_dispatch_includes_dispatch_agent` — settings.allow_subagent_dispatch=True → tool list includes `dispatch_agent`.
- [ ] Run; confirm failures.
- [ ] In `chatroom_orchestrator._run_speaking_task` where the payload is assembled, intercept the capability/tool list before passing to `cap.execute_stream`. Add a filter: if `room_snapshot.get("settings", {}).get("allow_subagent_dispatch", False)` is **False**, drop any tool whose name == `"dispatch_agent"` from the payload's tool list. Implement this by reading the agent's currently-bound tool list and constructing a filtered subset (or by passing `_excluded_tools=["dispatch_agent"]` if the agent supports such a kwarg — pick whichever matches the existing payload contract; check how `chatroom_invite` etc. propagate today).
- [ ] In `backend/src/core/chatroom.py` `DEFAULT_SETTINGS`, add `"allow_subagent_dispatch": False`.
- [ ] Run the unit suite until green.
- [ ] `git commit -m "feat(chatroom): default-block dispatch_agent inside chatrooms (allow_subagent_dispatch opt-in)"`.

### Task 15: Broadcast chatroom_dispatch_called WS event

- [ ] Add a failing test `backend/tests/unit/test_chatroom_websocket.py::test_chatroom_dispatch_called_event_broadcasted` (extend the existing file) that mocks `broadcast_chatroom_event` and asserts the new event payload `{room_id, dispatcher, dispatched_task_ids: [...], actions: [...]}` is broadcast exactly once when `chatroom_dispatch.execute` succeeds.
- [ ] Run; confirm failure.
- [ ] Confirm the broadcast is wired in Task 9. If missing, add the call in `chatroom_dispatch.execute` after collecting the dispatched list.
- [ ] Run `python3 -m pytest backend/tests/unit/test_chatroom_websocket.py -q` until green.
- [ ] `git commit -m "feat(chatroom): broadcast chatroom_dispatch_called WS event"`.

---

## Phase 4 — Frontend

### Task 16: Add ChatroomTodo / ChatroomGoalSubgoal TypeScript types and Chatroom extensions

- [ ] In `frontend/src/types/index.ts`, add:
  - `interface ChatroomTodo { id: string; content: string; status: 'pending'|'in_progress'|'completed'|'blocked'; assignee: string|null; created_at: string; updated_at: string; parent_dispatch_id: string|null; notes: string|null }`
  - `interface ChatroomGoalSubgoal { id: string; content: string; status: 'pending'|'done'; created_at: string; done_at: string|null }`
  - extend `interface Chatroom` with `todos?: ChatroomTodo[]; goal_subgoals?: ChatroomGoalSubgoal[]`
  - extend `interface ChatroomSettings` with `allow_subagent_dispatch?: boolean`
  - extend the `WSEvent` discriminated union with new event types: `chatroom_dispatch_called`, `chatroom_todo_added`, `chatroom_todo_updated`, `chatroom_todo_completed`, `chatroom_todo_deleted`, `chatroom_goal_subgoal_added`, `chatroom_goal_subgoal_done`, `chatroom_system_reminder`. Each carries `room_id` plus event-specific data.
- [ ] Run `cd frontend && npx tsc --noEmit` to confirm types compile (no test runner is gating frontend types — TS compile is the failure signal).
- [ ] `git commit -m "feat(chatroom): add ChatroomTodo / ChatroomGoalSubgoal TS types and WS event variants"`.

### Task 17: Render TodoBanner above messages and subgoal list inside goal banner

- [ ] In `frontend/src/components/ChatroomPanel.tsx`, add a new `<TodoBanner room={room} />` component near the top of the message-stream column (above `<ChatroomBanner>`). It groups `room.todos` by status, renders pending/in-progress at top, completed/blocked collapsed. Each row shows assignee chip, content, and a status badge.
- [ ] Inside the existing goal banner section (around line 947 — where `room.goal` is rendered), append a `<SubgoalList subgoals={room.goal_subgoals} />` showing each as a checkbox-styled row (☐ pending / ✔ done with strikethrough).
- [ ] Add corresponding CSS in `frontend/src/components/ChatroomPanel.css`: `.chatroom-todos`, `.chatroom-todo`, `.chatroom-todo--pending/completed/blocked`, `.chatroom-subgoals`, `.chatroom-subgoal--done`. Match the existing color tokens and spacing.
- [ ] Run `cd frontend && npx tsc --noEmit && npm run build`. Confirm no errors. (No explicit failing test step — frontend changes are visual + type-checked.)
- [ ] `git commit -m "feat(chatroom): render TodoBanner and subgoal list in ChatroomPanel"`.

### Task 18: Subscribe to new WS events and update local state

- [ ] In `frontend/src/components/ChatroomPanel.tsx`, extend the WebSocket event handler `switch` (around line 315) to handle:
  - `chatroom_dispatch_called` — toast/log; optionally flash a "Host 派发了 N 人" notice.
  - `chatroom_todo_added` — append to room.todos.
  - `chatroom_todo_updated` / `chatroom_todo_completed` — replace matching row.
  - `chatroom_todo_deleted` — filter out by id.
  - `chatroom_goal_subgoal_added` — append.
  - `chatroom_goal_subgoal_done` — flip status.
  - `chatroom_system_reminder` — only logged in console (debug mode) for now; no UI surface in this Task.
- [ ] Make sure each handler dispatches through the existing `setRoom` / context-store pattern (don't bypass the reducer). Refresh `room.todos` immutably.
- [ ] Run `cd frontend && npx tsc --noEmit && npm run build`.
- [ ] Manually open the Chatroom panel (developer note: not part of CI), trigger a dispatch via the backend, watch the TodoBanner update without page reload.
- [ ] `git commit -m "feat(chatroom): subscribe to chatroom_todo_* and chatroom_goal_subgoal_* WS events"`.

---

## Phase 5 — Documentation Sync

### Task 19: Update CLAUDE.md §3.10 chatroom section

- [ ] Edit `agentic-system/CLAUDE.md` §3.10 ("Agent 聊天室（Chatroom）"):
  - Add tool names `chatroom_get_goal`, `chatroom_update_goal`, `chatroom_dispatch`, `chatroom_todo` to the autonomy-tools list.
  - Note the system block is now XML (`<chatroom_context>`) and history uses XML metadata for non-self messages.
  - Note `dispatch_agent` is default-blocked, opt-in via `settings.allow_subagent_dispatch`.
  - Document the `<system-reminder>` injection mechanism with a one-line description.
  - Update the WebSocket events list with `chatroom_dispatch_called`, `chatroom_todo_*`, `chatroom_goal_subgoal_*`, `chatroom_system_reminder`.
  - Cross-reference the spec file `docs/superpowers/specs/2026-05-28-chatroom-collaboration-design.md`.
- [ ] Edit `docs/superpowers/specs/2026-05-26-agent-chatroom-design.md` (original chatroom spec) — append a "2026-05-28 update" pointer that says "see 2026-05-28-chatroom-collaboration-design.md for collaboration refactor (host_directive removed, XML context, system-reminder, todos)".
- [ ] No test step. Run `git diff --stat` and confirm only docs touched in this commit.
- [ ] `git commit -m "docs(chatroom): document collaboration refactor in CLAUDE.md and original spec"`.

### Task 20: Final integration sweep + verification

- [ ] Run the entire backend suite: `python3 -m pytest backend/tests/ -q`. Confirm zero failures (baseline before refactor: 798 tests).
- [ ] Run frontend build: `cd frontend && npm run build`. Confirm zero errors.
- [ ] Run a quick manual e2e: start backend (`cd backend/src && uvicorn api.main:app --reload`) + frontend, create a chatroom with auto_host enabled, send a message without `@`, watch the host call `chatroom_dispatch` (and **no** JSON appears in the message body). Verify TodoBanner populates and a dispatched agent's todo flips to completed when its speaking task ends.
- [ ] Inspect `git log --oneline` and confirm Task ordering / commit messages match the plan.
- [ ] Run `grep -r "_parse_host_directive\|host_directive" backend/src` and confirm zero hits (final regression check).
- [ ] Run `grep -r "actions.*agent.*prompt" backend/src/api/routes/chatrooms.py` and confirm zero hits.
- [ ] `git commit --allow-empty -m "chore(chatroom): close 2026-05-28 collaboration refactor"` (only if some untracked verification artifacts need a marker — usually skip).

---

## Risk Notes (carry from spec §15)

- **A2 host-exception clause cleanup**: Spec 1 (urgent-bugfix) sub-agent already pre-warned to remove the "主持人例外" line from the `CHATROOM_COLLABORATION_PROTOCOL` constant. Task 1 must produce the constant **without** that clause; Task 8 enforces and asserts it.
- **A15 role-confusion severity**: Other agents previously used `role=assistant` (not `role=user` as initially assumed in the design draft). Task 2's xfail test makes this explicit so the implementer cannot mis-read the bug.
- **XML in history**: Some LM providers may not love XML inside user-role content. Task 3 tests cover OpenAI / Anthropic / DeepSeek behavior implicitly through the existing integration suite. If a provider chokes, the fallback is to keep the `<msg>` tag but plain-prefix the content (`<msg ...>{content}</msg>` is provider-agnostic).
- **Feature flag**: spec §15.2 mentions `chatroom.use_xml_context: True`. Optional and not blocking; recommend skipping in this plan to avoid scope creep — add only if a provider actually breaks.
- **Frontend testing**: this codebase has no Jest / Vitest. Frontend tasks rely on `tsc --noEmit` and `npm run build` as the gating signal. This is consistent with prior plans (`2026-05-09-autonomous-memory-workspace.md`).
- **Order discipline**: A14 (Task 1) must land before A13 (Task 8) because Task 8's regression test reads the protocol constant. A15 (Task 3) must land before A16 (Task 13) because reminders are appended after history and the history shape now uses XML.
- **parent_message_id ContextVar**: introduced in Task 9; do not skip it — without it, dispatched relays lose their reply-thread metadata in the XML history.

---

## Verification Matrix

| Phase | Backend tests must pass | Frontend gate |
|---|---|---|
| Phase 1 | `test_chatroom.py`, `test_chatroom_history_format.py`, `test_chatroom_collaboration_protocol.py` | — |
| Phase 2 | + `test_chatroom_get_goal.py`, `test_chatroom_update_goal.py`, `test_chatroom_dispatch.py`, `test_chatroom_todo.py`, `test_chatroom_orchestrator.py`, `test_chatroom_pipeline.py` | — |
| Phase 3 | + `test_chatroom_system_reminders.py`, `test_chatroom_websocket.py` | — |
| Phase 4 | (Phase 3 sets) | `tsc --noEmit && npm run build` |
| Phase 5 | full backend suite green | full frontend build green |

---

**Plan complete.** 5 phases, 20 tasks. Ready for subagent-driven execution.
