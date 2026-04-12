# Continuation Plugin — Subagent Stuck Detection & Recovery

## TL;DR

> **Extend `continuation.ts`** to detect and recover stuck subagents. Two mechanisms: (1) **idle-based nudge** when a child session goes idle without the end marker, and (2) **periodic watcher** that nudges busy child sessions stuck for >3 minutes. Same rate limiter covers both continuations and nudges. All configurable via `CONFIG`.

> **Deliverables**:
> - Modified `continuation.ts` supporting subagent nudge + timeout watcher
> - Validation that `session.prompt()` and `session.idle` events work on child sessions

> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 2 waves + final verification
> **Critical Path**: Task 1 (validation) → Tasks 2-4 (parallel implementation) → Task 5 (integration) → Final verification

---

## Context

### Original Request
El plugin continuation.ts solo aplica al agente padre. Si se lanzan subagentes, el plugin no salta. Dos problemas: (1) subagente pregunta al usuario (imposible sin consola) → timeout → trabajo perdido, (2) subagente entra en loop infinito → nunca completa.

### Interview Summary
**Key Discussions**:
- Subagentes que preguntan al usuario: detectable porque el subagente termina su turno (`finish='stop'`) sin marcador ■, pero la sesión va a `idle`. Solo hay que quitar el filtro `parentID` y enviar un nudge.
- Subagentes en loop infinito: nunca van a `idle`, siempre `busy`. Necesita mecanismo proactivo (periodic watcher).
- Timeout de nudge: 3 minutos (antes del hard timeout de 5 min del sistema).
- Rate limit compartido entre continuaciones y nudges (3/60s por sesión).
- Todo en continuation.ts (un solo archivo, ~180→~300 líneas).
- Mensajes en inglés.

**Research Findings**:
- Línea 104 de continuation.ts: `if (sessionResult.data?.parentID) return` — filtro explícito que salta subagentes.
- SDK Events: `session.idle`, `session.error`, `session.status` (busy/idle/retry), `session.created`, `session.updated`.
- `session.children()` API retorna sesiones hijas directas.
- `session.prompt()` funciona para enviar mensajes a cualquier sesión.
- `SessionStatus`: `{type: 'idle'} | {type: 'retry', attempt, message, next} | {type: 'busy'}`
- Plugin Hooks disponibles: `event`, `chat.message`, `tool.execute.before`, `tool.execute.after`, etc.

### Metis Review
**Identified Gaps** (addressed):
- **Event propagation**: Child `session.idle` events may not reach the plugin's event handler. → Task 1 validates this. If it doesn't work, fallback to periodic-only approach.
- **`session.prompt()` on children**: SDK may not support prompting child sessions. → Task 1 validates this.
- **Race conditions**: idle handler + watcher could fire simultaneously. → Mitigated with `nudgeInProgress` Set.
- **Orphaned children**: Parent completes while child still busy. → Abort immediately (work is obsolete).
- **Plugin cleanup**: No explicit `unload` hook in plugin interface. → Watcher persists until process restart (documented limitation).
- **Nested subagents**: `session.children()` only returns direct children, not grandchildren. → Documented as v1 limitation.

---

## Work Objectives

### Core Objective
Make the continuation plugin work for subagent sessions, not just parent sessions, by adding idle-based nudges and a periodic watcher for stuck detection.

### Concrete Deliverables
- Modified `/home/fernando/.config/opencode/plugins/continuation.ts` with all new functionality
- Validation script confirming `session.prompt()` and `session.idle` work on child sessions

### Definition of Done
- [ ] Subagent that goes idle without ■ receives a nudge message
- [ ] Subagent busy for >3 minutes receives a timeout nudge
- [ ] Parent sessions continue receiving continuation prompts exactly as before
- [ ] Rate limit shared between continuations and nudges (3/60s per session)
- [ ] Concurrent nudge prevention (nudgeInProgress Set)
- [ ] All nudges logged with sessionID, type, timestamp
- [ ] All `session.prompt` calls wrapped in try-catch
- [ ] Max 3 nudges per session before escalation

### Must Have
- Remove `parentID` filter — process ALL sessions
- Subagent idle nudge with specific message in English
- Periodic watcher (60s interval) for busy child sessions >3 min
- Shared rate limiting (continuations + nudges)
- `nudgeInProgress` Set for concurrency prevention
- `maxNudges` tracking per session (escalation after 3)
- Configurable CONFIG (messages, timeouts, intervals)
- Comprehensive logging

### Must NOT Have (Guardrails)
- MUST NOT modify existing cut-off detection logic (lines 126-150)
- MUST NOT change existing rate limit defaults (3/60s)
- MUST NOT send nudges to sessions with end marker ■
- MUST NOT send nudges to parent sessions (only children with `parentID`)
- MUST NOT persist rate limit state to disk (in-memory only)
- MUST NOT add external dependencies (no new imports beyond SDK)
- MUST NOT nudge sessions busy < `timeoutThresholdMs`
- MUST NOT send more than `maxNudges` nudges to same session
- MUST NOT include per-agent-type custom messages (single generic message for v1)

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: NO — OpenCode plugins don't have a test harness
- **Automated tests**: NO — No framework available for plugin testing
- **Framework**: none
- **Agent-Executed QA**: ALWAYS (mandatory for all tasks)

