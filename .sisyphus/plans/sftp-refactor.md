# Plan: Refactor sftp-parallel-upload.sh

## TL;DR

> **Quick Summary**: Refactor the 172-line parallel SFTP upload script for code quality — extract functions, add constants, improve naming, add logging functions, fix ShellCheck warnings, add long options, differentiate exit codes, wrap in main(). No new features. Final task proposes new features list.

> **Deliverables**:
> - Refactored script at /tmp/sftp-parallel-upload-v7.sh
> - Baseline behavior capture before refactoring
> - Test suite execution against real SFTP server (fernando@beelink)
> - Feature proposal list as final task

> **Estimated Effort**: Medium (6-8 task waves)
> **Parallel Execution**: YES - 5 waves
> **Critical Path**: Baseline → Constants/Logging/Rename → Function extraction → ShellCheck/Options/ExitCodes → Final testing + Feature proposal

---

## Context

### Original Request
User requested a complete review plan — not just bugs, but implementation improvements and refactoring. After clarification: refactoring ONLY, no new features. New features will be proposed separately at the end.

### Interview Summary
**Key Discussions**:
- Scope: Refactoring only, no new features. Final task proposes features.
- Testing: Real SFTP server at fernando@beelink:/tmp/, create temp files with dd, clean up after.
- New feature user will request: glob patterns for file selection instead of entire directory.
- Target: Linux-only (GNU tools OK), bash 4+.

**Research Findings**:
- Oracle: Extract 4-5 functions, add logging, rename TMPDIR→WORK_DIR, add constants, add long options.
- Librarian: ShellCheck warnings (SC2154, SC2086), Google Shell Style Guide deviations (printf vs echo, brace-delimit), differentiated exit codes, main() wrapper pattern.
- Metis: HIGH priority features include -i/-P flags, --dry-run, --verify, --log-file, --skip-existing. But these are OUT OF SCOPE for this plan.

### Metis Review
**Identified Gaps** (addressed):
- Need baseline behavior capture BEFORE any refactoring
- Need exit code mapping table (old→new)
- Edge cases: spaces in filenames, special chars, empty file list, concurrent runs
- Per-commit verification requirement
- Scope creep risk: logging function extraction must NOT add log levels or file logging
- TMPDIR→WORK_DIR rename must preserve backwards-compatible env var reading

---

## Work Objectives

### Core Objective
Refactor sftp-parallel-upload-v6.sh for production quality — better structure, readability, maintainability — while preserving exact behavior.

### Concrete Deliverables
- /tmp/sftp-parallel-upload-v7.sh (refactored version)
- Baseline output capture at /tmp/sftp-baseline-*.txt
- Feature proposal list as final task output

### Definition of Done
- [ ] All refactoring tasks completed
- [ ] Script runs identically to v6 for same inputs (verified by diff)
- [ ] Exit codes match documented mapping
- [ ] ShellCheck passes with 0 warnings (or documented exceptions)
- [ ] All test scenarios pass against real SFTP server
- [ ] Script under 250 lines
- [ ] Feature proposal list delivered

### Must Have
- Function extraction (validate_inputs, distribute_files, create_batch, run_uploads, cleanup)
- Named constants (MAX_JOBS, CONNECT_TIMEOUT, SYSTEMD_TIMEOUT, DEFAULT_JOBS, DEFAULT_REMOTE_DIR)
- TMPDIR→WORK_DIR rename
- Logging functions (log_info, log_error, log_debug)
- main() wrapper
- --long-options aliases (--jobs, --remote-dir, --help)
- ShellCheck compliance
- Exit code differentiation
- Logical section headers

### Must NOT Have (Guardrails)
- NO new features (retry, timeout config, progress bars, etc.)
- NO new dependencies
- NO change to parallel upload algorithm
- NO change to error message text
- NO change to output format (exact string matching may exist)
- NO change to systemd-run invocation syntax
- NO change to sftp batch command syntax (put -f must remain)
- NO config file support
- NO change to file selection logic (still entire directory)
- Script must NOT exceed 250 lines

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed.

### Test Decision
- **Infrastructure exists**: NO (no test framework)
- **Automated tests**: Tests-after approach with real SFTP server
- **Framework**: None — use real SFTP server

### QA Policy
Every task MUST include agent-executed QA scenarios.

