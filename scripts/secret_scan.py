#!/usr/bin/env python3
"""掃描 git tracked 與 staged 檔案中是否混入疑似金鑰或長 token（純標準庫）。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

BINARY_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".webp",
    ".ico",
    ".ttf",
    ".ttc",
    ".otf",
    ".woff",
    ".woff2",
    ".zip",
    ".gz",
    ".tar",
    ".bz2",
    ".xz",
    ".7z",
    ".pyc",
    ".pyo",
    ".so",
    ".dylib",
    ".dll",
    ".exe",
}

# GitHub Actions secret 引用（例如 ${{ secrets.ANTHROPIC_API_KEY }}）不視為命中
_GHA_SECRET_REF = re.compile(r"\$\{\{\s*secrets\.[A-Za-z0-9_]+\s*\}\}")

# 規則皆以「前綴字串＋最小長度」定義；原始碼中不含任何真實或完整樣式金鑰
RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "anthropic_api_key",
        re.compile(r"sk" + r"-ant-" + r"[A-Za-z0-9_-]{20,}"),
    ),
    (
        "openai_api_key",
        re.compile(r"\bsk" + r"-(?!ant-)[A-Za-z0-9_-]{20,}"),
    ),
    (
        "authorization_bearer",
        re.compile(
            r"Authorization\s*:\s*Bearer\s+[A-Za-z0-9._\-+/=]{20,}",
            re.IGNORECASE,
        ),
    ),
    (
        "aws_access_key",
        re.compile(r"\bAK" + r"IA[0-9A-Z]{16}\b"),
    ),
    (
        "line_long_token",
        re.compile(
            r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/]{100,}={0,2}(?![A-Za-z0-9+/=_-])"
        ),
    ),
    (
        "env_secret_assignment",
        re.compile(
            r"\b(?:ANTHROPIC_API_KEY|OPENAI_API_KEY|LINE_TOKEN)"
            r"\s*=\s*['\"]?(?!\$)[^\s'\"#]{10,}"
        ),
    ),
]


def _is_binary_path(rel_path: str) -> bool:
    return Path(rel_path).suffix.lower() in BINARY_EXTENSIONS


def _is_binary_bytes(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def _git_output(repo_dir: Path, args: list[str]) -> bytes:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )
    return proc.stdout


def _scan_text(rel_path: str, text: str) -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        sanitized = _GHA_SECRET_REF.sub("", raw_line)
        for rule_name, pattern in RULES:
            if pattern.search(sanitized):
                findings.append((rel_path, lineno, rule_name))
    return findings


def scan_repo(repo_dir: Path) -> list[tuple[str, int, str]]:
    """掃描指定 git repo 的 tracked 檔案與 staged 檔案內容。"""
    tracked_raw = _git_output(repo_dir, ["ls-files", "-z"])
    tracked_files = [
        p for p in tracked_raw.decode("utf-8", errors="surrogateescape").split("\0") if p
    ]

    staged_raw = _git_output(
        repo_dir, ["diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"]
    )
    staged_files = [
        p for p in staged_raw.decode("utf-8", errors="surrogateescape").split("\0") if p
    ]

    seen: set[tuple[str, int, str]] = set()
    ordered_findings: list[tuple[str, int, str]] = []

    def _record(items: list[tuple[str, int, str]]) -> None:
        for item in items:
            if item not in seen:
                seen.add(item)
                ordered_findings.append(item)

    # 1. 掃描 staged blob（包含剛 git add 但尚未 commit 的檔案與已暫存修改）
    for rel_path in staged_files:
        if _is_binary_path(rel_path):
            continue
        try:
            data = _git_output(repo_dir, ["show", f":{rel_path}"])
        except subprocess.CalledProcessError:
            continue
        if _is_binary_bytes(data):
            continue
        text = data.decode("utf-8", errors="replace")
        _record(_scan_text(rel_path, text))

    # 2. 掃描 git ls-files 的工作樹檔案
    for rel_path in tracked_files:
        if _is_binary_path(rel_path):
            continue
        full_path = repo_dir / rel_path
        if not full_path.is_file():
            continue
        try:
            data = full_path.read_bytes()
        except OSError:
            continue
        if _is_binary_bytes(data):
            continue
        text = data.decode("utf-8", errors="replace")
        _record(_scan_text(rel_path, text))

    return ordered_findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan git tracked & staged files for secrets.")
    parser.add_argument(
        "--repo",
        default=os.getcwd(),
        help="Git repository root directory (default: current working directory)",
    )
    args = parser.parse_args(argv)
    repo_dir = Path(args.repo).resolve()

    findings = scan_repo(repo_dir)
    for rel_path, lineno, rule_name in findings:
        # 只印出檔名:行號:規則名，絕不印出命中內容
        print(f"{rel_path}:{lineno}:{rule_name}")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
