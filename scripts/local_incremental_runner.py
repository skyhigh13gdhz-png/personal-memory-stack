#!/usr/bin/env python3
"""Unattended local incremental runner for the Obsidian memory projection.

Runs the already existing pipeline stages in order and adds only the
scheduling concerns: raw projection sync, gap detection, bounded retries,
an overlap lock, structured logging and a non-zero failure status.

It never reimplements what `sync_obsidian_vault.sh`, `sync_daily_v2.py` and
`render_generation_status.py` already do -- it calls them.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator

try:  # pragma: no cover - depends on the host tz database
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


SCHEMA_VERSION = "local-incremental-runner-v1"
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_VAULT_DIR = "/Users/weizhenliang/obsidian空间"
DEFAULT_RAW_REL = "AI/AI外置记忆/00-系统生成/原始记录/liangzai"
DEFAULT_DAILY_REL = "AI/AI外置记忆/01-日报"
DEFAULT_STATUS_REL = "AI/AI外置记忆/00-系统生成/运行状态.md"
RUNNER_LABEL = "personal-memory-incremental"
DATE_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")

SCRIPT_DIR = Path(__file__).resolve().parent
EXIT_OK = 0
EXIT_FAILED = 2


class LockUnavailable(Exception):
    """Another runner instance already holds the overlap lock."""


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------


@dataclass
class RunnerConfig:
    raw_dir: Path
    daily_dir: Path
    status_output: Path
    work_dir: Path | None = None
    timezone: str = DEFAULT_TIMEZONE
    today: date | None = None
    backfill_days: int = 7
    max_attempts: int = 3
    retry_delay: float = 5.0
    dry_run: bool = False
    log_file: Path | None = None
    state_dir: Path | None = None
    env_file: Path | None = None
    sync_command: list[str] | None = None
    daily_command: list[str] | None = None
    status_command: list[str] | None = None
    extra_env: dict[str, str] = field(default_factory=dict)

    def resolved_today(self) -> date:
        if self.today is not None:
            return self.today
        return current_date(self.timezone)

    def lock_path(self) -> Path:
        root = self.state_dir or default_state_dir()
        return root / "runner.lock"

    def last_run_path(self) -> Path:
        root = self.state_dir or default_state_dir()
        return root / "last-run.json"


def default_state_dir() -> Path:
    configured = os.environ.get("PERSONAL_MEMORY_RUNNER_STATE_DIR")
    if configured:
        return Path(configured)
    return Path.home() / "Library/Application Support" / RUNNER_LABEL


def default_log_file() -> Path:
    configured = os.environ.get("PERSONAL_MEMORY_RUNNER_LOG_FILE")
    if configured:
        return Path(configured)
    return Path.home() / "Library/Logs" / RUNNER_LABEL / "runner.jsonl"


def current_date(timezone: str) -> date:
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo(timezone)).date()
    # Fixed +08:00 fallback when the host has no tz database.
    return (datetime.utcnow() + timedelta(hours=8)).date()


def load_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines. Values are never logged or persisted."""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def env_file_permission_warning(path: Path) -> str | None:
    try:
        mode = path.stat().st_mode
    except OSError:
        return None
    if mode & 0o077:
        return "env file is readable by group or others; chmod 600 recommended"
    return None


# --------------------------------------------------------------------------
# planning
# --------------------------------------------------------------------------


def dated_days(directory: Path) -> set[str]:
    if not directory.exists():
        return set()
    days = set()
    for path in directory.glob("*.md"):
        if not DATE_FILE.match(path.name):
            continue
        try:
            date.fromisoformat(path.stem)
        except ValueError:
            continue
        days.add(path.stem)
    return days


def plan_window(today: date, backfill_days: int) -> tuple[date, date]:
    """Backfill window: yesterday at the newest, N days back at the oldest.

    Today is deliberately excluded: its raw records are still arriving, so a
    report written now would be rewritten later.
    """
    newest = today - timedelta(days=1)
    oldest = today - timedelta(days=max(backfill_days, 1))
    return oldest, newest


