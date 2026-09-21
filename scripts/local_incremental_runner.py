#!/usr/bin/env python3
"""Unattended local incremental runner for the Obsidian memory projection.

Runs the already existing pipeline stages in order and adds only the
scheduling concerns: raw projection sync, gap detection, a bounded backlog
queue, bounded retries, an overlap lock, stage timeouts, structured logging
and a non-zero failure status.

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


SCHEMA_VERSION = "local-incremental-runner-v2"
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_VAULT_DIR = "/Users/weizhenliang/obsidian空间"
DEFAULT_RAW_REL = "AI/AI外置记忆/00-系统生成/原始记录/liangzai"
DEFAULT_DAILY_REL = "AI/AI外置记忆/01-日报"
DEFAULT_STATUS_REL = "AI/AI外置记忆/90-系统/运行状态/外置记忆运行状态.md"
RUNNER_LABEL = "personal-memory-incremental"
DATE_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
SECRET_KEY_MARKERS = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "APIKEY", "API_KEY", "AUTH")

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
    max_daily_days_per_run: int = 3
    max_attempts: int = 3
    retry_delay: float = 5.0
    stage_timeout: float = 1800.0
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


def secret_values(values: dict[str, str]) -> list[str]:
    """Values whose key looks like a credential, so logs can mask them."""
    found = []
    for key, value in values.items():
        upper = key.upper()
        if any(marker in upper for marker in SECRET_KEY_MARKERS) and value:
            found.append(value)
    return found


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


def plan_run(
    raw_dir: Path, daily_dir: Path, today: date, max_days_per_run: int
) -> dict[str, Any]:
    """Build the backlog plan.

    Every day earlier than today that has raw records but no Daily V2 is a
    candidate: a runner that was down for a week must not lose those gaps
    forever. Only `max_days_per_run` of them are generated per round,
    newest first, so a single round stays bounded.
    """
    raw = dated_days(raw_dir)
    daily = dated_days(daily_dir)
    backlog = sorted(day for day in raw - daily if date.fromisoformat(day) < today)
    newest_first = sorted(backlog, reverse=True)[:max(max_days_per_run, 1)]
    selected = sorted(newest_first)
    pending = sorted(set(backlog) - set(selected))
    return {
        "today": today.isoformat(),
        "raw_days": len(raw),
        "daily_days": len(daily),
        "missing": backlog,
        "selected": selected,
        "pending": pending,
        "max_days_per_run": max(max_days_per_run, 1),
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
        self.secrets: list[str] = []
        if config.env_file is not None and config.env_file.exists():
            self.secrets = secret_values(load_env_file(config.env_file))

    # -- helpers ---------------------------------------------------------
    def redact(self, text: str) -> str:
        for value in self.secrets:
            if len(value) >= 4:
                text = text.replace(value, "***")
        return text

    def log(self, stage: str, outcome: str, **detail: Any) -> None:
        safe_detail = {
            key: self.redact(value) if isinstance(value, str) else value
            for key, value in detail.items()
        }
        record = {
            "schema": SCHEMA_VERSION,
            "ts": datetime.now().astimezone().isoformat(),
            "pid": os.getpid(),
            "stage": stage,
            "outcome": outcome,
        }
        record.update(safe_detail)
        self.records.append(record)
        if self.config.dry_run:
            # Dry-run must not touch the disk: keep records in memory only.
            return
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
                    command, env=env, capture_output=True, text=True,
                    check=False, timeout=self.config.stage_timeout,
                )
            except subprocess.TimeoutExpired:
                last_detail = f"timeout after {self.config.stage_timeout}s"
                self.emit(f"[!] {name} 超时：{last_detail}")
                self.log(name, "timeout", attempt=attempt, detail=last_detail)
                if attempt < self.config.max_attempts:
                    self.sleep(self.config.retry_delay)
                continue
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
                tail = (completed.stderr or completed.stdout or "").strip().splitlines()
                last_detail = tail[-1] if tail else f"exit={completed.returncode}"
                self.emit(f"[!] {name} 失败：{self.redact(last_detail)}")
            self.log(name, "retry", attempt=attempt, detail=last_detail)
            if attempt < self.config.max_attempts:
                self.sleep(self.config.retry_delay)
        self.log(name, "failed", attempts=self.config.max_attempts, detail=last_detail)
        self.emit(f"[✗] {name} 重试 {self.config.max_attempts} 次后仍失败")
        return StageResult(name, "failed", self.config.max_attempts, str(last_detail))

    def emit_plan(self, plan: dict[str, Any]) -> None:
        self.emit(
            f"[→] 计划 {plan['today']}｜原始记录 {plan['raw_days']} 天｜"
            f"日报 {plan['daily_days']} 天｜待补 {len(plan['missing'])} 天｜"
            f"本轮生成 {len(plan['selected'])} 天｜仍待处理 {len(plan['pending'])} 天"
        )
        if plan["selected"]:
            self.emit(f"[→] 本轮生成：{', '.join(plan['selected'])}")
        if plan["pending"]:
            self.emit(f"[=] 仍待处理：{', '.join(plan['pending'])}")

    def make_plan(self, today: date) -> dict[str, Any]:
        return plan_run(
            self.config.raw_dir, self.config.daily_dir, today,
            self.config.max_daily_days_per_run,
        )

    def daily_command_for(self, plan: dict[str, Any]) -> list[str]:
        return self.config.daily_command or build_daily_command(
            self.config.raw_dir, self.config.daily_dir, self.config.work_dir,
            plan["selected"][0], plan["selected"][-1],
        )

    def status_command_for(self) -> list[str]:
        return self.config.status_command or build_status_command(
            self.config.raw_dir, self.config.daily_dir, self.config.work_dir,
            self.config.status_output,
        )

    # -- main ------------------------------------------------------------
    def run(self) -> int:
        config = self.config
        today = config.resolved_today()
        results: list[StageResult] = []
        if config.dry_run:
            # No lock and no writes: only directory names are read to plan.
            self.emit(f"[=] dry-run：只读扫描目录名，不写盘、不调用子命令")
            plan = self.make_plan(today)
            self.emit_plan(plan)
            self.log("plan", "ok", **plan)
            results.append(self.run_stage(
                "sync-raw", config.sync_command or build_sync_command()
            ))
            if plan["selected"]:
                results.append(self.run_stage("daily-v2", self.daily_command_for(plan)))
            else:
                results.append(StageResult("daily-v2", "skipped", detail="no missing dates"))
                self.emit("[=] 没有缺失日报，跳过生成（不调用 LLM）")
                self.log("daily-v2", "skipped", detail="no missing dates")
            results.append(self.run_stage("status-page", self.status_command_for()))
            self.emit("[summary] " + " | ".join(
                f"{item.name}={item.outcome}" for item in results
            ))
            return self.finish(plan, results, "dry-run", EXIT_OK)

        try:
            with acquire_lock(config.lock_path()):
                self.log("lock", "acquired")
                self.emit(f"[→] 增量运行 {today.isoformat()}（时区 {config.timezone}）")
                results.append(self.run_stage(
                    "sync-raw", config.sync_command or build_sync_command()
                ))
                sync_failed = results[-1].outcome == "failed"
                # Re-plan after sync so this round sees records that just arrived.
                plan = self.make_plan(today)
                self.emit_plan(plan)
                self.log("plan", "ok", **plan)
                if sync_failed:
                    # Never write reports from a stale or partial projection.
                    results.append(StageResult(
                        "daily-v2", "skipped", detail="原始记录同步失败，跳过日报生成"
                    ))
                    self.emit("[=] 原始记录同步失败，跳过日报生成以避免基于陈旧数据写入")
                    self.log("daily-v2", "skipped", detail="sync failed")
                elif plan["selected"]:
                    results.append(self.run_stage("daily-v2", self.daily_command_for(plan)))
                else:
                    results.append(StageResult(
                        "daily-v2", "skipped", detail="no missing dates"
                    ))
                    self.emit("[=] 没有缺失日报，跳过生成（不调用 LLM）")
                    self.log("daily-v2", "skipped", detail="no missing dates")
                results.append(self.run_stage("status-page", self.status_command_for()))
        except LockUnavailable as exc:
            self.emit(f"[=] 已有运行实例持有锁，本轮跳过：{exc}")
            self.log("lock", "skipped", detail=str(exc))
            return self.finish(
                {"today": today.isoformat(), "missing": [], "selected": [], "pending": []},
                [], "skipped", EXIT_OK,
            )

        failed = [item for item in results if item.outcome == "failed"]
        outcome = "failed" if failed else "ok"
        self.emit("[summary] " + " | ".join(
            f"{item.name}={item.outcome}" for item in results
        ))
        return self.finish(plan, results, outcome, EXIT_FAILED if failed else EXIT_OK)

    def finish(
        self, plan: dict[str, Any], results: list[StageResult], outcome: str, code: int
    ) -> int:
        if self.config.dry_run:
            self.log("run", outcome)
            return code
        state_dir = self.config.state_dir or default_state_dir()
        state_dir.mkdir(parents=True, exist_ok=True)
        last_run_path = state_dir / "last-run.json"
        last_success_at = None
        if last_run_path.exists():
            try:
                previous = json.loads(last_run_path.read_text(encoding="utf-8"))
                last_success_at = previous.get("last_success_at")
            except (OSError, json.JSONDecodeError):
                last_success_at = None
        finished_at = datetime.now().astimezone().isoformat()
        if outcome == "ok":
            last_success_at = finished_at
        payload = {
            "schema": SCHEMA_VERSION,
            "finished_at": finished_at,
            "last_success_at": last_success_at,
            "outcome": outcome,
            "plan": plan,
            "stages": [
                {"name": item.name, "outcome": item.outcome, "attempts": item.attempts,
                 "detail": item.detail}
                for item in results
            ],
        }
        last_run_path.write_text(
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
        plan = payload.get("plan", {})
        lines.extend([
            f"- 上次运行：{payload.get('finished_at', '未知')}",
            f"- 上次成功：{payload.get('last_success_at') or '尚无'}",
            f"- 结果：{payload.get('outcome', '未知')}",
            f"- 原始记录天数：{plan.get('raw_days', '未知')}",
            f"- 本轮生成：{', '.join(plan.get('selected', [])) or '无'}",
            f"- 仍待处理：{', '.join(plan.get('pending', [])) or '无'}",
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
    parser.add_argument("--timezone", default=None,
                        help=f"固定为 {DEFAULT_TIMEZONE}，除非显式覆盖")
    parser.add_argument("--today", default=None,
                        help="ISO date; overrides the clock, for deterministic runs")
    parser.add_argument("--max-daily-days-per-run", type=int, default=None)
    parser.add_argument("--max-attempts", type=int, default=None)
    parser.add_argument("--retry-delay", type=float, default=None)
    parser.add_argument("--stage-timeout", type=float, default=None)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--log-file", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sync-command", help="override the raw sync command")
    parser.add_argument("--daily-command", help="override the daily generation command")
    parser.add_argument("--status-command", help="override the status page command")
    return parser


def _pick(cli_value, key, file_values, cast, default):
    """CLI argument > env file > process environment > default."""
    if cli_value is not None:
        return cli_value
    if file_values.get(key):
        return cast(file_values[key])
    if os.environ.get(key):
        return cast(os.environ[key])
    return default


def config_from_args(args: argparse.Namespace) -> RunnerConfig:
    env_file = _pick(args.env_file, "PERSONAL_MEMORY_RUNNER_ENV_FILE", {}, Path, None)
    file_values: dict[str, str] = {}
    if env_file is not None and env_file.exists():
        file_values = load_env_file(env_file)
    vault = _pick(
        args.vault_dir, "PERSONAL_MEMORY_VAULT_DIR", file_values, Path,
        Path(DEFAULT_VAULT_DIR),
    )
    raw_dir = _pick(
        args.raw_dir, "PERSONAL_MEMORY_RAW_DIR", file_values, Path,
        vault / DEFAULT_RAW_REL,
    )
    daily_dir = _pick(
        args.daily_dir, "PERSONAL_MEMORY_DAILY_DIR", file_values, Path,
        vault / DEFAULT_DAILY_REL,
    )
    status_output = _pick(
        args.status_output, "PERSONAL_MEMORY_STATUS_OUTPUT", file_values, Path,
        vault / DEFAULT_STATUS_REL,
    )
    today = date.fromisoformat(args.today) if args.today else None
    return RunnerConfig(
        raw_dir=raw_dir,
        daily_dir=daily_dir,
        status_output=status_output,
        work_dir=args.work_dir,
        timezone=_pick(args.timezone, "PERSONAL_MEMORY_TIMEZONE", file_values, str,
                       DEFAULT_TIMEZONE),
        today=today,
        max_daily_days_per_run=_pick(
            args.max_daily_days_per_run, "PERSONAL_MEMORY_MAX_DAILY_DAYS_PER_RUN",
            file_values, int, 3,
        ),
        max_attempts=_pick(
            args.max_attempts, "PERSONAL_MEMORY_MAX_ATTEMPTS", file_values, int, 3
        ),
        retry_delay=_pick(
            args.retry_delay, "PERSONAL_MEMORY_RETRY_DELAY", file_values, float, 5.0
        ),
        stage_timeout=_pick(
            args.stage_timeout, "PERSONAL_MEMORY_STAGE_TIMEOUT", file_values, float, 1800.0
        ),
        dry_run=args.dry_run,
        log_file=_pick(args.log_file, "PERSONAL_MEMORY_RUNNER_LOG_FILE", file_values,
                       Path, None),
        state_dir=_pick(args.state_dir, "PERSONAL_MEMORY_RUNNER_STATE_DIR", file_values,
                        Path, None),
        env_file=env_file,
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
