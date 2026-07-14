# `/rhiza:new`

Scaffold a new source module and its **mirrored test file** in a rhiza-managed
Python repo, keeping the 1:1 test/source layout parity that `/rhiza:quality`
enforces.

```
/rhiza:new <module name> [--class Name] [path to a repo root]
```

The module name may be dotted or slashed for a subpackage (`parsing`,
`utils.parsing`, `utils/parsing`).

## What it does

Runs the bundled `scripts/new_module.py` — stdlib-only — which:

- discovers the single package under `src/` (the src-layout root);
- writes `src/<pkg>/…/<name>.py` with a module docstring and, unless `--class`
  is given, one docstringed placeholder function;
- writes the matching `tests/<pkg>/…/test_<name>.py` — mirroring the module's
  path relative to `src/`, exactly as `check_test_layout.py` expects;
- for each `--class Name`, adds `class Name` to the module and a matching
  `TestName` to the test file (satisfying the class-parity rule);
- creates any missing `__init__.py` for new subpackages.

Pass `--json` for a `{created, skipped}` report, or `--src` / `--tests` to match
non-default source/tests roots.

## Notes

- Works without the `rhiza` CLI installed.
- **Never overwrites** — existing files are reported as skipped, so a re-run is
  safe.
- Stubs are intentionally minimal (docstrings + `TODO`s); the generated test
  starts as a placeholder to replace with a real assertion. For the layout gate
  and the rest of the quality bar, see [`/rhiza:quality`](quality.md).