- **Server**: fernando@beelink:/tmp/
- **Test files**: Create with `dd if=/dev/urandom of=/tmp/sftp-test-XXX bs=1K count=N`
- **Cleanup**: Remove test files from both local and remote after testing
- **Total size limit**: 2GB max

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Foundation — MUST complete first):
├── Task 1: Baseline capture + test file setup [quick]
├── Task 2: Add named constants [quick]
├── Task 3: Extract logging functions (log_info, log_error, log_debug) [quick]
└── Task 4: Rename TMPDIR→WORK_DIR [quick]

Wave 2 (Function extraction — depends on Wave 1):
├── Task 5: Extract validate_inputs() [unspecified-high]
├── Task 6: Extract distribute_files() [unspecified-high]
├── Task 7: Extract create_batch() [unspecified-high]
└── Task 8: Extract run_uploads() + collect_results() [unspecified-high]

Wave 3 (Structure and compliance — depends on Wave 2):
├── Task 9: Wrap in main() function [unspecified-high]
├── Task 10: Add --long-options aliases [quick]
├── Task 11: Fix ShellCheck warnings [quick]
└── Task 12: Add exit code differentiation [quick]

Wave 4 (Polish — depends on Wave 3):
├── Task 13: Reorganize into logical sections with headers [quick]
├── Task 14: Add environment variable configuration (SFTP_JOBS) [quick]
└── Task 15: Final cleanup (comments, formatting, consistency) [quick]

Wave FINAL (Verification + Feature Proposal):
├── Task F1: Full regression test against baseline [deep]
├── Task F2: Edge case testing (spaces, special chars, empty dir) [unspecified-high]
├── Task F3: Feature proposal list [writing]
└── Task F4: Cleanup (remove test files from fernando@beelink) [quick]

Critical Path: Task 1 → Tasks 2-4 → Tasks 5-8 → Tasks 9-12 → Tasks 13-15 → F1-F4
Max Concurrent: 4 (Waves 1-3)
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|-----------|--------|
| 1 | - | 2-15, F1-F4 |
| 2 | 1 | 5-8 |
| 3 | 1 | 5-8 |
| 4 | 1 | 5-8 |
| 5 | 2,3,4 | 9 |
| 6 | 2,3,4 | 9 |
| 7 | 2,3,4 | 9 |
| 8 | 2,3,4 | 9 |
| 9 | 5-8 | 13 |
| 10 | 5-8 | 14 |
| 11 | 5-8 | 15 |
| 12 | 5-8 | 14 |
| 13 | 9 | F1 |
| 14 | 10,12 | F1 |
| 15 | 11 | F1 |
| F1 | 13-15 | F3 |
| F2 | 13-15 | F3 |
| F3 | F1,F2 | - |
| F4 | F1,F2 | - |

### Agent Dispatch Summary

- **Wave 1**: 4 tasks → `quick` × 4
- **Wave 2**: 4 tasks → `unspecified-high` × 4
- **Wave 3**: 4 tasks → `quick` × 3, `unspecified-high` × 1
- **Wave 4**: 3 tasks → `quick` × 3
- **FINAL**: 4 tasks → `deep` × 1, `unspecified-high` × 1, `writing` × 1, `quick` × 1

---

## TODOs

