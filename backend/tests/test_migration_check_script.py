import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("scenario", "allowed", "expected_code", "expected_output"),
    [
        ("clean", 0, 0, "ok   drift 0 operations (baseline 0)"),
        ("drift", 2, 0, "ok   drift 2 operations (baseline 2)"),
        ("drift", 1, 1, "FAIL: model/migration drift grew: 2 operations"),
        ("global-heads", 0, 1, "FAIL: expected 1 global alembic head, found 2"),
        ("project-heads", 0, 1, "FAIL: expected 1 project alembic head, found 2"),
        ("global-error", 0, 1, "FAIL: global alembic check failed"),
        ("project-error", 0, 1, "FAIL: project alembic check failed"),
        ("upgrade-error", 0, 1, "migration failed"),
    ],
)
def test_migration_check_script(tmp_path, scenario, allowed, expected_code, expected_output):
    bash = shutil.which("bash")
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if os.name == "nt" and git_bash.is_file():
        bash = str(git_bash)
    if bash is None:
        raise RuntimeError("Bash is required to exercise the migration check script")

    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    (backend_dir / ".alembic-drift-baseline").write_text(str(allowed), encoding="utf-8")
    command_log = tmp_path / "commands.log"
    script = Path(__file__).resolve().parents[2] / "scripts" / "migration_check.sh"
    harness = r"""
git() { printf '%s\n' "$CHECK_ROOT"; }
uv() {
    printf '%s\n' "$*" >> "$CHECK_LOG"
    [ "$1 $2 $3 $4" = 'run --quiet alembic -c' ] || return 99
    case "$5" in
        global-alembic.ini) history=global ;;
        project-alembic.ini) history=project ;;
        *) return 99 ;;
    esac
    case "$6" in
        heads)
            echo 'revision (head)'
            if [ "$CHECK_SCENARIO" = "$history-heads" ]; then echo 'other (head)'; fi
            ;;
        upgrade)
            if [ "$CHECK_SCENARIO" = upgrade-error ]; then
                echo 'migration failed' >&2
                return 1
            fi
            ;;
        check)
            if [ "$CHECK_SCENARIO" = "$history-error" ]; then
                echo 'database unavailable' >&2
                return 1
            fi
            if [ "$CHECK_SCENARIO" = drift ]; then
                echo "New upgrade operations detected: [('add_table', 'unexpected')]"
                return 1
            fi
            echo 'No new upgrade operations detected.'
            ;;
        downgrade) ;;
        *) return 99 ;;
    esac
    return 0
}
export -f git uv
bash "$CHECK_SCRIPT"
"""
    result = subprocess.run(
        [bash, "-c", harness],
        env={
            **os.environ,
            "CHECK_ROOT": tmp_path.as_posix(),
            "CHECK_LOG": command_log.as_posix(),
            "CHECK_SCRIPT": script.as_posix(),
            "CHECK_SCENARIO": scenario,
            "CEDARS_DATABASE_URL": "postgresql+asyncpg://unused/unused",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_code, result.stdout + result.stderr
    assert expected_output in result.stdout + result.stderr
    if expected_code == 0:
        assert command_log.read_text(encoding="utf-8").splitlines() == [
            f"run --quiet alembic -c {history}-alembic.ini {operation}"
            for history in ("global", "project")
            for operation in (
                "heads",
                "upgrade head",
                "downgrade -1",
                "upgrade head",
                "check",
                "downgrade base",
            )
        ]
