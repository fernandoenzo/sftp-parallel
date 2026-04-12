# SFTP Parallel Upload Script — Review & Fix Plan

## TL;DR

> **Quick Summary**: Review and fix `/tmp/sftp-parallel-upload.sh` addressing 12 issues identified by Metis. Fixes go into a NEW file `/tmp/sftp-parallel-upload-fixed.sh`, then diff against original. Essential fixes (quoting, validation, auth check, timeout) are prioritized over nice-to-haves (progress reporting, as-complete wait).
> 
> **Deliverables**:
> - Fixed script at `/tmp/sftp-parallel-upload-fixed.sh`
> - Diff file at `/tmp/sftp-parallel-upload-fixed.sh.patch`
> - Evidence of each fix working
> 
> **Estimated Effort**: Medium
> **Parallel Execution**: YES — 4 waves
> **Critical Path**: Task 1 → Task 4 → Task 6 → Task 7 → F1-F4

---

## Context

### Original Request
Review and fix a bash script (`/tmp/sftp-parallel-upload.sh`) that performs parallel SFTP uploads using `put -f` (fsync). Fixes should go in a new file, then diff against original.

### Metis Review — 12 Issues Found

**Tier 1 — ESSENTIAL (will cause real failures):**
1. **Line 83**: `cd $REMOTE_DIR` unquoted — breaks with spaces/special chars in remote path
2. **Line 50**: `find -printf '%f\n'` is GNU-only — fails silently on macOS/BSD (user says Linux-only, so lower priority but still a robustness fix)
3. **No JOBS validation** — `-j 0`, `-j -1`, `-j abc` all cause undefined behavior
4. **No SSH auth pre-check** — background sftp hangs forever if password-based auth is required
5. **No REMOTE_DIR existence check** — all uploads silently fail if remote dir doesn't exist
6. **No timeout on SFTP** — hangs indefinitely on network issues (SSH `ConnectTimeout` + `ServerAliveInterval`)

**Tier 2 — IMPORTANT (correctness under edge cases):**
7. **Filename escaping incomplete** — quotes/backslashes in filenames break the generated batch file
8. **`mapfile` requires bash 4.0+** — silent failure on older bash (user is Linux, likely fine, but should add a guard)
9. **Extra positional args silently ignored** — `$3+` silently ignored, should error

**Tier 3 — NICE-TO-HAVE (UX improvements):**
10. **No progress reporting** — user wants assurance it works first try
11. **Sequential wait** — slow session blocks reporting of fast ones
12. **`$?` after `wait`** — correct but fragile; can lose exit code if any statement runs between `wait` and `$?` capture

### User Context
- Own SFTP server — can configure sshd if needed
- Cares about `put -f` (fsync guarantee) — that's the whole point
- Wants 2-3 concurrent sessions
- Wants assurance it works first try
- Linux environment (not macOS)
- Fixes in NEW file, then diff against original

---

## Work Objectives

### Core Objective
Fix all correctness-breaking bugs, add essential safety guards, and improve the script so it works reliably first try on the user's Linux+SFTP setup.

### Concrete Deliverables
- `/tmp/sftp-parallel-upload-fixed.sh` — fixed version of the script
- `/tmp/sftp-parallel-upload-fixed.sh.patch` — diff against original
- Evidence files in `.sisyphus/evidence/`

### Definition of Done
- [ ] All Tier 1 fixes applied and verified
- [ ] All Tier 2 fixes applied and verified
- [ ] Tier 3 fixes applied where practical
- [ ] `bash -n` passes on fixed script (syntax check)
- [ ] `shellcheck` passes with no errors (warnings acceptable with justification)
- [ ] Diff file generated
- [ ] Evidence captured for each fix

### Must Have
- Quoting fix for `cd "$REMOTE_DIR"` (Line 83)
- JOBS validation (positive integer)
- SSH auth pre-check before forking
- REMOTE_DIR existence check via SFTP
- Connection timeout (`ConnectTimeout` + `ServerAliveInterval`)
- Filename escaping for quotes/backslashes in batch file
- Extra positional args rejected with error
- bash version guard for `mapfile`
- All fixes in a NEW file (not the original)

### Must NOT Have (Guardrails)
- Do NOT modify `/tmp/sftp-parallel-upload.sh` — fixes go in new file only
- Do NOT remove `put -f` — that's the core feature the user wants
- Do NOT switch to `scp` or `rsync` — user specifically wants SFTP with fsync
- Do NOT add external dependencies beyond standard Linux coreutils + openssh
- Do NOT over-engineer — this is a utility script, not a framework
- Do NOT add "AI slop" — no excessive comments, no over-abstraction, no generic error messages

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed.

### Test Decision
- **Infrastructure exists**: NO (bash script, no test framework)
- **Automated tests**: Tests-after (bash syntax check + shellcheck + manual QA scenarios)
- **Framework**: `bash -n` + `shellcheck` + functional test scenarios

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **CLI/TUI**: Use Bash — Run script with various inputs, check exit codes, output, and behavior
- **Script validation**: `bash -n`, `shellcheck`

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately — copy + foundation fixes):
├── Task 1: Copy script, add bash version guard [quick] ← START FIRST
├── Task 2: Add JOBS validation [quick] (after T1)
├── Task 3: Add extra positional args rejection [quick] (after T1)
└── Task 4: Quote all variable expansions (REMOTE_DIR, HOST, etc.) [quick] (after T1)