- [ ] 1. Baseline Capture + Test File Setup

  **What to do**:
  - Copy v6 to v7 (`cp /tmp/sftp-parallel-upload-v6.sh /tmp/sftp-parallel-upload-v7.sh`)
  - Create test directory: `mkdir -p /tmp/sftp-refactor-test && cd /tmp/sftp-refactor-test`
  - Create 5 test files of varying sizes: `dd if=/dev/urandom of=file1.txt bs=1K count=10`, etc.
  - Create 1 file with spaces: `dd if=/dev/urandom of="file with spaces.txt" bs=1K count=5`
  - Create 1 file with special chars: `dd if=/dev/urandom of="file\$name.txt" bs=1K count=5`
  - Create remote test dir: `ssh fernando@beelink 'mkdir -p /tmp/sftp-refactor-test'`
  - Run v6 against test files and capture: stdout, stderr, exit code
  - Run v6 with -h flag and capture help output
  - Run v6 with invalid args and capture error output
  - Save all captures to /tmp/sftp-baseline-*.txt

  **Must NOT do**:
  - Do NOT modify the v6 script
  - Do NOT exceed 2GB total test file size

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - **Skills Evaluated but Omitted**: `persist-knowledge` (operational, not durable knowledge)

  **Parallelization**:
  - **Can Run In Parallel**: YES, with Tasks 2-4 (but depends on v7 copy)
  - **Parallel Group**: Wave 1 (with Tasks 2, 3, 4)
  - **Blocks**: Tasks 2-15, F1-F4
  - **Blocked By**: None (can start immediately)

  **References** (CRITICAL):

  **Pattern References**:
  - `/tmp/sftp-parallel-upload-v6.sh` — Current script to copy as baseline

  **Why Each Reference Matters**:
  - v6 script is the source of truth for all behavioral comparisons

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Baseline capture succeeds
    Tool: Bash
    Preconditions: Test directory created, test files exist, remote dir exists
    Steps:
      1. ls /tmp/sftp-refactor-test/ | wc -l  # Expect: 7+ files
      2. ssh fernando@beelink 'ls /tmp/sftp-refactor-test/'  # Expect: empty (no files yet)
      3. ls /tmp/sftp-baseline-*.txt | wc -l  # Expect: 3+ baseline captures
    Expected Result: All baseline files created, remote dir accessible
    Failure Indicators: Missing baseline files, remote dir inaccessible
    Evidence: .sisyphus/evidence/task-1-baseline-capture.txt

  Scenario: v6 script runs successfully against test files
    Tool: Bash
    Preconditions: Test files in /tmp/sftp-refactor-test/
    Steps:
      1. /tmp/sftp-parallel-upload-v6.sh -j 2 -r /tmp/sftp-refactor-test fernando@beelink /tmp/sftp-refactor-test
      2. echo $?  # Expect: 0
      3. ssh fernando@beelink 'ls /tmp/sftp-refactor-test/' | wc -l  # Expect: 7+ files
    Expected Result: Exit code 0, all files uploaded
    Failure Indicators: Exit code non-zero, missing remote files
    Evidence: .sisyphus/evidence/task-1-v6-success.txt
  ```

  **Evidence to Capture**:
  - [ ] Each evidence file named: task-1-{scenario-slug}.txt
  - [ ] Baseline output files in /tmp/sftp-baseline-*.txt

  **Commit**: YES (groups with 1)
  - Message: `refactor: capture baseline behavior and set up test files`
  - Files: `/tmp/sftp-parallel-upload-v7.sh` (copy of v6), `/tmp/sftp-refactor-test/`
  - Pre-commit: Verify v7 matches v6 byte-for-byte

- [ ] 2. Add Named Constants

  **What to do**:
  - Add at top of script (after `set -euo pipefail`):
    ```bash
    readonly MAX_JOBS=16
    readonly CONNECT_TIMEOUT=10
    readonly SYSTEMD_TIMEOUT=86400
    readonly DEFAULT_JOBS=2
    readonly DEFAULT_REMOTE_DIR="."
    readonly EX_OK=0
    readonly EX_USAGE=2
    readonly EX_NOINPUT=66
    readonly EX_JOBFAIL=74
    ```
  - Replace all hardcoded values with constants: `16` → `$MAX_JOBS`, `10` → `$CONNECT_TIMEOUT`, `86400` → `$SYSTEMD_TIMEOUT`, `2` → `$DEFAULT_JOBS`, `"."` → `$DEFAULT_REMOTE_DIR`
  - Test: script behavior unchanged

  **Must NOT do**:
  - Do NOT make MAX_JOBS configurable beyond 16 (that's a feature)
  - Do NOT change any behavior

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 1, 3, 4 — but copy v7 first)
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 5-8
  - **Blocked By**: Task 1 (needs v7 copy)

  **References**:

  **Pattern References**:
  - `/tmp/sftp-parallel-upload-v7.sh` lines 2 (set flags), 32-33 (defaults), 80 (max jobs), 109/147 (connect timeout), 6 (systemd timeout)

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: Constants replace hardcoded values
    Tool: Bash
    Steps:
      1. grep -c 'MAX_JOBS\|CONNECT_TIMEOUT\|SYSTEMD_TIMEOUT\|DEFAULT_JOBS\|DEFAULT_REMOTE_DIR' /tmp/sftp-parallel-upload-v7.sh  # Expect: 7+ matches
      2. grep -n '16' /tmp/sftp-parallel-upload-v7.sh | grep -v 'MAX_JOBS' | grep -v '# '  # Expect: 0 matches (no leftover hardcoded 16)
      3. /tmp/sftp-parallel-upload-v7.sh -h  # Expect: same output as v6
    Expected Result: All values extracted to constants, no leftover hardcoded numbers
    Failure Indicators: Missing constant references, leftover hardcoded values
    Evidence: .sisyphus/evidence/task-2-constants.txt

  Scenario: Behavior preserved after constants extraction
    Tool: Bash
    Preconditions: Test files in /tmp/sftp-refactor-test/
    Steps:
      1. /tmp/sftp-parallel-upload-v7.sh -j 2 -r /tmp/sftp-refactor-test fernando@beelink /tmp/sftp-refactor-test
      2. echo $?  # Expect: 0
    Expected Result: Files uploaded successfully, exit code 0
    Failure Indicators: Exit code non-zero, missing files
    Evidence: .sisyphus/evidence/task-2-behavior.txt
  ```

  **Commit**: YES (groups with 2)
  - Message: `refactor: add named constants (MAX_JOBS, CONNECT_TIMEOUT, etc.)`
  - Files: `/tmp/sftp-parallel-upload-v7.sh`
  - Pre-commit: Verify v7 runs with same behavior as v6