### QA Policy
Every task includes agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Plugin logic**: Use Bash (node/bun REPL) — Import plugin, call functions, verify behavior
- **Event handling**: Use Bash — Simulate events, verify logging output
- **Integration**: Manual verification with actual subagent sessions

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Validation — blocks everything):
└── Task 1: Validate SDK capabilities on child sessions [deep]

Wave 2 (After Wave 1 — core implementation, MAX PARALLEL):
├── Task 2: Extend CONFIG + tracking infrastructure [quick]
├── Task 3: Idle-based nudge for subagents [unspecified-high]
└── Task 4: Periodic watcher for stuck detection [unspecified-high]

Wave 3 (After Wave 2 — integration):
└── Task 5: Wire everything together + final integration [deep]

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
| 1 | — | 2, 3, 4 |
| 2 | 1 | 5 |
| 3 | 1, 2 | 5 |
| 4 | 1, 2 | 5 |
| 5 | 2, 3, 4 | F1-F4 |

### Agent Dispatch Summary

- **Wave 1**: 1 agent — T1 → `deep`
- **Wave 2**: 3 agents — T2 → `quick`, T3 → `unspecified-high`, T4 → `unspecified-high`
- **Wave 3**: 1 agent — T5 → `deep`
- **FINAL**: 4 agents — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [ ] 1. Validate SDK capabilities on child sessions

  **What to do**:
  - Create a test script that validates 3 critical SDK operations on child sessions:
    1. **Can parent prompt child?** Create a child session via `client.session.create({ body: { parentID } })`, send a prompt via `client.session.prompt()` on the child, verify it executes.
    2. **Do child idle events reach the plugin?** Subscribe to `session.idle` events on a child session, trigger idle, verify the event handler fires with the child's `sessionID`.
    3. **Does `session.status` return child session status?** Call `client.session.status()` and verify child sessions appear with their `busy`/`idle` status.
  - Also validate: `client.session.get({ path: { id: childID } })` returns `parentID` field on child sessions.
  - Also validate: `client.session.messages({ path: { id: childID } })` returns messages for child sessions.
  - If any validation fails, document the limitation and adjust Tasks 3-5 accordingly.
  - Save validation results to `.sisyphus/evidence/task-1-validation.md`.

  **Must NOT do**:
  - Do NOT modify continuation.ts yet
  - Do NOT create a permanent test suite — just a one-off validation script

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Requires understanding of SDK APIs and careful validation of multiple scenarios
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - None relevant for this task

  **Parallelization**:
  - **Can Run In Parallel**: NO — blocks all other tasks
  - **Parallel Group**: Wave 1 (sequential)
  - **Blocks**: Tasks 2, 3, 4, 5
  - **Blocked By**: None

  **References**:

  **Pattern References**:
  - `/home/fernando/.config/opencode/plugins/continuation.ts:82-104` — Current event handler that subscribes to `session.idle` events and uses `client.session.get()`, `client.session.messages()`, `client.session.prompt()`
  - `/home/fernando/.config/opencode/plugins/continuation.ts:34-54` — Plugin initialization pattern showing `client` API access and logging setup

  **API/Type References**:
  - `/home/fernando/.config/opencode/node_modules/@opencode-ai/sdk/dist/gen/types.gen.d.ts:413-418` — `EventSessionIdle` type definition: `{type: "session.idle", properties: {sessionID: string}}`
  - `/home/fernando/.config/opencode/node_modules/@opencode-ai/sdk/dist/gen/types.gen.d.ts:396-405` — `SessionStatus` type: `{type: 'idle'} | {type: 'retry', attempt, message, next} | {type: 'busy'}`
  - `/home/fernando/.config/opencode/node_modules/@opencode-ai/sdk/dist/gen/types.gen.d.ts:465-492` — `Session` type with `parentID` field
  - `/home/fernando/.config/opencode/node_modules/@opencode-ai/sdk/dist/gen/types.gen.d.ts:2241-2266` — `SessionPromptData` showing `session.prompt()` API

  **WHY Each Reference Matters**:
  - continuation.ts event handler: This is the pattern to replicate for validating child session events
  - SessionPromptData: Confirms the `session.prompt()` API shape for sending messages to child sessions
  - SessionStatus: Confirms the status values we'll check in the periodic watcher

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: SDK validation - child session prompting
    Tool: Bash (bun/node REPL)
    Preconditions: OpenCode server running, valid session exists
    Steps:
      1. Create a child session via SDK: `const child = await client.session.create({ body: { parentID: parentSessionID } })`
      2. Send prompt to child: `await client.session.prompt({ path: { id: child.data.id }, body: { parts: [{ type: "text", text: "echo hello" }] } })`
      3. Verify response: `child.data.id` exists and prompt was accepted (no error thrown)
    Expected Result: Child session created and receives prompt without error
    Failure Indicators: Error thrown on create or prompt, null response
    Evidence: .sisyphus/evidence/task-1-sdk-child-prompt.md

  Scenario: SDK validation - child idle event propagation
    Tool: Bash (bun/node REPL)
    Preconditions: Plugin event handler registered, child session created
    Steps:
      1. Register event handler: `client.event.subscribe(event => { if (event.type === 'session.idle') log(event) })`
      2. Trigger child session to go idle (send prompt, wait for completion)
      3. Check if child sessionID appears in idle events
    Expected Result: Child session's `session.idle` event received with child's sessionID
    Failure Indicators: No idle event for child session, only parent events received
    Evidence: .sisyphus/evidence/task-1-sdk-idle-propagation.md

  Scenario: SDK validation - session status for children
    Tool: Bash (bun/node REPL)
    Preconditions: Child session exists and is busy
    Steps:
      1. Call `client.session.status()` to get all session statuses
      2. Find child session in results
      3. Verify status includes `parentID` and correct `busy`/`idle` state
    Expected Result: Child session status returned with `type: 'busy'` while processing, `type: 'idle'` when done
    Failure Indicators: Child session not in status results, status always 'idle' regardless of activity
    Evidence: .sisyphus/evidence/task-1-sdk-session-status.md
  ```

  **Evidence to Capture**:
  - [ ] task-1-validation.md — Summary of all validation results
  - [ ] task-1-sdk-child-prompt.md — Child session prompt test results
  - [ ] task-1-sdk-idle-propagation.md — Idle event propagation test results
  - [ ] task-1-sdk-session-status.md — Session status API test results

  **Commit**: NO (validation only, no code changes)

- [ ] 2. Extend CONFIG + tracking infrastructure

  **What to do**:
  - Add new CONFIG fields to `continuation.ts`:
    ```typescript
    const CONFIG = {
      // ... existing fields ...
      
      // Subagent nudge message (sent when child session goes idle without ■ marker)
      nudgeMessage:
        "You are a subagent without an interactive console. " +
        "You cannot receive input from a human. If your last action was " +
        "asking a question, make a reasonable assumption and continue. " +
        "Do not wait for human input. If you are stuck, try a different " +
        "approach or finish with the best information you have.",
      
      // Timeout threshold: how long a child session can be 'busy' before nudging (3 min)
      timeoutThresholdMs: 180_000,
      
      // Watcher interval: how often to check for stuck child sessions (60s)
      watcherIntervalMs: 60_000,
      
      // Maximum nudges per session before escalation
      maxNudges: 3,
      
      // Whether to abort child sessions after max nudges (true) or just stop nudging (false)
      abortAfterMaxNudges: true,
    }
    ```
  - Add tracking infrastructure after `sends` Map:
    ```typescript
    // Nudge count per session: sessionID → number of nudges sent
    const nudgeCounts = new Map<string, number>()
    
    // In-flight nudge prevention: sessionIDs currently being nudged
    const nudgeInProgress = new Set<string>()
    
    // Busy start time tracking: sessionID → timestamp when first detected busy
    const busyStartTimes = new Map<string, number>()
    
    // Watcher interval handle (for cleanup)
    let watcherHandle: ReturnType<typeof setInterval> | null = null
    ```
  - Add helper functions:
    ```typescript
    function getNudgeCount(sessionID: string): number
    function incrementNudgeCount(sessionID: string): void
    function resetNudgeCount(sessionID: string): void
    ```
  - Rename `recentCount` → `recentPromptCount` for clarity (it now covers both continuations and nudges)

  **Must NOT do**:
  - Do NOT modify existing cut-off detection logic (lines 126-150)
  - Do NOT change existing rate limit behavior
  - Do NOT add any external dependencies

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Straightforward config additions and tracking Map declarations, no complex logic
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - None relevant

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 3 and 4 conceptually, but they depend on this code)
  - **Parallel Group**: Wave 2
  - **Blocks**: Tasks 3, 4, 5
  - **Blocked By**: Task 1

  **References**:

  **Pattern References**:
  - `/home/fernando/.config/opencode/plugins/continuation.ts:8-30` — Current CONFIG object structure and style
  - `/home/fernando/.config/opencode/plugins/continuation.ts:37-38` — `sends` Map declaration pattern to follow for new tracking Maps
  - `/home/fernando/.config/opencode/plugins/continuation.ts:59-73` — `recentCount()` function pattern to follow for new helpers

  **WHY Each Reference Matters**:
  - CONFIG object: Must match existing style (inline, camelCase, descriptive comments)
  - `sends` Map: Pattern for in-memory tracking Maps that get cleaned up over time
  - `recentCount()`: Existing rate limiter that the new `recentPromptCount` name replaces, must preserve behavior

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: CONFIG fields exist and have correct defaults
    Tool: Bash (node)
    Preconditions: continuation.ts saved
    Steps:
      1. Run: `node -e "const fs = require('fs'); const code = fs.readFileSync('/home/fernando/.config/opencode/plugins/continuation.ts', 'utf8'); const checks = { nudgeMessage: code.includes('nudgeMessage'), timeoutThresholdMs: code.includes('timeoutThresholdMs') && code.includes('180_000'), watcherIntervalMs: code.includes('watcherIntervalMs') && code.includes('60_000'), maxNudges: code.includes('maxNudges') && code.includes('3'), abortAfterMaxNudges: code.includes('abortAfterMaxNudges') }; console.log(JSON.stringify(checks, null, 2))"`
      2. Verify all fields exist and have expected default values
    Expected Result: All checks true
    Failure Indicators: Any field missing or wrong default value
    Evidence: .sisyphus/evidence/task-2-config-fields.txt

  Scenario: Tracking Maps declared
    Tool: Bash (node)
    Preconditions: continuation.ts saved
    Steps:
      1. Run: `node -e "const fs = require('fs'); const code = fs.readFileSync('/home/fernando/.config/opencode/plugins/continuation.ts', 'utf8'); const checks = { nudgeCounts: code.includes('nudgeCounts'), nudgeInProgress: code.includes('nudgeInProgress'), busyStartTimes: code.includes('busyStartTimes'), watcherHandle: code.includes('watcherHandle') }; console.log(JSON.stringify(checks, null, 2))"`
    Expected Result: All tracking structures present
    Failure Indicators: Any structure missing
    Evidence: .sisyphus/evidence/task-2-tracking-maps.txt

  Scenario: Helper functions added
    Tool: Bash (node)
    Preconditions: continuation.ts saved
    Steps:
      1. Run: `node -e "const fs = require('fs'); const code = fs.readFileSync('/home/fernando/.config/opencode/plugins/continuation.ts', 'utf8'); const checks = { getNudgeCount: code.includes('function getNudgeCount'), incrementNudgeCount: code.includes('function incrementNudgeCount'), resetNudgeCount: code.includes('function resetNudgeCount'), recentPromptCount: code.includes('recentPromptCount') }; console.log(JSON.stringify(checks, null, 2))"`
    Expected Result: All functions present, recentCount renamed to recentPromptCount
    Failure Indicators: Any function missing or old name still present
    Evidence: .sisyphus/evidence/task-2-helpers.txt
  ```

  **Evidence to Capture**:
  - [ ] task-2-config-fields.txt
  - [ ] task-2-tracking-maps.txt
  - [ ] task-2-helpers.txt

  **Commit**: YES (groups with Tasks 3, 4, 5)
  - Message: `feat(continuation): add subagent nudge and timeout watcher`
  - Files: `/home/fernando/.config/opencode/plugins/continuation.ts`

