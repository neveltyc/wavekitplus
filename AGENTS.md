# wavekit-plus Agent Notes

Keep this file short. It is a map for future agents, not the full API manual.

## Working Rules

- Start with `git status --short --branch`; do not revert user changes.
- Prefer current source, README, and CHANGELOG over older planning docs.
- Do not tag a release until tests pass, docs/version are updated, changes are
  committed, and the annotated tag is created.
- Use `.\release_tag.ps1 -Version vX.Y.Z -CommitMessage "release: vX.Y.Z"` for
  releases. It protects tracked VCD fixtures from timestamp-only Iverilog churn.
- Keep generated artifacts out of commits. `.gitignore` covers example VCD/VVP
  outputs, local test artifacts, and transient release files.
- FST support is optional (`pip install .[fst]` / `pylibfst`). FSDB support needs
  the Verdi NPI runtime.

## Important Files

- `README.md` / `README_ZH.md`: user-facing overview, setup, examples, tests,
  and release command.
- `CHANGELOG.md`: release notes; add an `Unreleased` entry before tagging.
- `pyproject.toml`: package version, dependencies, ruff/mypy/pytest config.
- `release_tag.ps1`: release test/commit/tag workflow.
- `src/wavekit/readers/base.py`: shared Reader APIs, pattern matching, eval.
- `src/wavekit/readers/vcd/reader.py`: VCD loading, signal cache, x/z mask,
  clock edge selection.
- `src/wavekit/waveform.py`: Waveform operations, slicing, x/z propagation.
- `src/wavekit/pattern/`: temporal pattern DSL and engine.
- `tests/run_tests.py`: self-contained smoke/regression suite, no pytest needed.
- `tests/test_*.py`: broader pytest suite when dev dependencies are installed.
- `wavekit_plus_dev_spec.md` and `wavekitplus_feature_spec.md`: historical
  implementation plans; useful context, but not always current behavior.

## Quick Checks

```powershell
$env:PYTHONPATH = "src"
python tests/run_tests.py
python -m pytest -q
git status --short
```
