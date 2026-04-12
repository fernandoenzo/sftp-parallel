# Continuation Plugin — Full Review Plan

## TL;DR

> **Review and improve** the continuation.ts plugin across 4 areas: bugs/robustness, performance, refactoring, and architecture. 6 critical issues found: memory leaks in 4 Maps, N+1 query pattern, nudge race condition, silent error swallowing, type safety gaps, and missing cleanup on session completion.

> **Deliverables**:
> - 6 targeted fixes in continuation.ts
> - Memory management system for Maps/Sets
> - Parallel session fetching in watcher
> - Type safety improvements
> - Logging improvements

> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 3 waves + final verification
> **Critical Path**: Task 1 (memory) → Tasks 2-6 (parallel) → Task 7 (integration) → F1-F4

---

## Context

### Original Request
User asked for a review plan covering bugs, implementation improvements, refactorings, and architecture — not just bug fixes.

### Review Findings

**Oracle Deep Code Review (6 critical issues):**

1. **Memory Leaks (High)**: `nudgeCounts` never cleaned up. `sends` only pruned on access. `busyStartTimes` only cleaned when session goes non-busy. Deleted sessions leak forever.
2. **N+1 Query Pattern**: `checkStuckChildSessions` calls `session.get()` sequentially inside a for loop for each busy session. With 50 sessions = 5s per tick.
3. **Race Condition**: `handleChildSession` checks `nudgeInProgress` BEFORE `maxNudges`. Should reorder maxNudges first.
4. **Silent Error Swallowing**: `client.session.abort().catch(() => {})` at lines 176/288 swallows errors.
5. **Type Safety**: Handler parameters use `any` types. SDK provides proper types.
6. **Missing Cleanup**: When session completes with end marker, `nudgeCounts` entry persists forever.

**Explore Plugin Patterns:**
- No `unload` hook in plugin interface — watcher and Maps persist until process restart
- continuation.ts is the only plugin — no other patterns to compare against
- All `.catch()` handlers either swallow silently or log

---

## Work Objectives

### Core Objective
Fix 6 critical issues and improve code quality across robustness, performance, refactoring, and architecture.

### Concrete Deliverables
- Memory cleanup system for all 4 Maps/Sets
- Parallelized session fetching in watcher
- Reordered nudge checks (maxNudges before nudgeInProgress)
- Logged abort errors instead of silent swallow
- Proper TypeScript types replacing `any`
- nudgeCounts cleanup on session completion

### Definition of Done
- [x] All Maps/Sets have cleanup mechanism (periodic sweep or on-event cleanup)
- [x] Watcher fetches child sessions in parallel (no N+1)
- [x] maxNudges check happens before nudgeInProgress check
- [x] All abort errors are logged (not silently swallowed)
- [x] Handler parameters use proper SDK types (no `any`)
- [x] nudgeCounts reset when session completes with end marker
- [x] Rate limit hits logged at debug level
- [x] All existing tests pass (parent continuation unchanged)

### Must Have
- Memory cleanup for nudgeCounts, sends, busyStartTimes, nudgeInProgress
- Parallelized session.get() in watcher
- maxNudges check before nudgeInProgress check
- Log abort errors instead of silently swallowing
- nudgeCounts cleanup on session completion
- Rate limit hit logging

### Must NOT Have (Guardrails)
- MUST NOT change parent continuation behavior
- MUST NOT change CONFIG defaults (3/60s, 3min timeout, etc.)
- MUST NOT add external dependencies
- MUST NOT change nudge/continuation messages
- MUST NOT add unload hook (not available in Plugin interface)
- MUST NOT persist state to disk

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: NO
- **Automated tests**: NO
- **Framework**: none
- **Agent-Executed QA**: ALWAYS (mandatory for all tasks)

### QA Policy
Every task includes agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Foundation — blocks all):
└── Task 1: Memory management system [deep]

Wave 2 (After Wave 1 — parallel fixes):
├── Task 2: Parallelize watcher session fetching [quick]
├── Task 3: Fix nudge check ordering [quick]
├── Task 4: Log abort and rate-limit errors [quick]
├── Task 5: Replace any with proper types [unspecified-high]
└── Task 6: Add nudgeCounts cleanup on completion [quick]