- [ ] 3. Idle-based nudge for subagents

  **What to do**:
  - **Remove** the `parentID` early return at line 104: `if (sessionResult.data?.parentID) return`
  - **Replace** with conditional routing:
    ```typescript
    const isChildSession = !!sessionResult.data?.parentID
    
    // For child sessions: send nudge (subagent stuck/requires input)
    // For parent sessions: send continuation (existing behavior)
    if (isChildSession) {
      // Subagent idle nudge logic
    } else {
      // Existing continuation logic (unchanged)
    }
    ```
  - **Implement idle nudge** for child sessions:
    ```typescript
    // Check if this child session already received max nudges
    if (getNudgeCount(sessionID) >= CONFIG.maxNudges) {
      // Escalation: abort or log
      if (CONFIG.abortAfterMaxNudges) {
        await client.session.abort({ path: { id: sessionID } }).catch(() => {})
        await log("warn", `Max nudges reached, aborting child session`, { sessionID, nudgeCount: getNudgeCount(sessionID) })
      }
      return
    }
    
    // Check if already being nudged (concurrency prevention)
    if (nudgeInProgress.has(sessionID)) {
      return
    }
    
    // Check if child has end marker (already completed normally)
    if (finish === "stop") {
      const textParts = last.parts.filter((p) => p.type === "text")
      if (textParts.length > 0) {
        const lastTextPart = textParts[textParts.length - 1]
        if (lastTextPart.text.trim().endsWith(CONFIG.endMarker)) {
          return // completed normally, no nudge needed
        }
      }
    }
    
    // Send nudge
    nudgeInProgress.add(sessionID)
    try {
      recordSend(sessionID)
      incrementNudgeCount(sessionID)
      await log("info", `Subagent nudge sent`, { sessionID, nudgeCount: getNudgeCount(sessionID), type: "idle" })
      await client.session.prompt({
        path: { id: sessionID },
        body: { parts: [{ type: "text", text: CONFIG.nudgeMessage }] },
      })
    } catch (err) {
      await log("error", `Subagent nudge failed: ${(err as Error).message}`, { sessionID })
    } finally {
      nudgeInProgress.delete(sessionID)
    }
    ```
  - Extract existing continuation logic into `handleParentSession()` function (no behavior change)
  - Create `handleChildSession()` function with the idle nudge logic above

  **Must NOT do**:
  - Do NOT change the continuation message for parent sessions
  - Do NOT change the end marker detection logic
  - Do NOT change rate limit behavior for parent sessions
  - Do NOT send nudges to sessions with ■ marker

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Requires careful code restructuring while preserving existing behavior
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - None relevant

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 4)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 5
  - **Blocked By**: Tasks 1, 2

  **References**:

  **Pattern References**:
  - `/home/fernando/.config/opencode/plugins/continuation.ts:82-181` — Existing event handler structure that needs conditional routing added
  - `/home/fernando/.config/opencode/plugins/continuation.ts:103-104` — The `parentID` filter to remove/replace
  - `/home/fernando/.config/opencode/plugins/continuation.ts:126-150` — Cut-off detection logic to preserve exactly as-is
  - `/home/fernando/.config/opencode/plugins/continuation.ts:152-174` — Existing continuation prompt sending to replicate for nudge

  **API/Type References**:
  - `/home/fernando/.config/opencode/node_modules/@opencode-ai/sdk/dist/gen/types.gen.d.ts:2241-2266` — `SessionPromptData` for `session.prompt()` call
  - `/home/fernando/.config/opencode/node_modules/@opencode-ai/sdk/dist/gen/types.gen.d.ts:98-127` — `AssistantMessage` with `finish` field for cut-off detection

  **WHY Each Reference Matters**:
  - Lines 103-104: This is THE line to remove — the core change that enables subagent processing
  - Lines 126-150: Must be preserved exactly; both parent and child handlers need similar (but not identical) logic
  - Lines 152-174: Pattern for sending prompts with error handling — replicate for nudge

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Child session idle without end marker receives nudge
    Tool: Bash (node)
    Preconditions: continuation.ts with nudge logic, mock session with parentID
    Steps:
      1. Search continuation.ts for `handleChildSession` function
      2. Verify function exists and contains `CONFIG.nudgeMessage`
      3. Verify function contains `nudgeInProgress` Set check
      4. Verify function contains `getNudgeCount` check against `CONFIG.maxNudges`
      5. Verify function calls `client.session.prompt` with nudge message
    Expected Result: All checks pass — child session handler sends nudge with proper guards
    Failure Indicators: Missing function, missing guard checks, wrong message
    Evidence: .sisyphus/evidence/task-3-child-nudge.txt

  Scenario: Child session idle WITH end marker does NOT receive nudge
    Tool: Bash (node)
    Preconditions: continuation.ts with nudge logic
    Steps:
      1. Verify `handleChildSession` checks for end marker (■) same as parent handler
      2. Verify early return when marker found
    Expected Result: Sessions with ■ marker are skipped (no nudge sent)
    Failure Indicators: No end marker check in child handler
    Evidence: .sisyphus/evidence/task-3-marker-skip.txt

  Scenario: Max nudge count triggers escalation
    Tool: Bash (node)
    Preconditions: continuation.ts with nudge logic
    Steps:
      1. Verify `getNudgeCount(sessionID) >= CONFIG.maxNudges` check exists
      2. Verify `client.session.abort` is called when `CONFIG.abortAfterMaxNudges` is true
      3. Verify appropriate logging for escalation
    Expected Result: After 3 nudges, child session is aborted and logged
    Failure Indicators: No escalation logic, no abort call
    Evidence: .sisyphus/evidence/task-3-escalation.txt

  Scenario: Parent session behavior unchanged
    Tool: Bash (node)
    Preconditions: continuation.ts with restructured logic
    Steps:
      1. Search continuation.ts for `handleParentSession` function
      2. Verify it contains the original continuation logic
      3. Verify `CONFIG.message` is used (not `CONFIG.nudgeMessage`)
      4. Verify end marker detection is identical to original
    Expected Result: Parent session handler identical in behavior to original code
    Failure Indicators: Different message, different logic, missing checks
    Evidence: .sisyphus/evidence/task-3-parent-unchanged.txt
  ```

  **Evidence to Capture**:
  - [ ] task-3-child-nudge.txt
  - [ ] task-3-marker-skip.txt
  - [ ] task-3-escalation.txt
  - [ ] task-3-parent-unchanged.txt

  **Commit**: YES (groups with Tasks 2, 4, 5)
  - Message: `feat(continuation): add subagent nudge and timeout watcher`
  - Files: `/home/fernando/.config/opencode/plugins/continuation.ts`

- [ ] 4. Periodic watcher for stuck detection

  **What to do**:
  - Implement a periodic watcher using `setInterval` that checks all child sessions for stuck states:
    ```typescript
    // Inside plugin initialization, after event handler setup
    watcherHandle = setInterval(async () => {
      try {
        await checkStuckChildSessions()
      } catch (err) {
        await log("error", `Watcher error: ${(err as Error).message}`)
      }
    }, CONFIG.watcherIntervalMs)
    ```
  - Implement `checkStuckChildSessions()`:
    ```typescript
    async function checkStuckChildSessions(): Promise<void> {
      // 1. Get status of ALL sessions
      const statusResult = await client.session.status({})
      if (!statusResult.data) return
      
      // 2. For each session that's busy:
      for (const [sessionID, status] of Object.entries(statusResult.data)) {
        if (status.type !== "busy") {
          // Not busy → clean up any tracking
          busyStartTimes.delete(sessionID)
          continue
        }
        
        // 3. Check if this is a child session
        const sessionResult = await client.session.get({ path: { id: sessionID } })
        if (!sessionResult.data?.parentID) continue // Skip parent sessions
        
        // 4. Track busy start time
        const now = Date.now()
        const startTime = busyStartTimes.get(sessionID) ?? now
        if (!busyStartTimes.has(sessionID)) {
          busyStartTimes.set(sessionID, startTime)
        }
        
        // 5. Check if busy for longer than threshold
        const busyDuration = now - startTime
        if (busyDuration < CONFIG.timeoutThresholdMs) continue
        
        // 6. Rate limit check
        const promptCount = recentPromptCount(sessionID)
        if (promptCount >= CONFIG.rateLimit.max) continue
        
        // 7. Max nudge check
        if (getNudgeCount(sessionID) >= CONFIG.maxNudges) {
          if (CONFIG.abortAfterMaxNudges) {
            await client.session.abort({ path: { id: sessionID } }).catch(() => {})
            await log("warn", `Max nudges reached (watcher), aborting`, { sessionID, busyDuration })
          }
          continue
        }
        
        // 8. Concurrency check
        if (nudgeInProgress.has(sessionID)) continue
        
        // 9. Send timeout nudge
        nudgeInProgress.add(sessionID)
        try {
          recordSend(sessionID)
          incrementNudgeCount(sessionID)
          await log("info", `Timeout nudge sent (watcher)`, { sessionID, busyDuration, nudgeCount: getNudgeCount(sessionID) })
          await client.session.prompt({
            path: { id: sessionID },
            body: { parts: [{ type: "text", text: CONFIG.nudgeMessage }] },
          })
        } catch (err) {
          await log("error", `Timeout nudge failed: ${(err as Error).message}`, { sessionID })
        } finally {
          nudgeInProgress.delete(sessionID)
        }
      }
    }
    ```
  - Add cleanup for the watcher interval. The plugin interface (`Hooks`) doesn't have an explicit `unload` hook, so document this limitation in a comment. The watcher will persist until the process restarts.
  - Clean up `busyStartTimes` entries for sessions that are no longer busy (prevent memory leak).

  **Must NOT do**:
  - Do NOT implement disk persistence for tracking state
  - Do NOT query `session.children()` — use `session.status()` + filter by `parentID` instead (simpler, works for all sessions at once)
  - Do NOT add external dependencies for scheduling (use native `setInterval`)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Requires careful async logic with error handling, memory management, and race condition prevention
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - None relevant

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 3)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 5
  - **Blocked By**: Tasks 1, 2

  **References**:

  **Pattern References**:
  - `/home/fernando/.config/opencode/plugins/continuation.ts:34-54` — Plugin initialization pattern showing `client` access and `log` function
  - `/home/fernando/.config/opencode/plugins/continuation.ts:82-181` — Existing event handler structure showing logging, error handling, and API call patterns

  **API/Type References**:
  - `/home/fernando/.config/opencode/node_modules/@opencode-ai/sdk/dist/gen/types.gen.d.ts:396-405` — `SessionStatus` type: `{type: 'idle'} | {type: 'retry', ...} | {type: 'busy'}` — the values we check in the watcher
  - `/home/fernando/.config/opencode/node_modules/@opencode-ai/sdk/dist/gen/types.gen.d.ts:465-492` — `Session` type with `parentID` field for child detection
  - `/home/fernando/.config/opencode/node_modules/@opencode-ai/plugin/dist/index.d.ts:142-267` — `Hooks` interface showing available hooks — no `unload` hook available

  **WHY Each Reference Matters**:
  - SessionStatus: The core type we check (`busy`) in the watcher
  - `parentID` field: How we distinguish child from parent sessions
  - Hooks interface: Confirms there's no unload hook — must document this limitation

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Watcher interval set up on plugin load
    Tool: Bash (node)
    Preconditions: continuation.ts with watcher logic
    Steps:
      1. Verify `setInterval` call exists in plugin initialization
      2. Verify interval is `CONFIG.watcherIntervalMs`
      3. Verify result is stored in `watcherHandle` variable
    Expected Result: Watcher starts on plugin load with correct interval
    Failure Indicators: No setInterval, wrong interval, handle not stored
    Evidence: .sisyphus/evidence/task-4-watcher-setup.txt

  Scenario: Busy child session detected and nudged after threshold
    Tool: Bash (node)
    Preconditions: continuation.ts with watcher logic
    Steps:
      1. Verify `checkStuckChildSessions` function exists
      2. Verify it queries `client.session.status()`
      3. Verify it filters for `status.type === "busy"`
      4. Verify it checks `parentID` to identify child sessions
      5. Verify it checks `busyDuration >= CONFIG.timeoutThresholdMs`
      6. Verify it sends nudge via `client.session.prompt` with `CONFIG.nudgeMessage`
    Expected Result: All steps present and correct in the function
    Failure Indicators: Missing status query, missing busy check, missing timeout check, wrong message
    Evidence: .sisyphus/evidence/task-4-busy-detection.txt

  Scenario: Memory leak prevention — idle sessions cleaned from tracking
    Tool: Bash (node)
    Preconditions: continuation.ts with watcher logic
    Steps:
      1. Verify `busyStartTimes.delete(sessionID)` is called for non-busy sessions
      2. Verify entries are cleaned up in the watcher loop
    Expected Result: Non-busy sessions removed from tracking maps
    Failure Indicators: No cleanup, Maps grow unbounded
    Evidence: .sisyphus/evidence/task-4-memory-cleanup.txt

  Scenario: Concurrency prevention — nudgeInProgress checked in watcher
    Tool: Bash (node)
    Preconditions: continuation.ts with watcher logic
    Steps:
      1. Verify `nudgeInProgress.has(sessionID)` check exists before sending nudge
      2. Verify `nudgeInProgress.add(sessionID)` before prompt
      3. Verify `nudgeInProgress.delete(sessionID)` in finally block
    Expected Result: No duplicate nudges from concurrent handler+watcher execution
    Failure Indicators: Missing concurrency guard
    Evidence: .sisyphus/evidence/task-4-concurrency.txt
  ```

  **Evidence to Capture**:
  - [ ] task-4-watcher-setup.txt
  - [ ] task-4-busy-detection.txt
  - [ ] task-4-memory-cleanup.txt
  - [ ] task-4-concurrency.txt

  **Commit**: YES (groups with Tasks 2, 3, 5)
  - Message: `feat(continuation): add subagent nudge and timeout watcher`
  - Files: `/home/fernando/.config/opencode/plugins/continuation.ts`