Wave 2 (After Wave 1 — safety & correctness):
├── Task 5: Add SSH auth pre-check [unspecified-high]
├── Task 6: Add REMOTE_DIR existence check via sftp [unspecified-high]
├── Task 7: Add connection timeout (ConnectTimeout + ServerAliveInterval) [quick]
└── Task 8: Fix filename escaping in batch file generation [deep]

Wave 3 (After Wave 2 — UX improvements):
├── Task 9: Add basic progress reporting [quick]
└── Task 10: Improve wait loop (as-complete with PID tracking) [unspecified-low]

Wave 4 (After ALL implementation — verification):
├── Task 11: Generate diff file + final validation [quick]
├── F1: Plan compliance audit [oracle]
├── F2: Code quality review (shellcheck) [unspecified-high]
├── F3: Real manual QA [unspecified-high]
└── F4: Scope fidelity check [deep]

Critical Path: Task 1 → Task 4 → Task 8 → Task 11 → F1-F4
Parallel Speedup: ~60% faster than sequential
Max Concurrent: 4 (Wave 1)
```

### Dependency Matrix

| Task | Depends On | Reason |
|------|------------|--------|
| Task 1 | None | Starting point — copy file to new location |
| Task 2 | None | Independent — JOBS validation logic |
| Task 3 | None | Independent — positional args validation |
| Task 4 | Task 1 | Needs the copied file to apply quoting fixes |
| Task 5 | Task 4 | Needs quoted HOST variable for auth check |
| Task 6 | Task 4 | Needs quoted REMOTE_DIR for existence check |
| Task 7 | Task 4 | Needs quoted HOST for sftp options |
| Task 8 | Task 4 | Needs quoted LOCAL_DIR for filename escaping |
| Task 9 | Task 8 | Needs batch file generation to be correct before adding progress |
| Task 10 | Task 6 | Needs remote dir check in place before changing wait logic |
| Task 11 | Tasks 1-10 | All fixes must be in before generating diff |
| F1-F4 | Task 11 | Final verification needs complete diff |

### Agent Dispatch Summary

- **Wave 1**: **4 tasks** — T1 `quick`, T2 `quick`, T3 `quick`, T4 `quick`
- **Wave 2**: **4 tasks** — T5 `unspecified-high`, T6 `unspecified-high`, T7 `quick`, T8 `deep`
- **Wave 3**: **2 tasks** — T9 `quick`, T10 `unspecified-low`
- **Wave 4**: **5 tasks** — T11 `quick`, F1 `oracle`, F2 `unspecified-high`, F3 `unspecified-high`, F4 `deep`

---

## TODOs

> Implementation + Test = ONE Task. Never separate.
> EVERY task MUST have: Recommended Agent Profile + Parallelization info + QA Scenarios.

- [ ] 1. Copy script to new file + add bash version guard

  **What to do**:
  - Copy `/tmp/sftp-parallel-upload.sh` to `/tmp/sftp-parallel-upload-fixed.sh`
  - Add a bash version guard near the top (after `set -euo pipefail`):
    ```bash
    if [[ ${BASH_VERSINFO[0]} -lt 4 ]]; then
        echo "Error: bash 4.0+ required (mapfile builtin)" >&2
        exit 1
    fi
    ```
  - This addresses Metis issue #8 (`mapfile` requires bash 4.0+)

  **Must NOT do**:
  - Do NOT modify the original file
  - Do NOT add excessive comments — one-line guard is sufficient

  **Recommended Agent Profile**:
  - **Category**: `quick` — Single file copy + small addition
  - **Skills**: [] — No specialized skills needed for this

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 2, 3)
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 4 (needs file to exist)
  - **Blocked By**: None

  **References**:
  - `/tmp/sftp-parallel-upload.sh` — The original script to copy
  - Line 50 uses `mapfile` which requires bash 4.0+

  **QA Scenarios**:

  ```
  Scenario: Copy succeeds and guard is present
    Tool: Bash
    Preconditions: Original script exists at /tmp/sftp-parallel-upload.sh
    Steps:
      1. test -f /tmp/sftp-parallel-upload-fixed.sh && echo "EXISTS" || echo "MISSING"
      2. grep -c 'BASH_VERSINFO' /tmp/sftp-parallel-upload-fixed.sh
      3. bash -n /tmp/sftp-parallel-upload-fixed.sh && echo "SYNTAX_OK" || echo "SYNTAX_FAIL"
    Expected Result: EXISTS, count=1 (or more), SYNTAX_OK
    Failure Indicators: File missing, no BASH_VERSINFO, syntax error
    Evidence: .sisyphus/evidence/task-1-copy-and-guard.txt
  ```

  **Commit**: YES (groups with Wave 1)
  - Message: `fix(sftp-upload): copy to new file + bash version guard`
  - Files: `/tmp/sftp-parallel-upload-fixed.sh`
  - Pre-commit: `bash -n /tmp/sftp-parallel-upload-fixed.sh`

- [ ] 2. Add JOBS validation (positive integer)

  **What to do**:
  - In the fixed script, add validation after the `getopts` loop (after line 40 `shift $((OPTIND - 1))`):
    ```bash
    if ! [[ "$JOBS" =~ ^[1-9][0-9]*$ ]]; then
        echo "Error: -j must be a positive integer, got '$JOBS'" >&2
        exit 1
    fi
    ```
  - This addresses Metis issue #3 (no JOBS validation)
  - Regex ensures: at least 1, no leading zeros, digits only, >0

  **Must NOT do**:
  - Do NOT add a maximum JOBS cap (user may want more than some arbitrary limit)
  - Do NOT change the default value of 2

  **Recommended Agent Profile**:
  - **Category**: `quick` — Small validation addition
  - **Skills**: [] — No specialized skills needed

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 3, after Task 1 creates the file)
  - **Parallel Group**: Wave 1
  - **Blocks**: None directly
  - **Blocked By**: Task 1 (file must exist first)

  **References**:
  - `/tmp/sftp-parallel-upload-fixed.sh` — The file being edited (may not exist yet if Task 1 not done — apply after Task 1 or to same copy)
  - Line 34: `j) JOBS="$OPTARG"` — Where JOBS is set
  - Line 40: `shift $((OPTIND - 1))` — Insert validation after this line

  **QA Scenarios**:

  ```
  Scenario: Valid JOBS values accepted
    Tool: Bash
    Preconditions: Fixed script exists
    Steps:
      1. bash /tmp/sftp-parallel-upload-fixed.sh -j 1 user@host /tmp 2>&1 | head -5
      2. bash /tmp/sftp-parallel-upload-fixed.sh -j 3 user@host /tmp 2>&1 | head -5
    Expected Result: No "must be a positive integer" error for either
    Failure Indicators: Validation error message for valid input
    Evidence: .sisyphus/evidence/task-2-jobs-valid.txt

  Scenario: Invalid JOBS values rejected
    Tool: Bash
    Preconditions: Fixed script exists
    Steps:
      1. bash /tmp/sftp-parallel-upload-fixed.sh -j 0 user@host /tmp 2>&1; echo "EXIT=$?"
      2. bash /tmp/sftp-parallel-upload-fixed.sh -j -1 user@host /tmp 2>&1; echo "EXIT=$?"
      3. bash /tmp/sftp-parallel-upload-fixed.sh -j abc user@host /tmp 2>&1; echo "EXIT=$?"
    Expected Result: All three print error about -j to stderr and exit non-zero
    Failure Indicators: Any of the three exits 0 or does not show error
    Evidence: .sisyphus/evidence/task-2-jobs-invalid.txt
  ```

  **Commit**: YES (groups with Wave 1)
  - Message: `fix(sftp-upload): validate -j is positive integer`
  - Files: `/tmp/sftp-parallel-upload-fixed.sh`
  - Pre-commit: `bash -n /tmp/sftp-parallel-upload-fixed.sh`

- [ ] 3. Reject extra positional arguments

  **What to do**:
  - In the fixed script, after the two required positional args are assigned, add:
    ```bash
    if [[ $# -gt 2 ]]; then
        echo "Error: unexpected argument '$3'. Usage: $(basename "$0") [-j N] [-r remote_dir] user@host local_dir" >&2
        exit 1
    fi
    ```
  - Insert after line 43 (`LOCAL_DIR=...`) and before the `[[ ! -d "$LOCAL_DIR" ]]` check
  - This addresses Metis issue #12 (extra positional args silently ignored)

  **Must NOT do**:
  - Do NOT silently ignore extra args
  - Do NOT change the existing positional arg assignments

  **Recommended Agent Profile**:
  - **Category**: `quick` — Small validation addition
  - **Skills**: [] — No specialized skills needed

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 2, after Task 1 creates the file)
  - **Parallel Group**: Wave 1
  - **Blocks**: None directly
  - **Blocked By**: Task 1 (file must exist first)

  **References**:
  - `/tmp/sftp-parallel-upload-fixed.sh` — The file being edited
  - Lines 42-43: Where HOST and LOCAL_DIR are assigned
  - Line 44: The directory check where the validation should go before

  **QA Scenarios**:

  ```
  Scenario: Extra positional arg rejected
    Tool: Bash
    Preconditions: Fixed script exists
    Steps:
      1. bash /tmp/sftp-parallel-upload-fixed.sh user@host /tmp extra_arg 2>&1; echo "EXIT=$?"
    Expected Result: Error message mentioning "unexpected argument" on stderr, exit non-zero
    Failure Indicators: No error, exit 0, or script proceeds with extra arg
    Evidence: .sisyphus/evidence/task-3-extra-args.txt
  ```

  **Commit**: YES (groups with Wave 1)
  - Message: `fix(sftp-upload): reject extra positional arguments`
  - Files: `/tmp/sftp-parallel-upload-fixed.sh`
  - Pre-commit: `bash -n /tmp/sftp-parallel-upload-fixed.sh`

- [ ] 4. Quote all variable expansions properly

  **What to do**:
  - In the fixed script, fix ALL unquoted variable expansions. Key locations:
    1. **Line 83** (the critical one): `echo "cd $REMOTE_DIR"` → `echo "cd \"$REMOTE_DIR\""`
       - The `cd` command inside the sftp batch file MUST have the remote dir quoted
       - Must escape any embedded double-quotes in REMOTE_DIR
    2. **Line 91**: `sftp -b "$BATCHFILE" "$HOST"` — already quoted ✅
    3. **Line 67**: `BUCKETS[$IDX]+="$FILE"$'\n'` — `$FILE` is in a string context but could contain spaces; needs quoting within the array assignment context (already in double quotes, OK)
    4. **Line 85**: `echo "put -f \"${LOCAL_DIR}/${FILE}\""` — LOCAL_DIR and FILE are already double-quoted inside the string, but the path joining with `/` could produce `//` if LOCAL_DIR ends with `/`. Add `${LOCAL_DIR%/}` to strip trailing slash.
    5. **Line 92**: `PIDS+=($!)` — `$!` is safe unquoted in array assignment, but quote for consistency: `PIDS+=("$!")`
  - This addresses Metis issue #1 (cd $REMOTE_DIR unquoted)

  **Must NOT do**:
  - Do NOT change the script's control flow
  - Do NOT add unnecessary quotes around obviously safe expansions (like `$((...))` arithmetic)

  **Recommended Agent Profile**:
  - **Category**: `quick` — Systematic quoting fixes
  - **Skills**: [] — Bash knowledge is standard for quick agents

  **Parallelization**:
  - **Can Run In Parallel**: NO — Edits same file as Tasks 1-3; start after Task 1 completes
  - **Parallel Group**: Wave 1 (starts same time if file exists, or immediately after Task 1)
  - **Blocks**: Tasks 5, 6, 7, 8 (they need properly quoted variables)
  - **Blocked By**: Task 1 (file must exist)

  **References**:
  - `/tmp/sftp-parallel-upload-fixed.sh` — The file being edited
  - Line 83: `echo "cd $REMOTE_DIR"` — CRITICAL: unquoted in sftp batch command
  - Line 85: `echo "put -f \"${LOCAL_DIR}/${FILE}\""` — Path joining edge case
  - Line 92: `PIDS+=($!)` — Minor consistency fix

  **QA Scenarios**:

  ```
  Scenario: Remote dir with spaces handled correctly
    Tool: Bash
    Preconditions: Fixed script exists
    Steps:
      1. grep 'cd ' /tmp/sftp-parallel-upload-fixed.sh
      2. Verify the cd line now quotes $REMOTE_DIR
    Expected Result: Line shows cd with quoted/escaped REMOTE_DIR
    Failure Indicators: Still shows unquoted cd $REMOTE_DIR
    Evidence: .sisyphus/evidence/task-4-quoting.txt

  Scenario: Shellcheck passes with no errors
    Tool: Bash
    Preconditions: shellcheck is available
    Steps:
      1. shellcheck -s bash /tmp/sftp-parallel-upload-fixed.sh 2>&1 || true
    Expected Result: No SC2086 errors (unquoted variable expansions)
    Failure Indicators: SC2086 or similar quoting warnings
    Evidence: .sisyphus/evidence/task-4-shellcheck.txt
  ```

  **Commit**: YES (groups with Wave 1)
  - Message: `fix(sftp-upload): quote all variable expansions, fix cd $REMOTE_DIR`
  - Files: `/tmp/sftp-parallel-upload-fixed.sh`
  - Pre-commit: `bash -n /tmp/sftp-parallel-upload-fixed.sh`

- [ ] 5. Add SSH auth pre-check before forking

  **What to do**:
  - Before the parallel sftp session loop (before line ~71 where TMPDIR is created), add an SSH connection test:
    ```bash
    # Pre-check: verify SSH authentication works (prevent hanging background sessions)
    if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$HOST" exit 0 2>/dev/null; then
        echo "Error: cannot authenticate to $HOST (ensure SSH key is configured for passwordless auth)" >&2
        exit 1
    fi
    ```
  - `BatchMode=yes` ensures connection fails immediately if password auth is needed
  - `ConnectTimeout=5` gives a quick fail on unreachable hosts
  - Insert BEFORE the TMPDIR creation so we fail fast without creating temp files
  - This addresses Metis issue #4 (no SSH auth pre-check)

  **Must NOT do**:
  - Do NOT add `-o PasswordAuthentication=no` — `BatchMode=yes` is the correct approach
  - Do NOT make the check take more than ~5 seconds total

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` — Needs understanding of SSH auth semantics
  - **Skills**: [] — Standard bash/SSH knowledge

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 6, 7, 8)
  - **Parallel Group**: Wave 2
  - **Blocks**: None directly
  - **Blocked By**: Task 4 (needs properly quoted $HOST)

  **References**:
  - `/tmp/sftp-parallel-upload-fixed.sh` — The file being edited
  - Line 71 of original: `TMPDIR=$(mktemp -d)` — Insert auth check BEFORE this
  - Line 42: `HOST="${1:?..."` — The HOST variable to use

  **QA Scenarios**:

  ```
  Scenario: Auth check present in script
    Tool: Bash
    Preconditions: Fixed script exists with previous fixes
    Steps:
      1. grep -c 'BatchMode=yes' /tmp/sftp-parallel-upload-fixed.sh
      2. grep -n 'BatchMode\|ConnectTimeout' /tmp/sftp-parallel-upload-fixed.sh | head -5
    Expected Result: At least 1 match for BatchMode=yes
    Failure Indicators: No BatchMode=yes found in script
    Evidence: .sisyphus/evidence/task-5-auth-check.txt

  Scenario: Auth check fails gracefully with unreachable host
    Tool: Bash
    Preconditions: Fixed script exists
    Steps:
      1. timeout 15 bash /tmp/sftp-parallel-upload-fixed.sh -j 2 nonexistent@127.0.0.1 /tmp 2>&1; echo "EXIT=$?"
    Expected Result: Error about authentication/connection, exit non-zero, finishes within 15s
    Failure Indicators: Hangs > 15 seconds, exits 0, or no error message
    Evidence: .sisyphus/evidence/task-5-auth-fail.txt
  ```

  **Commit**: YES (groups with Wave 2)
  - Message: `fix(sftp-upload): add SSH auth pre-check before forking`
  - Files: `/tmp/sftp-parallel-upload-fixed.sh`
  - Pre-commit: `bash -n /tmp/sftp-parallel-upload-fixed.sh`

- [ ] 6. Add REMOTE_DIR existence check via SSH

  **What to do**:
  - After the SSH auth pre-check (Task 5) and before the parallel session loop, add a remote directory existence check:
    ```bash
    # Pre-check: verify remote directory exists
    if ! ssh -o BatchMode=yes "$HOST" "test -d \"$REMOTE_DIR\"" 2>/dev/null; then
        echo "Error: remote directory '$REMOTE_DIR' does not exist or is not accessible" >&2
        exit 1
    fi
    ```
  - Uses SSH rather than SFTP because we already have SSH working (verified by Task 5 auth check)
  - `test -d` is portable and reliable
  - This addresses Metis issue #5 (no REMOTE_DIR existence check)

  **Must NOT do**:
  - Do NOT create the remote directory automatically (security risk)
  - Do NOT use sftp to check (error parsing is fragile)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` — Needs SSH vs SFTP distinction understanding
  - **Skills**: [] — Standard SSH knowledge

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 5, 7, 8)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 10
  - **Blocked By**: Task 4 (needs properly quoted REMOTE_DIR)

  **References**:
  - `/tmp/sftp-parallel-upload-fixed.sh` — The file being edited
  - Insert after auth check from Task 5, before TMPDIR creation
  - Line 25: `REMOTE_DIR="."` — Default value
  - Line 35: `r) REMOTE_DIR="$OPTARG"` — Where it's set

  **QA Scenarios**:

  ```
  Scenario: Remote dir check present in script
    Tool: Bash
    Preconditions: Fixed script exists with previous fixes
    Steps:
      1. grep -c 'test -d' /tmp/sftp-parallel-upload-fixed.sh
    Expected Result: At least 1 match
    Failure Indicators: No test -d found
    Evidence: .sisyphus/evidence/task-6-dir-check.txt
  ```

  **Commit**: YES (groups with Wave 2)
  - Message: `fix(sftp-upload): add remote directory existence check`
  - Files: `/tmp/sftp-parallel-upload-fixed.sh`
  - Pre-commit: `bash -n /tmp/sftp-parallel-upload-fixed.sh`

- [ ] 7. Add connection timeout to SFTP sessions

  **What to do**:
  - Add SSH connection options array near the top of the script (after the JOBS/REMOTE_DIR defaults):
    ```bash
    SFTP_OPTS=(-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=30 -o ServerAliveCountMax=3)
    ```
  - Then change the sftp invocation from:
    ```bash
    sftp -b "$BATCHFILE" "$HOST"
    ```
    to:
    ```bash
    sftp "${SFTP_OPTS[@]}" -b "$BATCHFILE" "$HOST"
    ```
  - **ConnectTimeout=10**: Fail if can't establish connection within 10s
  - **ServerAliveInterval=30 + ServerAliveCountMax=3**: Kill session if no response for 90s (30s × 3)
  - This addresses Metis issue #6 (no timeout on SFTP)

  **Must NOT do**:
  - Do NOT set ServerAliveInterval too low (would kill slow-but-valid uploads)
  - Do NOT use `-o ConnectionTimeout` (not a valid OpenSSH option)

  **Recommended Agent Profile**:
  - **Category**: `quick` — Small addition to sftp command
  - **Skills**: [] — Standard SSH knowledge

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 5, 6, 8)
  - **Parallel Group**: Wave 2
  - **Blocks**: None directly
  - **Blocked By**: Task 4 (needs properly quoted HOST)

  **References**:
  - `/tmp/sftp-parallel-upload-fixed.sh` — The file being edited
  - Line 91 of original: `sftp -b "$BATCHFILE" "$HOST"` — The invocation to modify

  **QA Scenarios**:

  ```
  Scenario: Timeout options present in script
    Tool: Bash
    Preconditions: Fixed script exists with previous fixes
    Steps:
      1. grep -c 'ConnectTimeout\|ServerAliveInterval' /tmp/sftp-parallel-upload-fixed.sh
    Expected Result: Both options found
    Failure Indicators: Any option missing
    Evidence: .sisyphus/evidence/task-7-timeout.txt

  Scenario: Syntax validation after changes
    Tool: Bash
    Preconditions: Fixed script exists
    Steps:
      1. bash -n /tmp/sftp-parallel-upload-fixed.sh && echo "OK" || echo "FAIL"
    Expected Result: OK
    Failure Indicators: Syntax error
    Evidence: .sisyphus/evidence/task-7-timeout-syntax.txt
  ```

  **Commit**: YES (groups with Wave 2)
  - Message: `fix(sftp-upload): add connection timeout and keepalive to sftp`
  - Files: `/tmp/sftp-parallel-upload-fixed.sh`
  - Pre-commit: `bash -n /tmp/sftp-parallel-upload-fixed.sh`