Wave 3 (After Wave 2 — integration):
└── Task 7: Final integration + logging sweep [deep]

Wave FINAL (After ALL tasks — 4 parallel reviews):
├── F1: Plan compliance audit (oracle)
├── F2: Code quality review (unspecified-high)
├── F3: Real manual QA (unspecified-high)
└── F4: Scope fidelity check (deep)
→ Present results → Get explicit user okay
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|-----------|--------|
| 1 | — | 7 |
| 2 | — | 7 |
| 3 | — | 7 |
| 4 | — | 7 |
| 5 | — | 7 |
| 6 | 1 | 7 |
| 7 | 1-6 | F1-F4 |

### Agent Dispatch Summary

- **Wave 1**: 1 agent — T1 → `deep`
- **Wave 2**: 5 agents — T2 → `quick`, T3 → `quick`, T4 → `quick`, T5 → `unspecified-high`, T6 → `quick`
- **Wave 3**: 1 agent — T7 → `deep`
- **FINAL**: 4 agents — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [x] 1. Memory management system for Maps/Sets

  **What to do**:
  - Add a `cleanupStaleEntries()` function that sweeps all Maps/Sets and removes entries for sessions that no longer exist
  - Call `cleanupStaleEntries()` periodically in the watcher (every 5 minutes or on every 10th tick)
  - Call `resetNudgeCount(sessionID)` when a session completes with end marker (in `handleChildSession`)
  - Call `busyStartTimes.delete(sessionID)` in `handleChildSession` idle handler when a child session goes idle (it's no longer busy)
  - Add `sends.delete(sessionID)` and `nudgeCounts.delete(sessionID)` cleanup in the periodic sweep for sessions not seen in recent status

  **Must NOT do**:
  - Do NOT add unload hook (not available in Plugin interface)
  - Do NOT persist state to disk
  - Do NOT change CONFIG defaults

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO — blocks Task 7
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 6, 7
  - **Blocked By**: None

  **References**:
  - `/home/fernando/.config/opencode/plugins/continuation.ts:65-74` — All 4 Maps/Sets declarations
  - `/home/fernando/.config/opencode/plugins/continuation.ts:99-112` — `recentPromptCount` (only place that prunes `sends`)
  - `/home/fernando/.config/opencode/plugins/continuation.ts:141-209` — `checkStuckChildSessions` (where periodic cleanup should be added)
  - `/home/fernando/.config/opencode/plugins/continuation.ts:298-304` — End marker check in `handleChildSession` (where `resetNudgeCount` should be called)
  - `/home/fernando/.config/opencode/plugins/continuation.ts:148-151` — `busyStartTimes.delete(sessionID)` for non-busy sessions (existing cleanup pattern to follow)

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Stale entries cleaned up periodically
    Tool: Bash (grep)
    Preconditions: continuation.ts with cleanup function
    Steps:
      1. Search for `cleanupStaleEntries` function definition
      2. Verify it deletes entries from sends, nudgeCounts, busyStartTimes
      3. Verify it's called from the watcher or event handler
    Expected Result: Cleanup function exists and is called periodically
    Failure Indicators: No cleanup function, or function exists but never called
    Evidence: .sisyphus/evidence/task-1-stale-cleanup.txt

  Scenario: nudgeCounts cleaned on session completion
    Tool: Bash (grep)
    Preconditions: continuation.ts with cleanup
    Steps:
      1. Search for `resetNudgeCount` calls in handleChildSession
      2. Verify it's called before `return` in the end-marker check
    Expected Result: nudgeCounts entry removed when session completes with ■
    Failure Indicators: No resetNudgeCount call in end-marker check
    Evidence: .sisyphus/evidence/task-1-nudge-cleanup.txt

  Scenario: busyStartTimes cleaned on idle transition
    Tool: Bash (grep)
    Preconditions: continuation.ts with cleanup
    Steps:
      1. Search for `busyStartTimes.delete` in event handler or handleChildSession
      2. Verify it's called when a child session goes idle (no longer busy)
    Expected Result: busyStartTimes entry removed when child goes idle
    Failure Indicators: No cleanup in idle handler
    Evidence: .sisyphus/evidence/task-1-busy-cleanup.txt
  ```

  **Commit**: YES (groups with all tasks)
  - Message: `fix(continuation): memory management, performance, and robustness improvements`
  - Files: `/home/fernando/.config/opencode/plugins/continuation.ts`

- [x] 2. Parallelize watcher session fetching

  **What to do**:
  - In `checkStuckChildSessions()`, filter busy sessions first, then fetch their details in parallel using `Promise.all`
  - Replace the sequential `for` loop that calls `await client.session.get()` for each busy session with a parallel batch
  - Structure: `Object.entries(statusResult.data).filter(busy).map(getSession).then(process)`

  **Must NOT do**:
  - Do NOT change the overall watcher logic
  - Do NOT change CONFIG defaults
  - Do NOT remove the sequential nudge sending (prompts should still be sequential)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 3-6)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 7
  - **Blocked By**: None

  **References**:
  - `/home/fernando/.config/opencode/plugins/continuation.ts:141-209` — Current sequential `checkStuckChildSessions` implementation
  - `/home/fernando/.config/opencode/plugins/continuation.ts:155-156` — The N+1 query: `await client.session.get()` inside `for` loop

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Session details fetched in parallel
    Tool: Bash (grep)
    Preconditions: continuation.ts with parallelized watcher
    Steps:
      1. Search for `Promise.all` in `checkStuckChildSessions`
      2. Verify it's used to batch `client.session.get()` calls
      3. Verify the sequential `for` loop with `await client.session.get()` is gone
    Expected Result: Session details fetched via Promise.all, not sequential await
    Failure Indicators: Still using sequential await inside for loop
    Evidence: .sisyphus/evidence/task-2-parallel-fetch.txt
  ```

  **Commit**: YES (groups with all tasks)
  - Message: `fix(continuation): memory management, performance, and robustness improvements`
  - Files: `/home/fernando/.config/opencode/plugins/continuation.ts`

- [x] 3. Fix nudge check ordering

  **What to do**:
  - In `handleChildSession`, reorder checks so `maxNudges` is checked BEFORE `nudgeInProgress`
  - Current order: nudgeInProgress → maxNudges → endMarker → rateLimit → send
  - New order: maxNudges → nudgeInProgress → endMarker → rateLimit → send
  - Rationale: If maxNudges is reached, we should abort immediately without checking nudgeInProgress. This avoids the case where nudgeInProgress blocks an abort that should happen.

  **Must NOT do**:
  - Do NOT change the abort logic itself
  - Do NOT change the end marker check
  - Do NOT change the rate limit check

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 2, 4-6)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 7
  - **Blocked By**: None

  **References**:
  - `/home/fernando/.config/opencode/plugins/continuation.ts:280-312` — Current `handleChildSession` with wrong check order
  - `/home/fernando/.config/opencode/plugins/continuation.ts:280-283` — nudgeInProgress check (move after maxNudges)
  - `/home/fernando/.config/opencode/plugins/continuation.ts:286-295` — maxNudges check (move first)

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: maxNudges checked before nudgeInProgress
    Tool: Bash (grep)
    Preconditions: continuation.ts with reordered checks
    Steps:
      1. Read handleChildSession function
      2. Verify maxNudges check comes BEFORE nudgeInProgress check
      3. Verify the order is: maxNudges → nudgeInProgress → endMarker → rateLimit → send
    Expected Result: maxNudges is first guard, nudgeInProgress is second
    Failure Indicators: nudgeInProgress still checked before maxNudges
    Evidence: .sisyphus/evidence/task-3-check-order.txt
  ```

  **Commit**: YES (groups with all tasks)
  - Message: `fix(continuation): memory management, performance, and robustness improvements`
  - Files: `/home/fernando/.config/opencode/plugins/continuation.ts`

- [x] 4. Log abort and rate-limit errors

  **What to do**:
  - Replace `client.session.abort().catch(() => {})` with a logged error: `.catch(async (err) => { await log("error", ...err.message...) })` at lines 176 and 288
  - Add debug-level logging when rate limit is hit in `handleParentSession` (line 221) and `handleChildSession` (line 310)
  - Add debug logging in `checkStuckChildSessions` when rate limit is hit (line 171)
  - Add debug logging in `handleChildSession` when nudgeInProgress blocks a nudge

  **Must NOT do**:
  - Do NOT change the abort behavior (still try to abort, just log failures)
  - Do NOT change the rate limit behavior (still return, just log before returning)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 2, 3, 5, 6)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 7
  - **Blocked By**: None

  **References**:
  - `/home/fernando/.config/opencode/plugins/continuation.ts:176` — `client.session.abort().catch(() => {})` in watcher
  - `/home/fernando/.config/opencode/plugins/continuation.ts:288` — `client.session.abort().catch(() => {})` in handleChildSession
  - `/home/fernando/.config/opencode/plugins/continuation.ts:220-221` — Rate limit silent return in handleParentSession
  - `/home/fernando/.config/opencode/plugins/continuation.ts:309-311` — Rate limit silent return in handleChildSession
  - `/home/fernando/.config/opencode/plugins/continuation.ts:170-171` — Rate limit silent return in checkStuckChildSessions

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Abort errors are logged
    Tool: Bash (grep)
    Preconditions: continuation.ts with logged aborts
    Steps:
      1. Search for `session.abort` in continuation.ts
      2. Verify both instances (watcher + handleChildSession) have .catch with logging
      3. Verify log includes sessionID and error message
    Expected Result: Both abort calls log failures instead of silently swallowing
    Failure Indicators: Any `.catch(() => {})` on abort still present
    Evidence: .sisyphus/evidence/task-4-abort-logging.txt

  Scenario: Rate limit hits are logged
    Tool: Bash (grep)
    Preconditions: continuation.ts with rate limit logging
    Steps:
      1. Search for rate limit return statements
      2. Verify debug log before each return
      3. Verify all 3 locations: handleParentSession, handleChildSession, checkStuckChildSessions
    Expected Result: Rate limit hits logged at debug level before returning
    Failure Indicators: Silent returns without logging
    Evidence: .sisyphus/evidence/task-4-ratelimit-logging.txt
  ```

  **Commit**: YES (groups with all tasks)
  - Message: `fix(continuation): memory management, performance, and robustness improvements`
  - Files: `/home/fernando/.config/opencode/plugins/continuation.ts`