- [ ] 5. Final integration and testing

  **What to do**:
  - Wire together all components from Tasks 2, 3, and 4:
    - Ensure CONFIG fields are used consistently across all functions
    - Ensure `recentPromptCount` is used in both idle handler and watcher (shared rate limiter)
    - Ensure `nudgeInProgress` Set is checked in both idle handler and watcher
    - Ensure `nudgeCounts` Map is incremented in both paths
  - Add comprehensive logging:
    - Log watcher start on plugin initialization
    - Log each watcher tick (debug level)
    - Log nudge decisions (skip reasons: rate limit, max nudges, end marker, etc.)
  - Verify the complete flow:
    1. Plugin loads → watcher starts
    2. `session.idle` event → routed to parent or child handler
    3. Parent: existing continuation logic (unchanged)
    4. Child: nudge with `CONFIG.nudgeMessage`
    5. Watcher: periodic check → nudge stuck children
    6. Escalation: max nudges reached → abort
  - Add JSDoc comments to all new functions explaining purpose and parameters
  - Add a comment at the top explaining the subagent support enhancement

  **Must NOT do**:
  - Do NOT change the existing continuation message for parent sessions
  - Do NOT add external dependencies
  - Do NOT create test files (no test infrastructure)

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Integration work requiring understanding of all components and careful wiring
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - None relevant

  **Parallelization**:
  - **Can Run In Parallel**: NO — depends on Tasks 2, 3, 4
  - **Parallel Group**: Wave 3 (sequential)
  - **Blocks**: F1-F4
  - **Blocked By**: Tasks 2, 3, 4

  **References**:

  **Pattern References**:
  - `/home/fernando/.config/opencode/plugins/continuation.ts` — Complete file after Tasks 2-4 modifications
  - Original `/home/fernando/.config/opencode/plugins/continuation.ts` — Pre-modification reference to verify no regression

  **WHY Each Reference Matters**:
  - Modified file: Must verify all components are wired together correctly
  - Original file: Regression baseline — parent continuation must work identically

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Complete plugin loads without errors
    Tool: Bash (node)
    Preconditions: All modifications from Tasks 2-4 complete
    Steps:
      1. Run: `node -e "const fs = require('fs'); const code = fs.readFileSync('/home/fernando/.config/opencode/plugins/continuation.ts', 'utf8'); console.log('File length:', code.length, 'bytes'); console.log('Contains CONFIG:', code.includes('nudgeMessage')); console.log('Contains handleChildSession:', code.includes('handleChildSession')); console.log('Contains handleParentSession:', code.includes('handleParentSession')); console.log('Contains checkStuckChildSessions:', code.includes('checkStuckChildSessions')); console.log('Contains setInterval:', code.includes('setInterval')); console.log('Contains clearInterval:', code.includes('clearInterval')); console.log('Contains nudgeInProgress:', code.includes('nudgeInProgress')); console.log('Contains maxNudges:', code.includes('maxNudges'))"`
    Expected Result: All keys present, file is valid TypeScript
    Failure Indicators: Any key missing, syntax error
    Evidence: .sisyphus/evidence/task-5-plugin-loads.txt

  Scenario: Parent continuation behavior preserved
    Tool: Bash (node)
    Preconditions: continuation.ts complete
    Steps:
      1. Verify `handleParentSession` function exists
      2. Verify it uses `CONFIG.message` (NOT `CONFIG.nudgeMessage`)
      3. Verify it uses `CONFIG.endMarker` for cut-off detection
      4. Verify it uses `recentPromptCount` for rate limiting
      5. Verify it does NOT check `parentID` inside (routing happens before)
    Expected Result: Parent handler identical in behavior to original continuation logic
    Failure Indicators: Wrong config field used, missing checks, parentID check inside handler
    Evidence: .sisyphus/evidence/task-5-parent-preserved.txt

  Scenario: Child nudge flow end-to-end
    Tool: Bash (node)
    Preconditions: continuation.ts complete
    Steps:
      1. Read the event handler function
      2. Verify it routes to `handleChildSession` when `parentID` exists
      3. Read `handleChildSession`
      4. Verify: end marker check → skip if ■ present
      5. Verify: nudgeInProgress check → skip if already nudging
      6. Verify: max nudges check → escalate if >= 3
      7. Verify: rate limit check → skip if >= 3 in 60s
      8. Verify: send nudge with `CONFIG.nudgeMessage`
      9. Verify: increment nudge count, record send timestamp
    Expected Result: Complete nudge flow with all guards
    Failure Indicators: Missing guard, wrong message, missing tracking
    Evidence: .sisyphus/evidence/task-5-child-flow.txt

  Scenario: Watcher flow end-to-end
    Tool: Bash (node)
    Preconditions: continuation.ts complete
    Steps:
      1. Verify `setInterval` initialized with `CONFIG.watcherIntervalMs`
      2. Read `checkStuckChildSessions`
      3. Verify: query `client.session.status()`
      4. Verify: filter for `status.type === "busy"`
      5. Verify: check `parentID` (child sessions only)
      6. Verify: check `busyDuration >= CONFIG.timeoutThresholdMs`
      7. Verify: rate limit check → skip if >= 3 in 60s
      8. Verify: max nudges check → escalate if >= 3
      9. Verify: nudgeInProgress check → skip if already nudging
      10. Verify: send nudge with `CONFIG.nudgeMessage`
    Expected Result: Complete watcher flow with all guards
    Failure Indicators: Missing guard, wrong threshold, missing parentID check
    Evidence: .sisyphus/evidence/task-5-watcher-flow.txt

  Scenario: No old parentID filter remains
    Tool: Bash (node)
    Preconditions: continuation.ts complete
    Steps:
      1. Search for the old pattern: `if (sessionResult.data?.parentID) return`
      2. Verify it does NOT exist in the file
    Expected Result: The early-return filter is gone, replaced by conditional routing
    Failure Indicators: Old filter still present
    Evidence: .sisyphus/evidence/task-5-no-old-filter.txt
  ```

  **Evidence to Capture**:
  - [ ] task-5-plugin-loads.txt
  - [ ] task-5-parent-preserved.txt
  - [ ] task-5-child-flow.txt
  - [ ] task-5-watcher-flow.txt
  - [ ] task-5-no-old-filter.txt

  **Commit**: YES (final commit for all changes)
  - Message: `feat(continuation): add subagent nudge and timeout watcher`
  - Files: `/home/fernando/.config/opencode/plugins/continuation.ts`
  - Pre-commit: `node -e "const fs = require('fs'); const code = fs.readFileSync('/home/fernando/.config/opencode/plugins/continuation.ts', 'utf8'); console.log('Syntax check passed — file length:', code.length)"`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks) (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run `tsc --noEmit` + linter on continuation.ts. Review for: `as any`/`@ts-ignore`, empty catches, console.log in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names.
  Output: `Build [PASS/FAIL] | Lint [PASS/FAIL] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
  Start from clean state. Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test cross-task integration. Test edge cases: idle subagent without marker, busy subagent >3 min, rate limit exceeded, concurrent nudges. Save to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff. Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Detect cross-task contamination.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **1**: `feat(continuation): add subagent nudge and timeout watcher` — continuation.ts
  - No pre-commit test command (no test infrastructure)