def plan_run(raw_dir: Path, daily_dir: Path, today: date, backfill_days: int) -> dict[str, Any]:
    raw = dated_days(raw_dir)
    daily = dated_days(daily_dir)
    oldest, newest = plan_window(today, backfill_days)
    missing = sorted(
        day for day in raw - daily
        if oldest <= date.fromisoformat(day) <= newest
    )
    return {
        "raw_days": len(raw),
        "daily_days": len(daily),
        "window_start": oldest.isoformat(),
        "window_end": newest.isoformat(),
        "missing": missing,
        "today": today.isoformat(),
    }


def build_daily_command(
    raw_dir: Path, daily_dir: Path, work_dir: Path | None, start: str, end: str
) -> list[str]:
    command = [
        sys.executable,
        str(SCRIPT_DIR / "sync_daily_v2.py"),
        "--raw-dir", str(raw_dir),
        "--output-dir", str(daily_dir),
        "--date-from", start,
        "--date-to", end,
    ]
    if work_dir is not None:
        command += ["--work-dir", str(work_dir)]
    return command


def build_status_command(
    raw_dir: Path, daily_dir: Path, work_dir: Path | None, output: Path
) -> list[str]:
    command = [
        sys.executable,
        str(SCRIPT_DIR / "render_generation_status.py"),
        "--raw-dir", str(raw_dir),
        "--daily-dir", str(daily_dir),
        "--output", str(output),
    ]
    if work_dir is not None:
        command += ["--work-dir", str(work_dir)]
    return command


def build_sync_command() -> list[str]:
    return ["bash", str(SCRIPT_DIR / "sync_obsidian_vault.sh")]


# --------------------------------------------------------------------------
# lock and logging
# --------------------------------------------------------------------------