- [x] 5. Replace `any` with proper SDK types

  **What to do**:
  - Import `AssistantMessage` and `Message` types from the SDK
  - Replace `last: any` with a proper type in `handleParentSession` and `handleChildSession`
  - Replace `_messages: Array<any>` with `messages: Message[]` (or the appropriate SDK type)
  - Find the SDK type for messages returned by `client.session.messages()`
  - Verify the types compile correctly

  **Must NOT do**:
  - Do NOT change any runtime behavior
  - Do NOT add new imports beyond SDK types
  - Do NOT change function logic

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 2-4, 6)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 7
  - **Blocked By**: None

  **References**:
  - `/home/fernando/.config/opencode/plugins/continuation.ts:212-216` — `handleParentSession` with `any` types
  - `/home/fernando/.config/opencode/plugins/continuation.ts:262-268` — `handleChildSession` with `any` types
  - `/home/fernando/.config/opencode/node_modules/@opencode-ai/sdk/dist/gen/types.gen.d.ts` — SDK type definitions (search for Message, AssistantMessage, etc.)

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: No `any` types in handler signatures
    Tool: Bash (grep)
    Preconditions: continuation.ts with proper types
    Steps:
      1. Search for `: any` in continuation.ts
      2. Verify handler function signatures don't use `any`
      3. Verify types are imported from SDK
    Expected Result: Zero `: any` in handler function parameters
    Failure Indicators: `any` type still present in handler signatures
    Evidence: .sisyphus/evidence/task-5-type-safety.txt
  ```

  **Commit**: YES (groups with all tasks)
  - Message: `fix(continuation): memory management, performance, and robustness improvements`
  - Files: `/home/fernando/.config/opencode/plugins/continuation.ts`

- [x] 6. Add nudgeCounts cleanup on session completion

  **What to do**:
  - In `handleChildSession`, call `resetNudgeCount(sessionID)` before returning when end marker is detected
  - Also call `busyStartTimes.delete(sessionID)` when child session goes idle (it's no longer busy)
  - This ensures completed sessions don't leak nudgeCounts entries

  **Must NOT do**:
  - Do NOT change end marker detection logic
  - Do NOT change continuation behavior for parent sessions

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 2-5)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 7
  - **Blocked By**: Task 1 (for cleanup function pattern)

  **References**:
  - `/home/fernando/.config/opencode/plugins/continuation.ts:298-304` — End marker check in `handleChildSession` (where `resetNudgeCount` should be called)
  - `/home/fernando/.config/opencode/plugins/continuation.ts:130` — `resetNudgeCount` function (already exists, just needs to be called)

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: nudgeCounts reset on session completion
    Tool: Bash (grep)
    Preconditions: continuation.ts with cleanup
    Steps:
      1. Search for `resetNudgeCount` calls in handleChildSession
      2. Verify it's called before `return` in the end-marker check block
    Expected Result: resetNudgeCount called when session completes with ■
    Failure Indicators: No resetNudgeCount call in end-marker check
    Evidence: .sisyphus/evidence/task-6-nudge-cleanup.txt
  ```

  **Commit**: YES (groups with all tasks)
  - Message: `fix(continuation): memory management, performance, and robustness improvements`
  - Files: `/home/fernando/.config/opencode/plugins/continuation.ts`

