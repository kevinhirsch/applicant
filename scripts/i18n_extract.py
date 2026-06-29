#!/usr/bin/env python3
"""Extract user-facing strings from Python source files (i18n, issue #250).

Scans the ``src/`` tree for calls to ``_("...")`` and outputs a JSON template
suitable as a translation source file.

Usage:
    python scripts/i18n_extract.py > translations/template.json
"""

import ast
import json
import os
from pathlib import Path


def extract_strings(root: str) -> dict[str, list[str]]:
    """Scan *root* for ``_("...")`` calls.

    Returns a dict mapping each unique string to the list of file:line locations
    where it was found.
    """
    strings: dict[str, list[str]] = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=path)
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "_"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    msg = node.args[0].value
                    if msg:
                        loc = f"{path}:{node.lineno}"
                        strings.setdefault(msg, []).append(loc)
    return strings


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "src"
    strings = extract_strings(str(root))
    # Output as a JSON template: { "source_string": "source_string", ... }
    template = {msg: msg for msg in sorted(strings)}
    print(json.dumps(template, indent=2, ensure_ascii=False))
    print(f"# Total: {len(template)} strings", file=__import__("sys").stderr)


if __name__ == "__main__":
    main()