@contextlib.contextmanager
def acquire_lock(path: Path) -> Iterator[int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise LockUnavailable(str(path))
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
        yield fd
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@dataclass
class StageResult:
    name: str
    outcome: str  # ok | failed | skipped | dry-run
    attempts: int = 0
    detail: str = ""


class Runner:
    def __init__(
        self,
        config: RunnerConfig,
        emit: Callable[[str], None] = print,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.emit = emit
        self.sleep = sleep
        self.log_file = config.log_file or default_log_file()
        self.records: list[dict[str, Any]] = []

    # -- helpers ---------------------------------------------------------
    def log(self, stage: str, outcome: str, **detail: Any) -> None:
        record = {
            "schema": SCHEMA_VERSION,
            "ts": datetime.now().astimezone().isoformat(),
            "pid": os.getpid(),
            "stage": stage,
            "outcome": outcome,
        }
        record.update(detail)
        self.records.append(record)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with self.log_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def child_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(self.config.extra_env)
        if self.config.env_file is not None and self.config.env_file.exists():
            env.update(load_env_file(self.config.env_file))
        return env

    def run_stage(self, name: str, command: list[str]) -> StageResult:
        if self.config.dry_run:
            self.emit(f"[dry-run] 将执行 {name}: {shlex.join(command)}")
            self.log(name, "dry-run", command=command)
            return StageResult(name, "dry-run")
        env = self.child_env()
        last_detail = ""
        for attempt in range(1, self.config.max_attempts + 1):
            self.emit(f"[→] {name}（第 {attempt}/{self.config.max_attempts} 次）")
            try:
                completed = subprocess.run(
                    command, env=env, capture_output=True, text=True, check=False
                )
            except OSError as exc:
                completed = None
                last_detail = f"{type(exc).__name__}: {exc}"
            if completed is not None and completed.returncode == 0:
                for line in completed.stdout.strip().splitlines():
                    self.emit(f"    {line}")
                self.log(name, "ok", attempt=attempt)
                self.emit(f"[✓] {name} 完成")
                return StageResult(name, "ok", attempt)
            if completed is not None:
                last_detail = (completed.stderr or completed.stdout or "").strip().splitlines()
                last_detail = last_detail[-1] if last_detail else f"exit={completed.returncode}"
                self.emit(f"[!] {name} 失败：{last_detail}", )
            self.log(name, "retry", attempt=attempt, detail=last_detail)
            if attempt < self.config.max_attempts:
                self.sleep(self.config.retry_delay)
        self.log(name, "failed", attempts=self.config.max_attempts, detail=last_detail)
        self.emit(f"[✗] {name} 重试 {self.config.max_attempts} 次后仍失败")
        return StageResult(name, "failed", self.config.max_attempts, str(last_detail))

    # -- main ------------------------------------------------------------
    def run(self) -> int:
        config = self.config
        today = config.resolved_today()
        plan = plan_run(config.raw_dir, config.daily_dir, today, config.backfill_days)
        self.emit(
            f"[→] 增量运行 {today.isoformat()}｜原始记录 {plan['raw_days']} 天｜"
            f"日报 {plan['daily_days']} 天｜窗口 {plan['window_start']}~{plan['window_end']}"
        )
        self.log("plan", "ok", **plan)

        results: list[StageResult] = []
        try:
            with acquire_lock(config.lock_path()):
                self.log("lock", "acquired")
                results.append(self.run_stage(
                    "sync-raw", config.sync_command or build_sync_command()
                ))
                if results[-1].outcome == "failed":
                    results.append(StageResult(
                        "daily-v2", "skipped", detail="原始记录同步失败，跳过日报生成"
                    ))
                    self.emit("[=] 原始记录同步失败，跳过日报生成以避免基于陈旧数据写入")
                    self.log("daily-v2", "skipped", detail="sync failed")
                elif plan["missing"]:
                    start, end = plan["missing"][0], plan["missing"][-1]
                    results.append(self.run_stage(
                        "daily-v2",
                        config.daily_command or build_daily_command(
                            config.raw_dir, config.daily_dir, config.work_dir, start, end
                        ),
                    ))
                else:
                    # No gaps inside the window: never touch the LLM path.
                    results.append(StageResult("daily-v2", "skipped", detail="no missing dates"))
                    self.emit("[=] 窗口内无缺失日报，跳过生成（不调用 LLM）")
                    self.log("daily-v2", "skipped", detail="no missing dates")
                results.append(self.run_stage(
                    "status-page",
                    config.status_command or build_status_command(
                        config.raw_dir, config.daily_dir, config.work_dir, config.status_output
                    ),
                ))
        except LockUnavailable as exc:
            self.emit(f"[=] 已有运行实例持有锁，本轮跳过：{exc}")
            self.log("lock", "skipped", detail=str(exc))
            return self.finish(plan, [], "skipped", EXIT_OK)

        failed = [item for item in results if item.outcome == "failed"]
        outcome = "failed" if failed else ("dry-run" if config.dry_run else "ok")
        self.emit(
            "[summary] " + " | ".join(f"{item.name}={item.outcome}" for item in results)
        )
        return self.finish(plan, results, outcome, EXIT_FAILED if failed else EXIT_OK)

    def finish(
        self, plan: dict[str, Any], results: list[StageResult], outcome: str, code: int
    ) -> int:
        payload = {
            "schema": SCHEMA_VERSION,
            "finished_at": datetime.now().astimezone().isoformat(),
            "outcome": outcome,
            "plan": plan,
            "stages": [
                {"name": item.name, "outcome": item.outcome, "attempts": item.attempts,
                 "detail": item.detail}
                for item in results
            ],
        }
        state_dir = self.config.state_dir or default_state_dir()
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "last-run.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        self.log("run", outcome)
        return code


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def render_status(config: RunnerConfig) -> str:
    state_path = (config.state_dir or default_state_dir()) / "last-run.json"
    lines = [f"# {RUNNER_LABEL} 运行状态", ""]
    if not state_path.exists():
        lines.append("- 尚无运行记录。")
    else:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        lines.extend([
            f"- 上次运行：{payload.get('finished_at', '未知')}",
            f"- 结果：{payload.get('outcome', '未知')}",
            f"- 原始记录天数：{payload.get('plan', {}).get('raw_days', '未知')}",
            f"- 缺失日报：{', '.join(payload.get('plan', {}).get('missing', [])) or '无'}",
            "",
            "## 阶段",
            "",
        ])
        for stage in payload.get("stages", []):
            extra = f"（{stage['attempts']} 次尝试）" if stage.get("attempts") else ""
            lines.append(f"- {stage['name']}：{stage['outcome']}{extra}")
    lock_path = config.lock_path()
    running = False
    if lock_path.exists():
        try:
            with acquire_lock(lock_path):
                pass
        except LockUnavailable:
            running = True
    lines.extend(["", f"- 当前是否有实例在跑：{'是' if running else '否'}", ""])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["run", "status"], nargs="?", default="run")
    parser.add_argument("--vault-dir", type=Path, default=None)
    parser.add_argument("--raw-dir", type=Path, default=None)
    parser.add_argument("--daily-dir", type=Path, default=None)
    parser.add_argument("--status-output", type=Path, default=None)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--today", help="ISO date; overrides the clock, for deterministic runs")
    parser.add_argument(
        "--backfill-days", type=int,
        default=int(os.environ.get("PERSONAL_MEMORY_BACKFILL_DAYS", "7")),
    )
    parser.add_argument(
        "--max-attempts", type=int,
        default=int(os.environ.get("PERSONAL_MEMORY_MAX_ATTEMPTS", "3")),
    )
    parser.add_argument(
        "--retry-delay", type=float,
        default=float(os.environ.get("PERSONAL_MEMORY_RETRY_DELAY", "5.0")),
    )
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--log-file", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sync-command", help="override the raw sync command")
    parser.add_argument("--daily-command", help="override the daily generation command")
    parser.add_argument("--status-command", help="override the status page command")
    return parser


