# Front-door JS test harness

A tiny, zero-dependency test harness for the white-labeled front-door's browser
ES modules under `workspace/static/js/`. Until now the front-door's JS was only
syntax-checked (`node --check`); this adds real assertions about what the modules
export and how their pure helpers behave.

## What it covers

`runner.js` dynamically `import()`s eight real front-door modules and makes
**45 assertions** about genuine, stable facts — exported function/constant names
exist with the right type, and pure helpers return the expected value for known
inputs. There is no `assert(true)` filler.

| Module (`workspace/static/js/…`) | What is asserted |
| --- | --- |
| `modelSort.js` | `sortModelIds` / `sortModelObjects` / `compareModelObjects` exist; alphabetical sort after the last `/`, non-mutating, defensive on `null`/`[]` |
| `langIcons.js` | `langIcon` returns an inline `<svg>` for a known language, `""` for unknown/empty, and honors the `size` argument |
| `providers.js` | `providerLogo` maps known model ids (`gpt-4`, `claude-3-opus`) to an `<svg>` and returns `null` otherwise |
| `storage.js` | `KEYS` table + `KEYS.THEME` constant; `getJSON` returns the fallback when the key is missing / `localStorage` is unavailable |
| `platform.js` | `IS_MAC` boolean and the width/AltGr helpers; `isAltGrEvent` truth table (non-mac Ctrl+Alt+AltGraph only) |
| `applicantUpdateView.js` | `formatLogTail` joins lines, trims trailing whitespace, and returns `""` for empty/non-array input |
| `presets.js` | `PROMPT_TEMPLATES` is a non-empty array where every entry has string `id`/`name`/`prompt`; `getCharacterName` defaults to `""` |
| `modalSnap.js` | dock controllers (`makeRightDockController`, `makeEdgeDockController`, `applyRightDock`, `clearDockSide`) are functions |

The eight modules were chosen because they are **pure ES modules that touch no
browser globals at import time**, so the same suite runs both in a browser and
headlessly under Node.

## Run it headlessly (Node)

From the repository root:

```bash
node workspace/tests/js/runner.js
```

Expected last line: `45 passed, 0 failed` (exit code 0; non-zero on any failure).
No npm install, no dependencies — just Node with ES-module support.

### Via the configured test runner (`npm test`)

The suite is also wired into Node's built-in test runner (`node:test`, declared as
the runner in `workspace/package.json`). `front_door.test.js` is a thin `node:test`
wrapper that imports and runs the same `runner.js` assertions, so the suite is
discoverable by `node --test` and therefore by `npm test`:

```bash
cd workspace && npm test          # -> node --test tests/js/*.test.js
```

`node:test` is built into Node (no package download), so this still needs no
`npm install` — `runner.js` remains the single source of truth that also runs in
the browser. CI invokes `npm test` for the front-door alongside the existing
`node --check` syntax gate.

Syntax-check every harness file (mirrors the existing front-door `node --check`
gate):

```bash
for f in workspace/tests/js/*.js; do node --check "$f"; done
```

## Run it in a browser

`runner.js` resolves modules with `../../static/js/<mod>.js`, so the page must be
served such that `workspace/static/js/` sits two directories above
`workspace/tests/js/`. Serve the **repository root** and open the harness page:

```bash
# from the repository root
python3 -m http.server 8765
# then open:
#   http://localhost:8765/workspace/tests/js/test_harness.html
```

The page imports `./runner.js`, which in turn imports `../../static/js/*.js`
(i.e. `/workspace/static/js/*.js` under that server root) and renders a
pass/fail summary plus any failing assertions.

## Notes

- The path `workspace/tests/js/runner.js` → `../../static/js/<mod>.js` →
  `workspace/static/js/<mod>.js` is the single relative specifier used by both
  the Node entry and the browser page, so there is one source of truth for it.
- This harness only adds files under `workspace/tests/js/`; it modifies nothing
  in `workspace/static/js/`. Adding a module to the suite means inspecting it
  first and asserting only facts that are actually true of it.
