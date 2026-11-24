"""scripts/secret_scan.py 單元測試（以 tmp_path 假 repo 驗證，原始碼不含完整假金鑰）。"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "secret_scan.py"


def _init_git_repo(repo_dir: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )


def _run_scan(repo_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--repo", str(repo_dir)],
        capture_output=True,
        text=True,
    )


def test_clean_repo_and_gha_secrets_exit_zero(tmp_path):
    _init_git_repo(tmp_path)

    (tmp_path / "app.py").write_text("print('hello world')\n", encoding="utf-8")
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "daily.yml").write_text(
        "env:\n"
        "  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}\n"
        "  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}\n"
        "run: |\n"
        "  curl -H \"Authorization: Bearer ${{ secrets.LINE_TOKEN }}\" https://example.com\n",
        encoding="utf-8",
    )
    # 排除 PDF / PNG 二進位檔（即使內含超長 base64 樣式位元組）
    (tmp_path / "sample.pdf").write_bytes(b"%PDF-1.4\n" + b"A" * 160 + b"\n")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"B" * 160)

    subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)

    res = _run_scan(tmp_path)
    assert res.returncode == 0
    assert res.stdout.strip() == ""


@pytest.mark.parametrize(
    "case_name,secret_factory,expected_rule",
    [
        (
            "anthropic",
            lambda: "sk" + "-ant-" + "api03-" + "AbCdEf0123456789" * 2,
            "anthropic_api_key",
        ),
        (
            "openai",
            lambda: "sk" + "-" + "proj-" + "ZyXwVu9876543210" * 2,
            "openai_api_key",
        ),
        (
            "bearer",
            lambda: "Authorization: " + "Bearer " + "TokEnValue1234567890abcd",
            "authorization_bearer",
        ),
        (
            "aws",
            lambda: "AK" + "IA" + "0123456789ABCDEF",
            "aws_access_key",
        ),
        (
            "line_token",
            lambda: ("AbCdEfGh01" * 11) + "==",
            "line_long_token",
        ),
        (
            "env_assign",
            lambda: "ANTHROPIC_API_KEY" + "=" + "literal_secret_value_999",
            "env_secret_assignment",
        ),
    ],
)
def test_planted_secret_exits_one_without_leaking_value(
    tmp_path, case_name, secret_factory, expected_rule
):
    _init_git_repo(tmp_path)

    secret_val = secret_factory()
    target = tmp_path / f"leaked_{case_name}.txt"
    target.write_text(f"line1 ok\n{secret_val}\nline3 ok\n", encoding="utf-8")

    # 測試 staged（git add 但尚未 commit）即可被掃到
    subprocess.run(
        ["git", "add", target.name],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )

    res = _run_scan(tmp_path)
    assert res.returncode == 1
    assert f"{target.name}:2:{expected_rule}" in res.stdout
    # 輸出絕不可包含命中內容本身
    assert secret_val not in res.stdout
    assert secret_val not in res.stderr
