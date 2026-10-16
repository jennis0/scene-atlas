"""Rank tracked source files by comment density, to triage over-commenting.

Counts `#`/`//` comment lines and docstring / block-comment lines against
non-blank code lines. Test files and files under 30 code lines are skipped.

    uv run python scripts/quality/comment_density.py [repo-root]
"""

import ast
import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

MIN_CODE_LINES = 30
SKIP = re.compile(r"(^ignore/|^e2e/fixtures|/tests?/|__tests__|\.test\.)")


def python_counts(src: str) -> tuple[int, int, int]:
    comments = {
        t.start[0]
        for t in tokenize.generate_tokens(io.StringIO(src).readline)
        if t.type == tokenize.COMMENT
    }
    docstrings: set[int] = set()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docstrings.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    code = sum(
        1
        for i, line in enumerate(src.splitlines(), 1)
        if line.strip() and i not in docstrings and not line.strip().startswith("#")
    )
    return code, len(comments), len(docstrings)


def js_counts(src: str) -> tuple[int, int, int]:
    code = comments = blocks = 0
    in_block = False
    for raw in src.splitlines():
        line = raw.strip()
        if not line:
            continue
        if in_block or line.startswith("/*"):
            blocks += 1
            in_block = "*/" not in line
            continue
        if line.startswith("//"):
            comments += 1
            continue
        code += 1
        if "//" in line and not re.search(r"https?://", line):
            comments += 1
    return code, comments, blocks


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    files = subprocess.run(
        ["git", "-C", str(root), "ls-files"], capture_output=True, text=True, check=True
    ).stdout.split()
    rows = []
    for name in files:
        if SKIP.search(name):
            continue
        if name.endswith(".py"):
            counter = python_counts
        elif re.search(r"\.(ts|tsx|js|cjs|mjs)$", name) and not name.endswith(".d.ts"):
            counter = js_counts
        else:
            continue
        try:
            code, comments, docs = counter((root / name).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        if code >= MIN_CODE_LINES:
            rows.append((name, code, comments, docs, (comments + docs) / code))

    rows.sort(key=lambda r: -r[4])
    print(f"{'file':70} {'code':>5} {'cmt':>5} {'doc':>5} {'ratio':>6}")
    for name, code, comments, docs, ratio in rows:
        print(f"{name:70} {code:5} {comments:5} {docs:5} {ratio:6.2f}")
    code, comments, docs = (sum(r[i] for r in rows) for i in (1, 2, 3))
    print(
        f"TOTAL code {code} comment {comments} doc/block {docs} ratio {(comments + docs) / code:.2f}"
    )


if __name__ == "__main__":
    main()