- [ ] 3. Extract Logging Functions

  **What to do**:
  - Add logging functions after usage():
    ```bash
    log_info()  { printf '→ %s\n' "$*"; }
    log_error() { printf '✗ %s\n' "$*" >&2; }
    log_debug() { [[ "${DEBUG:-0}" == "1" ]] && printf '[DEBUG] %s\n' "$*" >&2 || true; }
    ```
  - Replace all `echo "→ ..."` with `log_info "..."`
  - Replace all `echo "✗ ..." >&2` with `log_error "..."`
  - Test: output matches exactly (character-for-character diff with baseline)

  **Must NOT do**:
  - Do NOT add log levels beyond info/error/debug
  - Do NOT add file logging
  - Do NOT add timestamps
  - Do NOT change output format (printf must produce same output as echo for these messages)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 1, 2, 4)
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 5-8
  - **Blocked By**: Task 1

  **References**:
  - `/tmp/sftp-parallel-upload-v7.sh` lines 71-72, 90-92, 95-99, 102-107, 109-116, 118, 146, 159-169

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: Logging functions produce identical output
    Tool: Bash
    Steps:
      1. diff <(/tmp/sftp-parallel-upload-v6.sh -h 2>&1) <(/tmp/sftp-parallel-upload-v7.sh -h 2>&1)  # Expect: identical
      2. grep -c 'log_info\|log_error\|log_debug' /tmp/sftp-parallel-upload-v7.sh  # Expect: 8+ matches
    Expected Result: Help output identical, logging functions used throughout
    Failure Indicators: Diff shows changes, logging functions not used
    Evidence: .sisyphus/evidence/task-3-logging.txt
  ```

  **Commit**: YES
  - Message: `refactor: extract logging functions (log_info, log_error, log_debug)`
  - Files: `/tmp/sftp-parallel-upload-v7.sh`

- [ ] 4. Rename TMPDIR → WORK_DIR

  **What to do**:
  - Rename variable `TMPDIR` to `WORK_DIR` throughout the script (lines 31, 54, 132)
  - Keep `TMPDIR` as env var fallback: `WORK_DIR="${TMPDIR:-}"`
  - After mktemp: `WORK_DIR=$(mktemp -d)`
  - In cleanup: `[[ -n "${WORK_DIR:-}" && -d "${WORK_DIR:-}" ]] && rm -rf -- "${WORK_DIR:-}"`
  - In upload loop and error reporting: replace all `TMPDIR` references with `WORK_DIR`
  - Test: script behavior unchanged

  **Must NOT do**:
  - Do NOT change mktemp behavior (it still honors system TMPDIR env var)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 1, 2, 3)
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 5-8
  - **Blocked By**: Task 1

  **References**:
  - `/tmp/sftp-parallel-upload-v7.sh` lines 31, 48-55, 132, 147, 160

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: WORK_DIR replaces TMPDIR
    Tool: Bash
    Steps:
      1. grep -c 'WORK_DIR' /tmp/sftp-parallel-upload-v7.sh  # Expect: 5+ matches
      2. grep -n 'TMPDIR' /tmp/sftp-parallel-upload-v7.sh  # Expect: only in TMPDIR env var context
      3. /tmp/sftp-parallel-upload-v7.sh -j 2 -r /tmp/sftp-refactor-test fernando@beelink /tmp/sftp-refactor-test
      4. echo $?  # Expect: 0
    Expected Result: All TMPDIR references updated, script runs correctly
    Failure Indicators: Leftover TMPDIR references, script fails
    Evidence: .sisyphus/evidence/task-4-rename.txt
  ```

  **Commit**: YES
  - Message: `refactor: rename TMPDIR to WORK_DIR`
  - Files: `/tmp/sftp-parallel-upload-v7.sh`