def config_from_args(args: argparse.Namespace) -> RunnerConfig:
    vault = args.vault_dir or Path(
        os.environ.get("PERSONAL_MEMORY_VAULT_DIR", DEFAULT_VAULT_DIR)
    )
    raw_dir = args.raw_dir or Path(
        os.environ.get("PERSONAL_MEMORY_RAW_DIR", str(vault / DEFAULT_RAW_REL))
    )
    daily_dir = args.daily_dir or Path(
        os.environ.get("PERSONAL_MEMORY_DAILY_DIR", str(vault / DEFAULT_DAILY_REL))
    )
    status_output = args.status_output or Path(
        os.environ.get("PERSONAL_MEMORY_STATUS_OUTPUT", str(vault / DEFAULT_STATUS_REL))
    )
    today = date.fromisoformat(args.today) if args.today else None
    return RunnerConfig(
        raw_dir=raw_dir,
        daily_dir=daily_dir,
        status_output=status_output,
        work_dir=args.work_dir,
        timezone=args.timezone,
        today=today,
        backfill_days=args.backfill_days,
        max_attempts=args.max_attempts,
        retry_delay=args.retry_delay,
        dry_run=args.dry_run,
        log_file=args.log_file,
        state_dir=args.state_dir,
        env_file=args.env_file,
        sync_command=shlex.split(args.sync_command) if args.sync_command else None,
        daily_command=shlex.split(args.daily_command) if args.daily_command else None,
        status_command=shlex.split(args.status_command) if args.status_command else None,
    )


def main() -> int:
    args = build_parser().parse_args()
    config = config_from_args(args)
    if args.action == "status":
        print(render_status(config))
        return EXIT_OK
    if config.env_file is not None and config.env_file.exists():
        warning = env_file_permission_warning(config.env_file)
        if warning:
            print(f"[!] {warning}")
    runner = Runner(config)
    try:
        return runner.run()
    except Exception as exc:  # noqa: BLE001
        print(f"LOCAL_INCREMENTAL_RUNNER_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_FAILED)


if __name__ == "__main__":
    raise SystemExit(main())