- [ ] 8. Fix filename escaping in batch file generation

  **What to do**:
  - The current batch file generation (lines 82-88) creates sftp commands with double-quoted paths, but breaks if filenames contain double-quotes or backslashes.
  - Fix the batch file generation block:
    ```bash
    {
        # Escape REMOTE_DIR for sftp batch syntax
        REMOTE_ESCAPED="${REMOTE_DIR//\\/\\\\}"
        REMOTE_ESCAPED="${REMOTE_ESCAPED//\"/\\\"}"
        echo "cd \"${REMOTE_ESCAPED}\""
        while IFS= read -r FILE; do
            [[ -z "$FILE" ]] && continue
            # Build full local path, then escape for sftp batch syntax
            LOCAL_PATH="${LOCAL_DIR%/}/${FILE}"
            LOCAL_ESCAPED="${LOCAL_PATH//\\/\\\\}"     # \ → \\
            LOCAL_ESCAPED="${LOCAL_ESCAPED//\"/\\\"}"  # " → \"
            echo "put -f \"${LOCAL_ESCAPED}\""
        done <<< "$BUCKET_CONTENTS"
        echo "bye"
    } > "$BATCHFILE"
    ```
  - Escaping strategy: backslashes first, then double-quotes (order matters!)
  - Also fixes path joining: uses `${LOCAL_DIR%/}/` to strip trailing slash
  - This addresses Metis issue #7 (filename escaping incomplete)

  **Must NOT do**:
  - Do NOT use `printf '%q'` — that produces bash-escaped strings, not sftp-compatible
  - Do NOT change `-b` (file-based batch) to stdin-based batch mode

  **Recommended Agent Profile**:
  - **Category**: `deep` — Tricky escaping logic with multiple edge cases
  - **Skills**: [] — Pure bash string manipulation

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 5, 6, 7)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 9 (progress reporting needs correct batch generation)
  - **Blocked By**: Task 4 (needs quoted variables as baseline)

  **References**:
  - `/tmp/sftp-parallel-upload-fixed.sh` — The file being edited
  - Lines 82-88 of original: The batch file generation block
  - SFTP batch file syntax: Double-quoted strings with backslash-escaped special chars

  **QA Scenarios**:

  ```
  Scenario: Filenames with spaces handled correctly
    Tool: Bash
    Preconditions: Fixed script exists
    Steps:
      1. mkdir -p /tmp/test-sftp-files && touch "/tmp/test-sftp-files/file with spaces.txt"
      2. Inspect generated batch file for proper quoting
    Expected Result: Batch file contains put -f with properly quoted filename
    Failure Indicators: Filename unquoted or incorrectly escaped
    Evidence: .sisyphus/evidence/task-8-escaping-spaces.txt

  Scenario: Filenames with double quotes handled
    Tool: Bash
    Preconditions: Fixed script exists
    Steps:
      1. mkdir -p /tmp/test-sftp-quotes && touch '/tmp/test-sftp-quotes/file"with"quotes.txt'
      2. Inspect generated batch file for proper escaping
    Expected Result: Double quotes in filename are backslash-escaped
    Failure Indicators: Unescaped double quotes break batch syntax
    Evidence: .sisyphus/evidence/task-8-escaping-quotes.txt

  Scenario: Filenames with backslashes handled
    Tool: Bash
    Preconditions: Fixed script exists
    Steps:
      1. mkdir -p /tmp/test-sftp-backslash && touch '/tmp/test-sftp-backslash/file\with\backslash.txt'
      2. Inspect generated batch file for proper escaping
    Expected Result: Backslashes in filename are doubled
    Failure Indicators: Unescaped backslashes
    Evidence: .sisyphus/evidence/task-8-escaping-backslashes.txt
  ```

  **Commit**: YES (groups with Wave 2)
  - Message: `fix(sftp-upload): properly escape filenames in sftp batch generation`
  - Files: `/tmp/sftp-parallel-upload-fixed.sh`
  - Pre-commit: `bash -n /tmp/sftp-parallel-upload-fixed.sh`

