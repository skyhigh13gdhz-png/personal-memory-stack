#!/usr/bin/env python3
"""Unattended local incremental runner for the Obsidian memory projection.

Runs the already existing pipeline stages in order and adds only the
scheduling concerns: raw projection sync, gap detection, a bounded backlog
queue, bounded retries, an overlap lock, stage timeouts, structured logging
and a non-zero failure status.

It never reimplements what `sync_obsidian_vault.sh`, `sync_daily_v2.py` and
`render_generation_status.py` already do -- it calls them.

One resolved Vault/path configuration is shared by the parent process and
every child stage, stage timeouts terminate whole process groups, and every
byte the runner shows or persists goes through the same redactor.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping

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
DAILY_SOURCE_HASH = re.compile(r"<!-- daily-v2-source-sha256:([0-9a-f]{64}) -->")
SECRET_KEY_MARKERS = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "APIKEY", "API_KEY", "AUTH")
# Names that match a marker but never carry a credential.
SECRET_KEY_EXCLUSIONS = ("SSH_AUTH_SOCK", "GIT_ASKPASS", "SSH_ASKPASS")
MIN_SECRET_LENGTH = 4
# How long a timed-out stage group may live after SIGTERM before SIGKILL.
TIMEOUT_GRACE_SECONDS = 5.0
# How long to wait for the direct child to exit before the SIGKILL sweep.
TERMINATION_WAIT_SECONDS = 2.0
TERMINATION_POLL_SECONDS = 0.05

SCRIPT_DIR = Path(__file__).resolve().parent
EXIT_OK = 0
EXIT_FAILED = 2


class LockUnavailable(Exception):
    """Another runner instance already holds the overlap lock."""


class ConfigError(Exception):
    """The resolved configuration cannot be run safely."""


class StageTimeout(Exception):
    """A stage exceeded its timeout and its process group was terminated."""

    def __init__(self, timeout: float, stdout: str = "", stderr: str = "") -> None:
        super().__init__(f"timeout after {timeout:g}s")
        self.timeout = timeout
        self.stdout = stdout
        self.stderr = stderr


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------


@dataclass
class RunnerConfig:
    raw_dir: Path
    daily_dir: Path
    status_output: Path
    # The single resolved Vault, also handed to the sync child stage.
    vault_dir: Path | None = None
    target_rel: str | None = None
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

    def resolved_vault_dir(self) -> Path | None:
        """The one Vault both this process and the sync child stage use."""
        if self.vault_dir is not None:
            return self.vault_dir
        # Fall back to reversing the default projection layout, so callers
        # that build the config directly still hand the child a Vault.
        return infer_vault_dir(self.raw_dir)

    def resolved_target_rel(self, vault: Path) -> str:
        """Projection target relative to `vault`, as the sync stage expects."""
        if self.target_rel:
            return self.target_rel
        try:
            return self.raw_dir.relative_to(vault).as_posix()
        except ValueError:
            return DEFAULT_RAW_REL


def validate_config(config: RunnerConfig) -> None:
    """Reject values that would otherwise fail in a confusing way."""
    problems: list[str] = []
    if config.max_attempts < 1:
        problems.append("max_attempts 必须 >= 1")
    if config.max_daily_days_per_run < 1:
        problems.append("max_daily_days_per_run 必须 >= 1")
    if config.retry_delay < 0:
        problems.append("retry_delay 必须 >= 0")
    if config.stage_timeout <= 0:
        problems.append("stage_timeout 必须 > 0")
    if problems:
        raise ConfigError("；".join(problems))


def infer_vault_dir(raw_dir: Path) -> Path | None:
    """Recover a Vault root when raw_dir uses the standard managed suffix."""
    suffix = Path(DEFAULT_RAW_REL).parts
    parts = raw_dir.parts
    if len(parts) > len(suffix) and tuple(parts[-len(suffix):]) == suffix:
        return Path(*parts[: -len(suffix)])
    return None


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


def looks_secret(key: str) -> bool:
    upper = key.upper()
    if upper in SECRET_KEY_EXCLUSIONS:
        return False
    return any(marker in upper for marker in SECRET_KEY_MARKERS)


def secret_values(values: Mapping[str, str]) -> list[str]:
    """Values whose key looks like a credential, so logs can mask them."""
    return [value for key, value in values.items() if value and looks_secret(key)]


def env_file_permission_warning(path: Path) -> str | None:
    try:
        mode = path.stat().st_mode
    except OSError:
        return None
    if mode & 0o077:
        return "env file is readable by group or others; chmod 600 recommended"
    return None


class Redactor:
    """One redactor for console output, JSONL records and persisted state."""

    def __init__(self, values: Iterable[str] = ()) -> None:
        self._secrets: list[str] = []
        self.absorb(values)

    def absorb(self, values: Iterable[str]) -> None:
        for value in values:
            if not value or len(value) < MIN_SECRET_LENGTH:
                continue
            if value not in self._secrets:
                self._secrets.append(value)

    def __call__(self, text: str) -> str:
        for value in self._secrets:
            text = text.replace(value, "***")
        return text


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


def stale_daily_days(raw_dir: Path, daily_dir: Path) -> set[str]:
    """Return notes whose recorded source digest no longer matches raw data.

    Legacy notes without a marker are treated as an accepted baseline. Newly
    generated notes always carry the marker, so later Document patches trigger
    regeneration without rewriting the entire historical archive at rollout.
    """
    stale: set[str] = set()
    for daily_path in daily_dir.glob("????-??-??.md") if daily_dir.exists() else ():
        raw_path = raw_dir / daily_path.name
        if not raw_path.exists():
            continue
        match = DAILY_SOURCE_HASH.search(daily_path.read_text(encoding="utf-8"))
        if match and hashlib.sha256(raw_path.read_bytes()).hexdigest() != match.group(1):
            stale.add(daily_path.stem)
    return stale


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
    missing = sorted(day for day in raw - daily if date.fromisoformat(day) < today)
    stale = sorted(day for day in stale_daily_days(raw_dir, daily_dir) if date.fromisoformat(day) < today)
    backlog = sorted(set(missing) | set(stale))
    newest_first = sorted(backlog, reverse=True)[:max(max_days_per_run, 1)]
    selected = sorted(newest_first)
    pending = sorted(set(backlog) - set(selected))
    return {
        "today": today.isoformat(),
        "raw_days": len(raw),
        "daily_days": len(daily),
        "missing": missing,
        "stale": stale,
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
        "--replace-existing",
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
# process handling
# --------------------------------------------------------------------------


def signal_process_group(pgid: int, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        os.killpg(pgid, sig)


def process_group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stage_process_group(process: "subprocess.Popen[str]") -> int | None:
    """Record the stage's group id while the leader is still alive.

    Asking for it later is too late: if the direct child already exited,
    `os.getpgid` fails and a surviving ssh/scp grandchild would never be
    signalled. `start_new_session` guarantees the leader is the group leader,
    and the id cannot be recycled while any member is still alive.
    """
    if os.name != "posix":  # pragma: no cover - the target host is macOS
        return None
    try:
        return os.getpgid(process.pid)
    except OSError:
        return process.pid


def terminate_process_group(
    process: "subprocess.Popen[str]", grace: float, pgid: int | None = None
) -> None:
    """Terminate the whole stage group: a plain kill leaves ssh/scp behind.

    `sync_obsidian_vault.sh` is Bash that starts ssh and scp; killing only the
    direct child would leave those network children running into the retry.
    """
    if os.name != "posix":  # pragma: no cover - the target host is macOS
        process.kill()
        with contextlib.suppress(Exception):
            process.wait(timeout=grace)
        return
    if pgid is None:
        pgid = stage_process_group(process)
    if pgid is None:  # pragma: no cover - non-posix only
        with contextlib.suppress(Exception):
            process.wait(timeout=grace)
        return

    # 1. Ask the whole group to stop, not just the direct child.
    signal_process_group(pgid, signal.SIGTERM)

    # 2. Reap the direct child before probing: an unreaped zombie keeps
    #    answering `killpg(pgid, 0)`, which would make the group look alive
    #    for the whole grace period even when nothing is running.
    try:
        process.wait(timeout=min(grace, TERMINATION_WAIT_SECONDS))
    except subprocess.TimeoutExpired:
        pass

    # 3. Whatever ignored SIGTERM inside the group is forced down.
    if process_group_alive(pgid):
        signal_process_group(pgid, signal.SIGKILL)
        deadline = time.monotonic() + grace
        while process_group_alive(pgid) and time.monotonic() < deadline:
            time.sleep(TERMINATION_POLL_SECONDS)
        with contextlib.suppress(Exception):
            process.wait(timeout=grace)


def run_process(
    command: list[str],
    env: Mapping[str, str],
    timeout: float,
    grace: float = TIMEOUT_GRACE_SECONDS,
) -> tuple[int, str, str]:
    """Run a stage in its own session; on timeout kill the whole group."""
    options: dict[str, Any] = {
        "env": dict(env),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
    }
    if os.name == "posix":
        # A new session means the stage owns a process group we can signal.
        options["start_new_session"] = True
    process = subprocess.Popen(command, **options)  # type: ignore[arg-type]
    pgid = stage_process_group(process)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate_process_group(process, grace, pgid)
        # Collect whatever the stage managed to write before it died. This
        # only returns once every writer of the pipe is gone, so it doubles
        # as proof that no grandchild survived.
        stdout, stderr = process.communicate()
        raise StageTimeout(timeout, stdout or "", stderr or "") from None
    return process.returncode, stdout or "", stderr or ""


# --------------------------------------------------------------------------
# lock and state
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


def atomic_write_json(path: Path, payload: Any) -> None:
    """Publish state atomically so a concurrent reader never sees a half file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)