- [ ] 5. Extract validate_inputs() Function

  **What to do**:
  - Extract all input validation (lines 67-107) into a `validate_inputs()` function
  - Pass HOST, LOCAL_DIR, JOBS as arguments or use global variables
  - Function returns 0 on success, non-zero on failure (with specific exit codes)
  - Call site: `validate_inputs || exit $?`
  - Test: all validation error cases still work

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 6, 7, 8)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 9
  - **Blocked By**: Tasks 2, 3, 4

  **References**:
  - `/tmp/sftp-parallel-upload-v7.sh` lines 67-107 (validation block)

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: Validation errors preserved
    Tool: Bash
    Steps:
      1. /tmp/sftp-parallel-upload-v7.sh 2>&1 | head -1  # Expect: error about missing user@host
      2. /tmp/sftp-parallel-upload-v7.sh -j 0 user@host /tmp 2>&1 | head -1  # Expect: error about -j
      3. /tmp/sftp-parallel-upload-v7.sh user@host /nonexistent 2>&1 | head -1  # Expect: error about directory
    Expected Result: All validation errors produce same messages as v6
    Failure Indicators: Different error messages, different exit codes
    Evidence: .sisyphus/evidence/task-5-validation.txt
  ```

  **Commit**: YES
  - Message: `refactor: extract validate_inputs() function`

- [ ] 6. Extract distribute_files() Function

  **What to do**:
  - Extract round-robin bucket distribution (lines 120-129) into `distribute_files()` function
  - Accept FILES array and JOBS count as input
  - Return BUCKETS array (or use nameref)
  - Test: distribution logic produces identical bucket assignments as v6

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 5, 7, 8)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 9
  - **Blocked By**: Tasks 2, 3, 4

  **References**:
  - `/tmp/sftp-parallel-upload-v7.sh` lines 120-129

  **Commit**: YES
  - Message: `refactor: extract distribute_files() function`

- [ ] 7. Extract create_batch() Function

  **What to do**:
  - Extract batch command construction (lines 140-144) into `create_batch()` function
  - Accept REMOTE_DIR, LOCAL_DIR, and file list as input
  - Return BATCH_CMDS string
  - Test: batch command output identical to v6 for same inputs

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 5, 6, 8)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 9
  - **Blocked By**: Tasks 2, 3, 4

  **References**:
  - `/tmp/sftp-parallel-upload-v7.sh` lines 140-144

  **Commit**: YES
  - Message: `refactor: extract create_batch() function`

- [ ] 8. Extract run_uploads() and collect_results() Functions

  **What to do**:
  - Extract upload loop (lines 137-151) into `run_uploads()` function
  - Extract result collection (lines 153-165) into `collect_results()` function
  - Both operate on shared PIDS and WORK_DIR
  - Test: parallel uploads produce identical behavior (same files, same exit codes)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 5, 6, 7)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 9
  - **Blocked By**: Tasks 2, 3, 4

  **References**:
  - `/tmp/sftp-parallel-upload-v7.sh` lines 137-151 (upload loop), 153-165 (results)

  **Commit**: YES
  - Message: `refactor: extract run_uploads() and collect_results() functions`

- [ ] 9. Wrap in main() Function

  **What to do**:
  - Create `main()` function that orchestrates all logic
  - Move global variable declarations inside main() where appropriate
  - Add `main "$@"` call at end of script
  - Test: script behavior identical end-to-end

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO (depends on Tasks 5-8)
  - **Blocked By**: Tasks 5-8
  - **Blocks**: Task 13

  **References**:
  - `/tmp/sftp-parallel-upload-v7.sh` (all of main body)

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: main() wrapper preserves behavior
    Tool: Bash
    Steps:
      1. diff <(/tmp/sftp-parallel-upload-v6.sh -h 2>&1) <(/tmp/sftp-parallel-upload-v7.sh -h 2>&1)  # Expect: identical
      2. /tmp/sftp-parallel-upload-v7.sh -j 2 -r /tmp/sftp-refactor-test fernando@beelink /tmp/sftp-refactor-test
      3. echo $?  # Expect: 0
    Expected Result: Script behavior unchanged after main() wrapper
    Failure Indicators: Different help output, upload failure, wrong exit code
    Evidence: .sisyphus/evidence/task-9-main.txt
  ```

  **Commit**: YES
  - Message: `refactor: wrap script logic in main() function`