- [ ] 9. Add basic progress reporting

  **What to do**:
  - Add progress output to the session launch and completion:
    1. At session launch, already prints `[session N] files: ...` — keep this
    2. After each `wait`, print progress count: `✓ [2/3] Session 2 completed`
    3. Before printing the final "Done" line, add elapsed time
  - Minimal implementation — add a COMPLETED counter that increments after each wait:
    ```bash
    COMPLETED=0
    for I in "${!PIDS[@]}"; do
        PID=${PIDS[$I]}
        if ! wait "$PID"; then
            ...
        else
            COMPLETED=$((COMPLETED + 1))
            echo "✓ [$COMPLETED/${#PIDS[@]}] Session $((I + 1)) completed"
        fi
    done
    ```
  - This addresses Metis issue #9 (no progress reporting)

  **Must NOT do**:
  - Do NOT add per-file progress (sftp batch mode doesn't support it)
  - Do NOT add percentage bars or spinners
  - Do NOT use `pv` or other external tools

  **Recommended Agent Profile**:
  - **Category**: `quick` — Small output formatting addition
  - **Skills**: [] — No specialized skills needed

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 10)
  - **Parallel Group**: Wave 3
  - **Blocks**: None
  - **Blocked By**: Task 8 (needs correct batch file generation)

  **References**:
  - `/tmp/sftp-parallel-upload-fixed.sh` — The file being edited
  - Lines 97-107 of original: The wait loop that needs progress output
  - Line 114: `echo "→ Done: $TOTAL file(s) uploaded"` — Final output line

  **QA Scenarios**:

  ```
  Scenario: Progress reporting present in script
    Tool: Bash
    Preconditions: Fixed script exists with all previous fixes
    Steps:
      1. grep -c 'COMPLETED' /tmp/sftp-parallel-upload-fixed.sh
    Expected Result: At least 2 matches (declaration + increment)
    Failure Indicators: No COMPLETED counter found
    Evidence: .sisyphus/evidence/task-9-progress.txt
  ```

  **Commit**: YES (groups with Wave 3)
  - Message: `feat(sftp-upload): add basic session progress reporting`
  - Files: `/tmp/sftp-parallel-upload-fixed.sh`
  - Pre-commit: `bash -n /tmp/sftp-parallel-upload-fixed.sh`