---

## Success Criteria

### Verification Commands
```bash
# Verify plugin loads without errors
node -e "const {ContinuationPlugin} = require('./continuation'); console.log('Plugin loads OK')"

# Verify CONFIG has new fields
node -e "const fs = require('fs'); const code = fs.readFileSync('continuation.ts', 'utf8'); const hasNudgeMsg = code.includes('nudgeMessage'); const hasTimeout = code.includes('timeoutThresholdMs'); const hasWatcher = code.includes('watcherIntervalMs'); const hasMaxNudges = code.includes('maxNudges'); console.log('CONFIG fields:', {hasNudgeMsg, hasTimeout, hasWatcher, hasMaxNudges})"

# Verify parentID filter removed
node -e "const fs = require('fs'); const code = fs.readFileSync('continuation.ts', 'utf8'); const hasOldFilter = code.includes('if (sessionResult.data?.parentID) return'); console.log('Old parentID filter removed:', !hasOldFilter)"

# Verify watcher cleanup
node -e "const fs = require('fs'); const code = fs.readFileSync('continuation.ts', 'utf8'); const hasInterval = code.includes('setInterval'); const hasClear = code.includes('clearInterval'); console.log('Watcher setup/cleanup:', {hasInterval, hasClear})"
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] Parent continuation behavior unchanged
- [ ] Subagent idle nudge works
- [ ] Periodic watcher nudges stuck subagents
- [ ] Rate limiting shared correctly
- [ ] Concurrent nudge prevention in place
- [ ] Max nudges escalation implemented