- [ ] 10. Add --long-options Aliases

  **What to do**:
  - Add `--jobs=N` as alias for `-j N`
  - Add `--remote-dir=DIR` as alias for `-r DIR`
  - Add `--help` as alias for `-h`
  - Implement by preprocessing $@ before getopts (loop to convert --long to -short)
  - Test: both forms produce identical behavior

  **Must NOT do**:
  - Do NOT remove short options (backward compatibility)
  - Do NOT add any new options beyond aliases for existing ones

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 9, 11, 12)
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 14
  - **Blocked By**: Tasks 5-8

  **Commit**: YES
  - Message: `refactor: add --long-options aliases (--jobs, --remote-dir, --help)`

- [ ] 11. Fix ShellCheck Warnings

  **What to do**:
  - Run `shellcheck /tmp/sftp-parallel-upload-v7.sh`
  - Fix all warnings that don't change behavior
  - Document any warnings that require behavior changes (these become explicit exceptions)
  - Common fixes: quote variable expansions, use `local` for function variables, use `"$@"` not `$@`
  - Test: `shellcheck` returns 0 warnings (or documented exceptions)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 9, 10, 12)
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 15
  - **Blocked By**: Tasks 5-8

  **Commit**: YES
  - Message: `refactor: fix ShellCheck warnings`

- [ ] 12. Add Exit Code Differentiation

  **What to do**:
  - Replace `exit 1` with named exit codes:
    - Usage errors → `$EX_USAGE` (2)
    - Connection/input errors → `$EX_NOINPUT` (66)
    - Upload failures → `$EX_JOBFAIL` (74)
    - Help → `$EX_OK` (0)
  - Create exit code mapping document in comments
  - Test: each error case returns correct exit code

  **Must NOT do**:
  - Do NOT change what constitutes an error (same conditions, different codes)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 9, 10, 11)
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 14
  - **Blocked By**: Tasks 5-8

  **Commit**: YES
  - Message: `refactor: differentiate exit codes (usage=2, connection=66, upload=74)`

- [ ] 13. Reorganize into Logical Sections

  **What to do**:
  - Organize script into sections with clear headers:
    ```
    ## === CONSTANTS ===
    ## === FUNCTIONS ===
    ## === ARGUMENT PARSING ===
    ## === VALIDATION ===
    ## === MAIN ===
    ```
  - Reorder functions, constants, main logic for readability
  - Test: script behavior identical

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO (depends on Task 9)
  - **Blocked By**: Task 9
  - **Blocks**: F1

  **Commit**: YES
  - Message: `refactor: reorganize into logical sections with headers`

- [ ] 14. Add Environment Variable Configuration

  **What to do**:
  - Allow `SFTP_JOBS` env var as default for `-j`
  - Allow `SFTP_CONNECT_TIMEOUT` env var as default for connect timeout
  - Pattern: `JOBS="${SFTP_JOBS:-$DEFAULT_JOBS}"` after arg parsing
  - Test: env vars override defaults, CLI flags override env vars

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 13, 15)
  - **Parallel Group**: Wave 4
  - **Blocks**: F1
  - **Blocked By**: Tasks 10, 12

  **Commit**: YES
  - Message: `refactor: add environment variable configuration (SFTP_JOBS, SFTP_CONNECT_TIMEOUT)`