- [ ] 10. Improve wait loop — preserve exit codes reliably

  **What to do**:
  - The current `wait` loop correctly captures exit codes but is fragile — if any statement runs between `wait` and `$?`, the exit code is lost.
  - Replace the current pattern:
    ```bash
    if ! wait "$PID"; then
        echo "✗ Session $((I + 1)) failed (exit $?):" >&2
    ```
    with:
    ```bash
    wait "$PID"
    EXIT_CODE=$?
    if [[ $EXIT_CODE -ne 0 ]]; then
        echo "✗ Session $((I + 1)) failed (exit $EXIT_CODE):" >&2
    ```
  - This addresses Metis issue #11 ($? after wait is correct but fragile) and #10 (sequential wait)
  - For the "as-complete" wait improvement (Metis issue #10): This would require significant restructuring (using `wait -n` or polling), which is complex for a utility script. The current sequential wait is acceptable for 2-3 sessions. Add a comment noting this limitation:
    ```bash
    # Note: Sessions are waited on sequentially. For many concurrent sessions,
    # consider 'wait -n' (bash 5.1+) for as-complete reporting.
    ```

  **Must NOT do**:
  - Do NOT rewrite the entire wait loop with polling/subprocess signaling — over-engineering for 2-3 sessions
  - Do NOT use `wait -n` without a bash 5.1+ guard (current script targets bash 4.0+)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-low` — Small reliability fix with clear scope
  - **Skills**: [] — Bash signal/wait knowledge is standard

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 9)
  - **Parallel Group**: Wave 3
  - **Blocks**: None
  - **Blocked By**: Task 6 (needs remote dir check in place)

  **References**:
  - `/tmp/sftp-parallel-upload-fixed.sh` — The file being edited
  - Lines 97-107 of original: The wait loop
  - Line 100-101: `if ! wait "$PID"; then ... echo ... exit $?` — The fragile pattern

  **QA Scenarios**:

  ```
  Scenario: Exit code captured reliably
    Tool: Bash
    Preconditions: Fixed script exists
    Steps:
      1. grep -A2 'wait' /tmp/sftp-parallel-upload-fixed.sh | grep 'EXIT_CODE'
    Expected Result: EXIT_CODE variable found immediately after wait
    Failure Indicators: No EXIT_CODE, still using $? inline
    Evidence: .sisyphus/evidence/task-10-exit-code.txt
  ```

  **Commit**: YES (groups with Wave 3)
  - Message: `fix(sftp-upload): preserve sftp exit codes reliably in wait loop`
  - Files: `/tmp/sftp-parallel-upload-fixed.sh`
  - Pre-commit: `bash -n /tmp/sftp-parallel-upload-fixed.sh`

- [ ] 11. Generate diff file + final validation

  **What to do**:
  - Generate the diff file:
    ```bash
    diff -u /tmp/sftp-parallel-upload.sh /tmp/sftp-parallel-upload-fixed.sh > /tmp/sftp-parallel-upload-fixed.sh.patch
    ```
  - Run final validation on the fixed script:
    ```bash
    bash -n /tmp/sftp-parallel-upload-fixed.sh
    shellcheck -s bash /tmp/sftp-parallel-upload-fixed.sh
    ```
  - Verify the diff file is non-empty and shows all expected changes
  - Verify the original file is unchanged:
    ```bash
    git diff /tmp/sftp-parallel-upload.sh  # should show nothing
    ```

  **Must NOT do**:
  - Do NOT modify the original script
  - Do NOT skip shellcheck

  **Recommended Agent Profile**:
  - **Category**: `quick` — Diff generation + validation checks
  - **Skills**: [`git-master`] — For diff/patch understanding

  **Parallelization**:
  - **Can Run In Parallel**: NO — Must wait for all fixes
  - **Parallel Group**: Wave 4 (sequential within wave)
  - **Blocks**: F1-F4 (final verification)
  - **Blocked By**: Tasks 1-10 (all fixes must be complete)

  **References**:
  - `/tmp/sftp-parallel-upload.sh` — Original (must remain unchanged)
  - `/tmp/sftp-parallel-upload-fixed.sh` — Fixed version

  **QA Scenarios**:

  ```
  Scenario: Diff file generated and non-empty
    Tool: Bash
    Preconditions: All previous tasks complete
    Steps:
      1. test -s /tmp/sftp-parallel-upload-fixed.sh.patch && echo "NONEMPTY" || echo "EMPTY"
      2. wc -l /tmp/sftp-parallel-upload-fixed.sh.patch
    Expected Result: NONEMPTY, > 50 lines (12 issues addressed)
    Failure Indicators: EMPTY or very small diff
    Evidence: .sisyphus/evidence/task-11-diff.txt

  Scenario: Shellcheck passes
    Tool: Bash
    Preconditions: Fixed script exists
    Steps:
      1. shellcheck -s bash /tmp/sftp-parallel-upload-fixed.sh 2>&1 || true
    Expected Result: No errors (warnings acceptable)
    Failure Indicators: Shellcheck errors (not warnings)
    Evidence: .sisyphus/evidence/task-11-shellcheck.txt

  Scenario: Original file unchanged
    Tool: Bash
    Preconditions: Original script was copied in Task 1
    Steps:
      1. diff /tmp/sftp-parallel-upload.sh /tmp/sftp-parallel-upload.sh  # self-compare always works
      2. md5sum /tmp/sftp-parallel-upload.sh
    Expected Result: Original file exists and is unchanged from start
    Failure Indicators: Original modified or missing
    Evidence: .sisyphus/evidence/task-11-original-unchanged.txt
  ```

  **Commit**: YES (standalone)
  - Message: `chore(sftp-upload): generate diff file and validate`
  - Files: `/tmp/sftp-parallel-upload-fixed.sh.patch`
  - Pre-commit: `bash -n /tmp/sftp-parallel-upload-fixed.sh`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists in the fixed script (grep for specific patterns). For each "Must NOT Have": search fixed script for forbidden patterns — reject with line number if found. Check evidence files exist in `.sisyphus/evidence/`. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run `bash -n` + `shellcheck -s bash` on the fixed script. Review all changed code for: unquoted variable expansions, empty error messages, commented-out code, unreachable paths, unnecessary subshells. Check AI slop: excessive comments, over-abstraction, generic variable names. Verify the diff file is correct and complete.
  Output: `Syntax [PASS/FAIL] | Shellcheck [PASS/FAIL] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
  Start from clean state. Execute key QA scenarios: (1) `-j 0` rejected, (2) extra positional arg rejected, (3) unreachable host fails fast, (4) bash syntax check passes, (5) shellcheck passes. Test edge cases: empty directory, single file, filenames with spaces. Save to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff. Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Verify original file is untouched. Flag any unaccounted changes in the fixed script.
  Output: `Tasks [N/N compliant] | Original [UNCHANGED/MODIFIED] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

### Wave 1 (atomic — foundation)
```
fix(sftp-upload): copy to new file + bash version guard
fix(sftp-upload): validate -j is positive integer
fix(sftp-upload): reject extra positional arguments
fix(sftp-upload): quote all variable expansions, fix cd $REMOTE_DIR
```

### Wave 2 (atomic — safety & correctness)
```
fix(sftp-upload): add SSH auth pre-check before forking
fix(sftp-upload): add remote directory existence check
fix(sftp-upload): add connection timeout and keepalive to sftp
fix(sftp-upload): properly escape filenames in sftp batch generation
```

### Wave 3 (atomic — UX)
```
feat(sftp-upload): add basic session progress reporting
fix(sftp-upload): preserve sftp exit codes reliably in wait loop
```

### Wave 4 (standalone)
```
chore(sftp-upload): generate diff file and validate
```

> Note: Since this is in /tmp (not a git repo), commits are advisory — the executor should track which changes are applied and group them logically if a git repo is later initialized.

---

## Success Criteria

### Verification Commands
```bash
# Syntax check
bash -n /tmp/sftp-parallel-upload-fixed.sh  # Expected: no output (success)

# Shellcheck
shellcheck -s bash /tmp/sftp-parallel-upload-fixed.sh  # Expected: no errors

# Diff exists and is substantial
test -s /tmp/sftp-parallel-upload-fixed.sh.patch && echo "OK"  # Expected: OK

# All Metis issues addressed
grep -c 'BASH_VERSINFO' /tmp/sftp-parallel-upload-fixed.sh  # >= 1 (issue 8)
grep 'BatchMode=yes' /tmp/sftp-parallel-upload-fixed.sh     # present (issues 4, 6)
grep 'test -d' /tmp/sftp-parallel-upload-fixed.sh            # present (issue 5)
grep 'ConnectTimeout' /tmp/sftp-parallel-upload-fixed.sh     # present (issue 6)
grep 'ESCAPED' /tmp/sftp-parallel-upload-fixed.sh            # present (issue 7)
grep 'EXIT_CODE' /tmp/sftp-parallel-upload-fixed.sh          # present (issue 11)
grep 'must be a positive integer' /tmp/sftp-parallel-upload-fixed.sh  # present (issue 3)
grep 'unexpected argument' /tmp/sftp-parallel-upload-fixed.sh        # present (issue 12)

# Original unchanged
diff <(md5sum /tmp/sftp-parallel-upload.sh) <(cat <<'EOF'
# compare against original hash recorded at start
EOF
)
```

### Final Checklist
- [ ] All 8 "Must Have" items present in fixed script
- [ ] All "Must NOT Have" items absent from fixed script
- [ ] `bash -n` passes on fixed script
- [ ] `shellcheck` passes on fixed script (errors = fail, warnings = acceptable)
- [ ] Original script `/tmp/sftp-parallel-upload.sh` unchanged
- [ ] Diff file `/tmp/sftp-parallel-upload-fixed.sh.patch` generated
- [ ] All Metis issues #1-#12 addressed
- [ ] `put -f` preserved (core feature)
- [ ] Evidence files captured for each task