@dataclass
class StageResult:
    name: str
    outcome: str  # ok | failed | timeout | skipped | dry-run
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
        self.redactor = Redactor()
        if config.env_file is not None and config.env_file.exists():
            self.redactor.absorb(secret_values(load_env_file(config.env_file)))
        # Whatever is actually handed to the children must be masked too.
        self.redactor.absorb(secret_values(config.extra_env))

    # -- helpers ---------------------------------------------------------
    def redact(self, text: str) -> str:
        return self.redactor(text)

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
        """The single resolved Vault/path configuration, handed to children.

        `sync_obsidian_vault.sh` reads `PERSONAL_MEMORY_VAULT_DIR` and
        `PERSONAL_MEMORY_TARGET_REL`; without this a `--vault-dir` override
        would sync one Vault while the runner scans another.
        """
        env = os.environ.copy()
        env.update(self.config.extra_env)
        if self.config.env_file is not None and self.config.env_file.exists():
            env.update(load_env_file(self.config.env_file))
        vault = self.config.resolved_vault_dir()
        if vault is not None:
            env["PERSONAL_MEMORY_VAULT_DIR"] = str(vault)
            env["PERSONAL_MEMORY_TARGET_REL"] = self.config.resolved_target_rel(vault)
        self.redactor.absorb(secret_values(env))
        return env

    def run_stage(self, name: str, command: list[str]) -> StageResult:
        if self.config.dry_run:
            # Load the exact child environment so dry-run uses the same
            # redaction set as a real run, while still executing nothing.
            self.child_env()
            safe_command = self.redact(shlex.join(command))
            self.emit(f"[dry-run] 将执行 {name}: {safe_command}")
            self.log(name, "dry-run", command=safe_command)
            return StageResult(name, "dry-run")
        env = self.child_env()
        attempts = self.config.max_attempts
        last_detail = ""
        last_kind = "failed"
        for attempt in range(1, attempts + 1):
            self.emit(f"[→] {name}（第 {attempt}/{attempts} 次）")
            try:
                returncode, stdout, stderr = run_process(
                    command, env, self.config.stage_timeout
                )
            except StageTimeout as exc:
                last_kind = "timeout"
                last_detail = str(exc)
                if exc.stderr.strip():
                    last_detail += f"；stderr 尾行：{exc.stderr.strip().splitlines()[-1]}"
                last_detail = self.redact(last_detail)
                self.emit(f"[!] {name} 超时：{last_detail}")
                self.log(name, "timeout", attempt=attempt, detail=last_detail)
                if attempt < attempts:
                    self.sleep(self.config.retry_delay)
                continue
            except OSError as exc:
                last_kind = "failed"
                last_detail = self.redact(f"{type(exc).__name__}: {exc}")
                self.emit(f"[!] {name} 无法执行：{last_detail}")
                self.log(name, "retry", attempt=attempt, detail=last_detail)
                if attempt < attempts:
                    self.sleep(self.config.retry_delay)
                continue

            if returncode == 0:
                for line in stdout.strip().splitlines():
                    self.emit(f"    {self.redact(line)}")
                self.log(name, "ok", attempt=attempt)
                self.emit(f"[✓] {name} 完成")
                return StageResult(name, "ok", attempt)

            last_kind = "failed"
            tail = (stderr or stdout or "").strip().splitlines()
            last_detail = self.redact(tail[-1] if tail else f"exit={returncode}")
            self.emit(f"[!] {name} 失败：{last_detail}")
            self.log(name, "retry", attempt=attempt, detail=last_detail)
            if attempt < attempts:
                self.sleep(self.config.retry_delay)

        self.log(name, "failed", attempts=attempts, detail=last_detail)
        if last_kind == "timeout":
            self.emit(f"[✗] {name} 重试 {attempts} 次后仍超时")
        else:
            self.emit(f"[✗] {name} 重试 {attempts} 次后仍失败")
        return StageResult(name, last_kind, attempts, last_detail)

    def emit_plan(self, plan: dict[str, Any]) -> None:
        self.emit(
            f"[→] 计划 {plan['today']}｜原始记录 {plan['raw_days']} 天｜"
            f"日报 {plan['daily_days']} 天｜待补 {len(plan['missing'])} 天｜"
            f"待刷新 {len(plan.get('stale', []))} 天｜本轮生成 {len(plan['selected'])} 天｜"
            f"仍待处理 {len(plan['pending'])} 天"
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
        validate_config(config)
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
                sync_failed = results[-1].outcome in ("failed", "timeout")
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
            # A losing instance must not publish shared state: the winning
            # instance still owns last-run.json for this round.
            self.emit(f"[=] 已有运行实例持有锁，本轮跳过：{exc}")
            self.log("lock", "skipped", detail=str(exc))
            self.log("run", "skipped", detail="another instance holds the lock")
            self.emit(f"[summary] run=skipped（已有实例在跑）")
            return EXIT_OK

        failed = [item for item in results if item.outcome in ("failed", "timeout")]
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
                 "detail": self.redact(item.detail)}
                for item in results
            ],
        }
        atomic_write_json(last_run_path, payload)
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
            note = ""
            if stage.get("outcome") == "timeout":
                note = f"｜原因：{stage.get('detail') or '超出阶段超时'}"
            lines.append(f"- {stage['name']}：{stage['outcome']}{extra}{note}")
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
    explicit_vault = _pick(
        args.vault_dir, "PERSONAL_MEMORY_VAULT_DIR", file_values, Path,
        None,
    )
    default_vault = explicit_vault or Path(DEFAULT_VAULT_DIR)
    raw_dir = _pick(
        args.raw_dir, "PERSONAL_MEMORY_RAW_DIR", file_values, Path,
        default_vault / DEFAULT_RAW_REL,
    )
    vault = explicit_vault or infer_vault_dir(raw_dir) or default_vault
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
        vault_dir=vault,
        target_rel=_pick(None, "PERSONAL_MEMORY_TARGET_REL", file_values, str, None),
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
    except ConfigError as exc:
        print(f"[✗] 配置无效：{exc}", file=sys.stderr)
        return EXIT_FAILED
    except Exception as exc:  # noqa: BLE001
        print(
            f"LOCAL_INCREMENTAL_RUNNER_ERROR: {type(exc).__name__}: {runner.redact(str(exc))}",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_FAILED)


if __name__ == "__main__":
    raise SystemExit(main())