- [ ] 15. Final Cleanup

  **What to do**:
  - Consistent formatting (indentation, spacing)
  - Comment review (remove stale comments, add section comments)
  - Variable naming consistency (snake_case throughout)
  - Remove any dead code or unused variables
  - Verify line count under 250
  - Test: final full regression

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 13, 14)
  - **Parallel Group**: Wave 4
  - **Blocks**: F1
  - **Blocked By**: Tasks 5-12

  **Commit**: YES
  - Message: `refactor: final cleanup (comments, formatting, consistency)`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

- [ ] F1. **Full Regression Test** — `deep`
  Run all baseline scenarios against refactored v7. Compare output character-for-character with baseline captures. Compare exit codes. Verify all files uploaded correctly to remote. Verify cleanup removes temp files. Test with: 5 regular files, 1 file with spaces, 1 file with special chars, -j 1 (serial), -j 4 (parallel), -h (help), invalid args.

- [ ] F2. **Edge Case Testing** — `unspecified-high`
  Test edge cases: empty directory (should exit with error), file with unicode chars, -j 16 (max parallel), concurrent script runs, SIGINT during upload (Ctrl+C), kill script mid-upload (verify cleanup), -j 0 and -j 17 (validation errors), --jobs=3 and --remote-dir=/path (long options).

- [ ] F3. **Feature Proposal List** — `writing`
  Create /tmp/sftp-feature-proposals.md with prioritized feature list. Each feature includes: description, priority (HIGH/MEDIUM/LOW), estimated complexity, implementation approach. Features: glob patterns (user-requested), -i/-P SSH options, --dry-run, --verify, --log-file, --skip-existing, -R recursive, --retry, --include/--exclude, config file.

- [ ] F4. **Cleanup** — `quick`
  Remove all test files from /tmp/sftp-refactor-test/ and fernando@beelink:/tmp/sftp-refactor-test/. Remove baseline capture files from /tmp/sftp-baseline-*.txt. Leave only the final v7 script.

## Commit Strategy

- **1**: `refactor: capture baseline behavior and set up test files`
- **2**: `refactor: add named constants (MAX_JOBS, CONNECT_TIMEOUT, etc.)`
- **3**: `refactor: extract logging functions (log_info, log_error, log_debug)`
- **4**: `refactor: rename TMPDIR to WORK_DIR`
- **5**: `refactor: extract validate_inputs() function`
- **6**: `refactor: extract distribute_files() function`
- **7**: `refactor: extract create_batch() function`
- **8**: `refactor: extract run_uploads() and collect_results() functions`
- **9**: `refactor: wrap script logic in main() function`
- **10**: `refactor: add --long-options aliases (--jobs, --remote-dir, --help)`
- **11**: `refactor: fix ShellCheck warnings`
- **12**: `refactor: differentiate exit codes (usage=2, connection=66, upload=74)`
- **13**: `refactor: reorganize into logical sections with headers`
- **14**: `refactor: add environment variable configuration (SFTP_JOBS, SFTP_CONNECT_TIMEOUT)`
- **15**: `refactor: final cleanup (comments, formatting, consistency)`

## Success Criteria

### Verification Commands
```bash
# Baseline equivalence
diff <(./sftp-parallel-upload-v6.sh -h 2>&1) <(./sftp-parallel-upload-v7.sh -h 2>&1)  # Help matches

# ShellCheck
shellcheck sftp-parallel-upload-v7.sh  # 0 warnings (or documented exceptions)

# Functional
./sftp-parallel-upload-v7.sh -j 4 -r fernando@beelink /tmp/sftp-refactor-test  # Exit 0
ssh fernando@beelink 'ls /tmp/sftp-refactor-test/'  # Files exist

# Edge cases
./sftp-parallel-upload-v7.sh -j 0 fernando@beelink /tmp 2>&1  # Exit 2 (usage error)
./sftp-parallel-upload-v7.sh --jobs=3 --remote-dir=/tmp fernando@beelink /tmp/sftp-refactor-test  # Long options work
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] Script under 250 lines
- [ ] ShellCheck passes
- [ ] Baseline equivalence verified
- [ ] Feature proposal list delivered