- [x] 7. Final integration and logging sweep

  **What to do**:
  - Wire all changes from Tasks 1-6 together
  - Verify no regressions in parent continuation behavior
  - Add watcher reentrancy guard (prevent concurrent ticks)
  - Ensure all new log messages use consistent format: `{sessionID, ...context}`
  - Verify that the `recentPromptCount` rename from the subagent feature is still correct (not `recentCount`)

  **Must NOT do**:
  - Do NOT change parent continuation behavior
  - Do NOT add external dependencies
  - Do NOT change CONFIG defaults

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO — depends on Tasks 1-6
  - **Parallel Group**: Wave 3
  - **Blocks**: F1-F4
  - **Blocked By**: Tasks 1-6

  **References**:
  - `/home/fernando/.config/opencode/plugins/continuation.ts` — Complete file after all changes

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Parent continuation behavior unchanged
    Tool: Bash (grep)
    Preconditions: All changes integrated
    Steps:
      1. Verify handleParentSession uses CONFIG.message (not CONFIG.nudgeMessage)
      2. Verify handleParentSession uses CONFIG.endMarker for cut-off detection
      3. Verify handleParentSession uses recentPromptCount for rate limiting
      4. Verify parent continuation prompt is fire-and-forget (no await)
    Expected Result: Parent behavior identical to original
    Failure Indicators: Different message, different logic, missing checks
    Evidence: .sisyphus/evidence/task-7-parent-unchanged.txt

  Scenario: Watcher reentrancy guard
    Tool: Bash (grep)
    Preconditions: All changes integrated
    Steps:
      1. Search for reentrancy guard in watcher (e.g., isRunning flag or similar)
      2. Verify it prevents concurrent checkStuckChildSessions execution
    Expected Result: Watcher cannot run concurrently with itself
    Failure Indicators: No reentrancy guard
    Evidence: .sisyphus/evidence/task-7-reentrancy.txt

  Scenario: All Maps have cleanup mechanism
    Tool: Bash (grep)
    Preconditions: All changes integrated
    Steps:
      1. Verify cleanupStaleEntries function exists
      2. Verify it's called periodically
      3. Verify nudgeCounts.delete is called on session completion
      4. Verify busyStartTimes.delete is called when session goes idle
    Expected Result: All 4 Maps/Sets have cleanup paths
    Failure Indicators: Any Map without a cleanup mechanism
    Evidence: .sisyphus/evidence/task-7-cleanup-mechanism.txt

  Scenario: Consistent log format
    Tool: Bash (grep)
    Preconditions: All changes integrated
    Steps:
      1. Search for all `await log(` calls
      2. Verify each includes sessionID in the extra object
      3. Verify no `.catch(() => {})` on abort calls
    Expected Result: All log calls include sessionID, no silent abort catches
    Failure Indicators: Log without sessionID, or silent abort catch
    Evidence: .sisyphus/evidence/task-7-log-format.txt
  ```

  **Commit**: YES (final commit)
  - Message: `fix(continuation): memory management, performance, and robustness improvements`
  - Files: `/home/fernando/.config/opencode/plugins/continuation.ts`
  - Pre-commit: `node -e "const fs = require('fs'); const code = fs.readFileSync('/home/fernando/.config/opencode/plugins/continuation.ts', 'utf8'); console.log('File valid, length:', code.length)"`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

- [x] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. Verify: memory cleanup exists, N+1 fixed, check ordering corrected, abort errors logged, types improved, nudgeCounts cleanup added. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [x] F2. **Code Quality Review** — `unspecified-high`
  Review all changes for: `as any`/`@ts-ignore`, empty catches, console.log, commented code, unused imports, AI slop. Verify no regressions in parent behavior.
  Output: `Build [PASS/FAIL] | Types [PASS/FAIL] | Files [N clean/N issues] | VERDICT`

- [x] F3. **Real Manual QA** — `unspecified-high`
  Execute every QA scenario from Tasks 1-7. Test parent continuation still works. Test child nudge still works. Test watcher still works. Test memory cleanup. Test parallel fetching. Verify no regressions.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [x] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff. Verify 1:1 correspondence. No scope creep. No unaccounted changes.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **1**: `fix(continuation): memory management, performance, and robustness improvements` — continuation.ts

---

## Success Criteria

### Verification Commands
```bash
# Verify no `any` types in handler signatures
node -e "const fs = require('fs'); const code = fs.readFileSync('/home/fernando/.config/opencode/plugins/continuation.ts', 'utf8'); const anyCount = (code.match(/: any/g) || []).length; console.log('any types in signatures:', anyCount)"

