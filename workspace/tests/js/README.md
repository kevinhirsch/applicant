# Front-Door JS Test Harness

Smoke-test the front-door JavaScript modules loaded by `frontend/static/index.html`.

## What It Does

- Loads each core ES module via dynamic `import()`.
- Verifies that the module's expected exports exist and have the correct types.
- Reports pass/fail results in the browser DOM.

## How to Run

### 1. Serve the project

You need an HTTP server that serves the repo root (ES modules require `localhost`, not `file://`):

```bash
# Python 3
cd /path/to/repo
python3 -m http.server 8080
```

### 2. Open the harness

Navigate to:

```
http://localhost:8080/workspace/tests/js/test_harness.html
```

The page loads each module and displays a colored summary.

### 3. Read the results

- **✓ green** — export exists with the expected type
- **✗ red** — export missing or wrong type (details shown below)
- **– orange** — skipped (module not available in this build)

A final banner shows `N/M tests passed`.

## Current Suites

| Suite         | Module                          | What's checked                          |
|---------------|---------------------------------|-----------------------------------------|
| `storage`     | `static/js/storage.js`          | `get`, `set`, `remove`, `KEYS`          |
| `ui`          | `static/js/ui.js`               | `el`, `showToast`, `debounce`, `esc`    |
| `markdown`    | `static/js/markdown.js`         | `mdToHtml`, `renderContent`             |
| `sessions`    | `static/js/sessions.js`         | `loadSessions`, `selectSession`         |
| `models`      | `static/js/models.js`           | `refreshModels`, `getCachedItems`       |
| `spinner`     | `static/js/spinner.js`          | `create`, `Spinner` class               |
| `theme`       | `static/js/theme.js`            | `THEMES`, `applyColors`, `getSaved`     |
| `fileHandler` | `static/js/fileHandler.js`      | `addFiles`, `openPicker`                |
| `chatRenderer`| `static/js/chatRenderer.js`     | `addMessage`, `hideWelcomeScreen`       |
| `censor`      | `static/js/censor.js`           | `init`, `isEnabled`, `setEnabled`       |

## Adding a Suite

1. Add an `async function suiteMyModule()` in `runner.js` that returns an array of `TestResult` objects.
2. Add `['myModule', suiteMyModule]` to the `suites` array inside `runAllSuites()`.
3. Reload the harness page.
