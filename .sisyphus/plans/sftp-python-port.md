# Plan: sftp-parallel Python Port

## TL;DR

> **Quick Summary**: Port the bash parallel SFTP uploader to a Python package that invokes `sftp -f` via subprocess (preserving fsync guarantee), with --verify (checksum vía SSH), progress bar (Rich), --skip-existing (size comparison), and proper signal handling.
> 
> **Deliverables**:
> - `sftp-parallel` pip-installable package (pyproject.toml)
> - CLI: `sftp-parallel upload [OPTIONS] LOCAL_DIR HOST:REMOTE_DIR`
> - --verify via SSH exec (md5sum/sha256sum)
> - --skip-existing via size comparison
> - Rich progress bar
> - pytest test suite (mocked subprocess)
> 
> **Estimated Effort**: Large (10+ waves)
> **Parallel Execution**: YES - 5-8 tasks per wave
> **Critical Path**: Phase 0 spikes → Package skeleton → Core upload → Parallel → Features → Tests

---

## Context

### Original Request
Port bash script to Python with subprocess to `sftp` (preserving `put -f`), adding --verify, progress bar, and --skip-existing.

### Interview Summary
**Key Discussions**:
- Format: Python package (pip installable), NOT single-file script
- CLI: New interface from scratch (not bash-compatible)
- Core: subprocess to `sftp -b -` (keeps `put -f` fsync guarantee)
- No systemd-run: Python handles signals with signal.signal() + subprocess.Popen process groups
- Features: --verify (checksum via SSH), progress bar (Rich), --skip-existing (size comparison)
- No --retry (user didn't select)
- Python 3.13+ (newest features)
- Package name: `sftp-parallel`
- No paramiko (can't guarantee fsync)
- --skip-existing: compare sizes (existence + size mismatch = re-upload)

**Research Findings**:
- sftp -N disables quiet mode set by -b (confirmed correct)
- sftp batch mode aborts on first put failure
- sftp has NO native checksum command — --verify requires separate SSH exec
- --skip-existing needs remote ls -l parsing (fragile but workable)
- Progress bar: sftp batch mode doesn't emit progress; need to track files completed, not bytes

### Metis Review
**Identified Gaps** (addressed):
- --verify requires SSH (not just SFTP) — acknowledged, user chose checksum vía SSH
- --skip-existing needs remote listing — acknowledged, user chose size comparison
- Progress bar feasibility: sftp doesn't emit per-byte progress — will track files completed
- Authentication: SSH keys/agent only (no passwords)
- Partial uploads: fail fast, report clearly, no retry
- Python version: 3.13+ (user chose latest)

---

## Work Objectives

### Core Objective
Create a pip-installable Python package `sftp-parallel` that uploads files via parallel `sftp -f` (fsync) sessions, with checksum verification, progress bar, and skip-existing support.

### Concrete Deliverables
- `/tmp/sftp-parallel/` — Complete Python package
- `sftp-parallel upload` CLI command
- pyproject.toml with dependencies (rich, pytest, pytest-mock)
- Test suite with pytest

### Definition of Done
- [x] `pip install -e .` succeeds and `sftp-parallel --help` works
- [x] `sftp-parallel upload -t 4 /tmp/testdir user@host:/remote/path` uploads all files with fsync
- [x] `sftp-parallel upload --verify /tmp/testdir user@host:/remote/path` checksums match
- [x] `sftp-parallel upload --skip-existing /tmp/testdir user@host:/remote/path` skips same-size files
- [x] Rich progress bar shows during upload
- [x] Ctrl+C cleanly terminates all child processes
- [x] `pytest tests/` passes all tests (224/224)
- [x] Exit codes: 0 success, 2 usage error, 74 upload failure

### Must Have
- subprocess to `sftp -b -` with `put -f` (fsync guarantee)
- Parallel sessions with configurable -j/--parallel
- --verify via SSH checksum (md5sum/sha256sum)
- --skip-existing via size comparison
- Rich progress bar (files completed / total)
- Signal handling (SIGINT/SIGTERM clean termination)
- pyproject.toml package structure
- Type hints throughout
- Exit code differentiation

### Must NOT Have (Guardrails)
- NO paramiko or async SSH libraries
- NO systemd-run integration
- NO retry logic
- NO password authentication (SSH keys/agent only)
- NO per-file progress bars (single aggregate bar only)
- NO configuration files (CLI flags only for MVP)
- NO resume interrupted uploads
- NO compression or encryption
- NO GUI/TUI beyond Rich progress bar

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed.

### Test Decision
- **Infrastructure exists**: NO (Python test framework needed)
- **Automated tests**: TDD approach — write failing tests first, then implement
- **Framework**: pytest + pytest-mock
- **Integration tests**: Manual (requires real SFTP server at fernando@beelink)

### QA Policy
- Unit tests mock subprocess.Popen, don't need real SFTP server
- Integration tests use fernando@beelink:/tmp/ for real validation
- Every task MUST include agent-executed QA scenarios
- Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`

---

## Execution Strategy

### Phase 0: Feasibility Spikes (MUST complete before Phase 1)

```
Wave 0 (Feasibility — MUST PASS before proceeding):
├── Task 0.1: Verify --verify via SSH exec works [quick]
├── Task 0.2: Verify sftp batch mode output capturable [quick]
└── Task 0.3: Verify Rich progress bar works with subprocess [quick]
```

### Phase 1: Package Skeleton (after Phase 0)

```
Wave 1 (Foundation):
├── Task 1: Create pyproject.toml + package structure [quick]
├── Task 2: Implement CLI with argparse (--parallel, --verify, --skip-existing, --verbose) [unspecified-high]
├── Task 3: Implement sftp_escape() and batch command generation [quick]
└── Task 4: Implement subprocess wrapper for single sftp invocation [unspecified-high]

Wave 2 (Core Upload):
├── Task 5: Implement single file upload end-to-end [deep]
├── Task 6: Implement file discovery (local dir scanning) [quick]
├── Task 7: Implement round-robin file distribution (parallel sessions) [unspecified-high]
└── Task 8: Implement parallel upload with Popen process management [deep]

Wave 3 (Features):
├── Task 9: Implement --skip-existing (remote ls -l, size comparison) [unspecified-high]
├── Task 10: Implement --verify (SSH exec checksum comparison) [deep]
├── Task 11: Implement Rich progress bar [visual-engineering]
└── Task 12: Implement signal handling (SIGINT/SIGTERM clean termination) [deep]

Wave 4 (Polish + Tests):
├── Task 13: Write pytest test suite (unit tests, mocked subprocess) [unspecified-high]
├── Task 14: Write integration tests (real SFTP server) [unspecified-high]
├── Task 15: Error messages, exit codes, edge cases [unspecified-high]
└── Task 16: README documentation + usage examples [writing]

Wave FINAL (Verification):
├── Task F1: Full regression test against bash version [deep]
├── Task F2: Edge case testing (spaces, special chars, empty dir, large files) [unspecified-high]
├── Task F3: Signal handling test (Ctrl+C, kill) [unspecified-high]
└── Task F4: Code quality review (mypy, ruff, coverage) [oracle]
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|-----------|--------|
| 0.1 | - | 10 |
| 0.2 | - | 4, 11 |
| 0.3 | - | 11 |
| 1 | - | 2, 3, 4 |
| 2 | 1 | 5 |
| 3 | 1 | 5 |
| 4 | 1, 0.2 | 5 |
| 5 | 2, 3, 4 | 8 |
| 6 | 1 | 7 |
| 7 | 6 | 8 |
| 8 | 5, 7 | 9, 10, 12 |
| 9 | 8 | F1 |
| 10 | 8, 0.1 | F1 |
| 11 | 0.3, 8 | F1 |
| 12 | 8 | F3 |
| 13 | 5-12 | F1 |
| 14 | 13 | F2 |
| 15 | 13 | F1 |
| 16 | 13 | - |

### Agent Dispatch Summary

- **Wave 0**: 3 tasks → `quick` × 3
- **Wave 1**: 4 tasks → `quick` × 3, `unspecified-high` × 1
- **Wave 2**: 4 tasks → `deep` × 2, `quick` × 1, `unspecified-high` × 1
- **Wave 3**: 4 tasks → `deep` × 2, `visual-engineering` × 1, `unspecified-high` × 1
- **Wave 4**: 4 tasks → `unspecified-high` × 3, `writing` × 1
- **FINAL**: 4 tasks → `deep` × 1, `unspecified-high` × 2, `oracle` × 1

---

## TODOs

(To be filled incrementally — this is the skeleton. Each task will be expanded with full detail during execution.)

- [x] 0.1. Verify --verify via SSH exec (md5sum/sha256sum on remote)
- [x] 0.2. Verify sftp batch mode output capturable for progress
- [x] 0.3. Verify Rich progress bar works with subprocess.Popen
- [x] 1. Create pyproject.toml + package structure
- [x] 2. Implement CLI with argparse
- [x] 3. Implement sftp_escape() and batch command generation
- [x] 4. Implement subprocess wrapper for single sftp invocation
- [x] 5. Implement single file upload end-to-end
- [x] 6. Implement file discovery (local dir scanning)
- [x] 7. Implement round-robin file distribution
- [x] 8. Implement parallel upload with Popen process management
- [x] 9. Implement --skip-existing (remote ls, size comparison)
- [x] 10. Implement --verify (SSH exec checksum)
- [x] 11. Implement Rich progress bar
- [x] 12. Implement signal handling (SIGINT/SIGTERM)
- [x] 13. Write pytest test suite
- [x] 14. Write integration tests (real SFTP)
- [x] 15. Error messages, exit codes, edge cases
- [x] 16. README documentation + usage examples
- [x] 17. AGENTS.md (project knowledge for AI assistants)
- [x] 18. .gitignore (exclude .sisyphus/, __pycache__, *.egg-info, dist/, .mypy_cache, etc.)
- [x] F1. Full regression test against bash version
- [x] F2. Edge case testing
- [x] F3. Signal handling test
- [x] F4. Code quality review

---

## Commit Strategy

- **0.x**: `spike(phase0): verify --verify, sftp output, Rich compatibility`
- **1**: `feat: package skeleton with pyproject.toml`
- **2**: `feat: CLI argument parsing with argparse`
- **3**: `feat: sftp escape and batch command generation`
- **4**: `feat: subprocess wrapper for sftp invocation`
- **5**: `feat: single file upload end-to-end`
- **6**: `feat: file discovery and local dir scanning`
- **7**: `feat: round-robin file distribution`
- **8**: `feat: parallel upload with process management`
- **9**: `feat: --skip-existing with size comparison`
- **10**: `feat: --verify with SSH checksum`
- **11**: `feat: Rich progress bar`
- **12**: `feat: signal handling for clean termination`
- **13**: `test: pytest unit test suite`
- **14**: `test: integration tests with real SFTP`
- **15**: `fix: error messages, exit codes, edge cases`
- **16**: `docs: README and usage examples`
- **17**: `docs: AGENTS.md project knowledge`
- **18**: `chore: add .gitignore`
- **CLI**: Parallelism flag is `-t/--threads` (NOT -j)

## Success Criteria

### Verification Commands
```bash
# Package installation
pip install -e . && sftp-parallel --help  # Shows usage

# Unit tests
pytest tests/ -v  # All pass

# Upload (requires SFTP server)
sftp-parallel upload -j 4 /tmp/testdir fernando@beelink:/tmp/sftp-test  # Exit 0

# Verify
sftp-parallel upload --verify /tmp/testdir fernando@beelink:/tmp/sftp-test  # Checksums match

# Skip existing
sftp-parallel upload --skip-existing /tmp/testdir fernando@beelink:/tmp/sftp-test  # Skips same-size

# Type checking
mypy src/  # No errors
```

### Final Checklist
- [x] All "Must Have" present
- [x] All "Must NOT Have" absent
- [x] pip install works
- [x] pytest passes (224/224)
- [x] mypy --strict passes
- [x] ruff check passes
- [x] Rich progress bar displays during upload (v2 with per-file byte-level progress)
- [x] Ctrl+C terminates cleanly