# Verify no silent abort catches
node -e "const fs = require('fs'); const code = fs.readFileSync('/home/fernando/.config/opencode/plugins/continuation.ts', 'utf8'); const silentCatches = (code.match(/\.catch\(\(\) => \{\}\)/g) || []).length; console.log('Silent abort catches:', silentCatches)"

# Verify memory cleanup function exists
node -e "const fs = require('fs'); const code = fs.readFileSync('/home/fernando/.config/opencode/plugins/continuation.ts', 'utf8'); console.log('Has cleanupStaleEntries:', code.includes('cleanupStaleEntries')); console.log('Has resetNudgeCount in handleChildSession:', code.includes('resetNudgeCount'))"

# Verify Promise.all in watcher
node -e "const fs = require('fs'); const code = fs.readFileSync('/home/fernando/.config/opencode/plugins/continuation.ts', 'utf8'); console.log('Has Promise.all in checkStuckChildSessions:', code.includes('Promise.all'))"

# Verify maxNudges before nudgeInProgress
node -e "const fs = require('fs'); const code = fs.readFileSync('/home/fernando/.config/opencode/plugins/continuation.ts', 'utf8'); const maxNudgesPos = code.indexOf('getNudgeCount(sessionID) >= CONFIG.maxNudges'); const nudgeInProgressPos = code.indexOf('nudgeInProgress.has(sessionID)', code.indexOf('handleChildSession')); console.log('maxNudges check position:', maxNudgesPos); console.log('nudgeInProgress check position:', nudgeInProgressPos); console.log('Correct order:', maxNudgesPos < nudgeInProgressPos)"
```

### Final Checklist
- [x] All "Must Have" present
- [x] All "Must NOT Have" absent
- [x] Parent continuation behavior unchanged
- [x] Memory leaks fixed
- [x] N+1 query parallelized
- [x] Nudge check ordering corrected
- [x] Abort errors logged
- [x] Type safety improved
- [x] nudgeCounts cleanup on completion