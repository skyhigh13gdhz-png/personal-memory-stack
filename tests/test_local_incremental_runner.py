import importlib.util
import json
import os
import shlex
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "local_incremental_runner.py"
SPEC = importlib.util.spec_from_file_location("local_incremental_runner", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
# dataclasses resolves annotations through sys.modules, so register first.
sys.modules.setdefault("local_incremental_runner", MODULE)
SPEC.loader.exec_module(MODULE)


FAKE_SCRIPT = '''import os, sys, time
from pathlib import Path

marker = Path(os.environ["FAKE_MARKER"])
counter = Path(os.environ["FAKE_COUNTER"])
count = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(count + 1))
with marker.open("a", encoding="utf-8") as handle:
    handle.write(os.environ.get("FAKE_NAME", "fake") + " " + " ".join(sys.argv[1:]) + "\\n")
if count == 0:
    time.sleep(float(os.environ.get("FAKE_FIRST_SLEEP", "0")))
if count < int(os.environ.get("FAKE_FAIL_TIMES", "0")):
    sys.stderr.write(os.environ.get("FAKE_ERROR_TEXT", "fake failure") + "\\n")
    raise SystemExit(1)
time.sleep(float(os.environ.get("FAKE_SLEEP", "0")))
sys.stdout.write("fake ok\\n")
'''


class _RunnerHarness:
    """Shared fixtures. Not a TestCase, so it is never collected on its own."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="incremental-runner-")
        self.root = Path(self.temporary.name)
        self.vault = self.root / "Vault"
        self.raw_dir = self.vault / "00-系统生成" / "原始记录" / "liangzai"
        self.daily_dir = self.vault / "01-日报"
        self.work_dir = self.root / "work"
        self.state_dir = self.root / "state"
        self.log_file = self.root / "logs" / "runner.jsonl"
        self.marker = self.root / "marker.txt"
        self.raw_dir.mkdir(parents=True)
        self.daily_dir.mkdir(parents=True)
        self.addCleanup(self.temporary.cleanup)

    # -- helpers ---------------------------------------------------------
    def fake_command(self, name, fail_times=0, sleep=0.0, first_sleep=0.0, error_text=""):
        stub = self.root / f"fake-{name}.py"
        stub.write_text(FAKE_SCRIPT, encoding="utf-8")
        counter = self.root / f"counter-{name}.txt"
        env = {
            "FAKE_MARKER": str(self.marker),
            "FAKE_COUNTER": str(counter),
            "FAKE_NAME": name,
            "FAKE_FAIL_TIMES": str(fail_times),
            "FAKE_SLEEP": str(sleep),
            "FAKE_FIRST_SLEEP": str(first_sleep),
            "FAKE_ERROR_TEXT": error_text,
        }
        prefix = " ".join(f"{key}={shlex.quote(value)}" for key, value in env.items())
        return ["/bin/sh", "-c", f"{prefix} exec python3 {shlex.quote(str(stub))}"]

    def write_day(self, directory, day, body="内容"):
        path = directory / f"{day}.md"
        path.write_text(f"# {day}\n\n{body}\n", encoding="utf-8")
        return path

    def sync_command_creating(self, day):
        target = self.raw_dir / f"{day}.md"
        return ["/bin/sh", "-c", f"printf '# {day}\\n\\n内容\\n' > {shlex.quote(str(target))}"]

    def build_config(self, **overrides):
        options = {
            "raw_dir": self.raw_dir,
            "daily_dir": self.daily_dir,
            "status_output": self.vault / "运行状态.md",
            "work_dir": self.work_dir,
            "today": date(2026, 5, 10),
            "max_daily_days_per_run": 3,
            "max_attempts": 3,
            "retry_delay": 0,
            "stage_timeout": 30.0,
            "log_file": self.log_file,
            "state_dir": self.state_dir,
            "sync_command": self.fake_command("sync"),
            "daily_command": self.fake_command("daily"),
            "status_command": self.fake_command("status"),
        }
        options.update(overrides)
        return MODULE.RunnerConfig(**options)

    def run_runner(self, config):
        lines = []
        runner = MODULE.Runner(config, emit=lines.append, sleep=lambda _seconds: None)
        code = runner.run()
        return code, lines, runner

    def marker_calls(self):
        if not self.marker.exists():
            return []
        return [line for line in self.marker.read_text(encoding="utf-8").splitlines() if line]

    def called_stages(self):
        return [line.split(" ")[0] for line in self.marker_calls()]

    def last_run(self):
        return json.loads((self.state_dir / "last-run.json").read_text(encoding="utf-8"))


class RunnerTestCase(_RunnerHarness, unittest.TestCase):
    # -- planning --------------------------------------------------------
    def test_plan_excludes_today(self):
        self.write_day(self.raw_dir, "2026-05-10")  # today: never generated
        self.write_day(self.raw_dir, "2026-05-09")
        plan = MODULE.plan_run(self.raw_dir, self.daily_dir, date(2026, 5, 10), 3)
        self.assertNotIn("2026-05-10", plan["missing"])
        self.assertEqual(plan["selected"], ["2026-05-09"])

    def test_build_daily_command_targets_gap_range(self):
        command = MODULE.build_daily_command(
            self.raw_dir, self.daily_dir, self.work_dir, "2026-05-03", "2026-05-09"
        )
        self.assertIn(str(self.raw_dir), command)
        self.assertIn("2026-05-03", command)
        self.assertIn("2026-05-09", command)
        self.assertIn("--work-dir", command)

    # -- scenarios -------------------------------------------------------
    def test_no_change_skips_llm_stage(self):
        self.write_day(self.raw_dir, "2026-05-09")
        self.write_day(self.daily_dir, "2026-05-09")
        code, lines, runner = self.run_runner(self.build_config())
        self.assertEqual(code, 0)
        self.assertNotIn("daily", self.called_stages())
        self.assertEqual(self.called_stages().count("status"), 1)
        self.assertTrue(any("不调用 LLM" in line for line in lines))
        self.assertEqual(runner.records[-1]["outcome"], "ok")

    def test_missing_daily_triggers_generation(self):
        self.write_day(self.raw_dir, "2026-05-09")
        code, lines, _ = self.run_runner(self.build_config())
        self.assertEqual(code, 0)
        self.assertIn("daily", self.called_stages())
        self.assertIn("status", self.called_stages())
        self.assertTrue(any("daily-v2=ok" in line for line in lines))

    def test_existing_daily_file_is_untouched(self):
        self.write_day(self.raw_dir, "2026-05-09")
        existing = self.write_day(self.daily_dir, "2026-05-09", body="人工修订过的日报")
        before = existing.stat().st_mtime_ns
        code, _, _ = self.run_runner(self.build_config())
        self.assertEqual(code, 0)
        self.assertEqual(existing.read_text(encoding="utf-8").splitlines()[-1], "人工修订过的日报")
        self.assertEqual(existing.stat().st_mtime_ns, before)

    def test_concurrent_lock_skips_second_run(self):
        self.write_day(self.raw_dir, "2026-05-09")
        config = self.build_config()
        config.lock_path().parent.mkdir(parents=True, exist_ok=True)
        with MODULE.acquire_lock(config.lock_path()):
            code, lines, runner = self.run_runner(config)
        self.assertEqual(code, 0)
        self.assertEqual(self.marker_calls(), [])
        self.assertTrue(any("持有锁" in line for line in lines))
        self.assertEqual(runner.records[-1]["outcome"], "skipped")

    def test_single_day_failure_returns_nonzero_and_still_renders_status(self):
        self.write_day(self.raw_dir, "2026-05-09")
        config = self.build_config(
            daily_command=self.fake_command("daily", fail_times=99), max_attempts=3
        )
        code, lines, runner = self.run_runner(config)
        self.assertEqual(code, MODULE.EXIT_FAILED)
        self.assertEqual(self.called_stages().count("daily"), 3)
        self.assertIn("status", self.called_stages())
        self.assertEqual(runner.records[-1]["outcome"], "failed")

    def test_retry_recovers_before_limit(self):
        self.write_day(self.raw_dir, "2026-05-09")
        config = self.build_config(
            daily_command=self.fake_command("daily", fail_times=2), max_attempts=3
        )
        code, _, _ = self.run_runner(config)
        self.assertEqual(code, 0)
        self.assertEqual(self.called_stages().count("daily"), 3)

    def test_retry_limit_is_bounded(self):
        self.write_day(self.raw_dir, "2026-05-09")
        config = self.build_config(
            daily_command=self.fake_command("daily", fail_times=5), max_attempts=2
        )
        code, _, _ = self.run_runner(config)
        self.assertEqual(code, MODULE.EXIT_FAILED)
        self.assertEqual(self.called_stages().count("daily"), 2)

    def test_sync_failure_skips_daily_generation(self):
        self.write_day(self.raw_dir, "2026-05-09")
        config = self.build_config(
            sync_command=self.fake_command("sync", fail_times=99), max_attempts=2
        )
        code, lines, _ = self.run_runner(config)
        self.assertEqual(code, MODULE.EXIT_FAILED)
        self.assertNotIn("daily", self.called_stages())
        self.assertTrue(any("跳过日报生成" in line for line in lines))

    def test_dry_run_executes_nothing(self):
        self.write_day(self.raw_dir, "2026-05-09")
        code, lines, runner = self.run_runner(self.build_config(dry_run=True))
        self.assertEqual(code, 0)
        self.assertEqual(self.marker_calls(), [])
        self.assertTrue(any("[dry-run]" in line for line in lines))
        self.assertEqual(runner.records[-1]["outcome"], "dry-run")

    def test_paths_with_chinese_and_spaces(self):
        vault = self.root / "陈 老的 Vault 备份"
        raw = vault / "00-系统生成" / "原始记录" / "liangzai"
        daily = vault / "01-日报"
        raw.mkdir(parents=True)
        daily.mkdir(parents=True)
        (raw / "2026-05-09.md").write_text("# 2026-05-09\n", encoding="utf-8")
        config = self.build_config(
            raw_dir=raw, daily_dir=daily, status_output=vault / "运行状态.md"
        )
        code, _, _ = self.run_runner(config)
        self.assertEqual(code, 0)
        self.assertIn("daily", self.called_stages())

    def test_last_run_state_is_persisted(self):
        self.write_day(self.raw_dir, "2026-05-09")
        code, _, _ = self.run_runner(self.build_config())
        self.assertEqual(code, 0)
        payload = self.last_run()
        self.assertEqual(payload["outcome"], "ok")
        self.assertEqual(payload["plan"]["selected"], ["2026-05-09"])
        self.assertTrue(self.log_file.exists())

    def test_last_success_survives_a_failed_run(self):
        self.write_day(self.raw_dir, "2026-05-09")
        self.run_runner(self.build_config())
        success_at = self.last_run()["last_success_at"]
        config = self.build_config(
            daily_command=self.fake_command("daily", fail_times=99), max_attempts=1
        )
        code, _, _ = self.run_runner(config)
        self.assertEqual(code, MODULE.EXIT_FAILED)
        payload = self.last_run()
        self.assertEqual(payload["outcome"], "failed")
        self.assertEqual(payload["last_success_at"], success_at)

    def test_env_file_values_never_reach_the_log(self):
        env_file = self.root / "runner.env"
        env_file.write_text(
            '# comment\nGATEWAY_API_TOKEN="super-secret-token"\n'
            "export PERSONAL_MEMORY_VAULT_DIR='/tmp/vault'\n",
            encoding="utf-8",
        )
        env_file.chmod(0o600)
        values = MODULE.load_env_file(env_file)
        self.assertEqual(values["GATEWAY_API_TOKEN"], "super-secret-token")
        self.assertEqual(values["PERSONAL_MEMORY_VAULT_DIR"], "/tmp/vault")
        self.write_day(self.raw_dir, "2026-05-09")
        config = self.build_config(env_file=env_file)
        _, _, runner = self.run_runner(config)
        serialized = json.dumps(runner.records, ensure_ascii=False)
        self.assertNotIn("super-secret-token", serialized)

    def test_child_stderr_secret_is_redacted(self):
        env_file = self.root / "runner.env"
        env_file.write_text('GATEWAY_API_TOKEN="super-secret-token"\n', encoding="utf-8")
        env_file.chmod(0o600)
        self.write_day(self.raw_dir, "2026-05-09")
        config = self.build_config(
            env_file=env_file,
            daily_command=self.fake_command(
                "daily", fail_times=99, error_text="boom super-secret-token leaked"
            ),
            max_attempts=1,
        )
        code, lines, runner = self.run_runner(config)
        self.assertEqual(code, MODULE.EXIT_FAILED)
        serialized = json.dumps(runner.records, ensure_ascii=False)
        self.assertNotIn("super-secret-token", serialized)
        self.assertTrue(any("***" in line for line in lines))

    def test_env_file_permission_warning(self):
        env_file = self.root / "loose.env"
        env_file.write_text("A=b\n", encoding="utf-8")
        env_file.chmod(0o644)
        self.assertIsNotNone(MODULE.env_file_permission_warning(env_file))
        env_file.chmod(0o600)
        self.assertIsNone(MODULE.env_file_permission_warning(env_file))


# --------------------------------------------------------------------------
# WB-01R regression tests
# --------------------------------------------------------------------------


class R1EnvFilePriorityTests(_RunnerHarness, unittest.TestCase):
    """R1: the env file must configure the runner itself, not only children."""

    def write_env_file(self, **values):
        path = self.root / "runner.env"
        body = "\n".join(f"{key}={shlex.quote(str(value))}" for key, value in values.items())
        path.write_text(body + "\n", encoding="utf-8")
        path.chmod(0o600)
        return path

    def config_from_cli(self, argv):
        args = MODULE.build_parser().parse_args(argv)
        return MODULE.config_from_args(args)

    def test_env_file_configures_runner_paths(self):
        env_file = self.write_env_file(
            PERSONAL_MEMORY_RAW_DIR=str(self.root / "env-raw"),
            PERSONAL_MEMORY_DAILY_DIR=str(self.root / "env-daily"),
            PERSONAL_MEMORY_STATUS_OUTPUT=str(self.root / "env-status.md"),
        )
        config = self.config_from_cli(["run", "--env-file", str(env_file)])
        self.assertEqual(config.raw_dir, self.root / "env-raw")
        self.assertEqual(config.daily_dir, self.root / "env-daily")
        self.assertEqual(config.status_output, self.root / "env-status.md")

    def test_env_file_configures_runner_limits(self):
        env_file = self.write_env_file(
            PERSONAL_MEMORY_MAX_DAILY_DAYS_PER_RUN="5",
            PERSONAL_MEMORY_MAX_ATTEMPTS="7",
            PERSONAL_MEMORY_RETRY_DELAY="1.5",
            PERSONAL_MEMORY_STAGE_TIMEOUT="42",
        )
        config = self.config_from_cli(["run", "--env-file", str(env_file)])
        self.assertEqual(config.max_daily_days_per_run, 5)
        self.assertEqual(config.max_attempts, 7)
        self.assertEqual(config.retry_delay, 1.5)
        self.assertEqual(config.stage_timeout, 42.0)

    def test_cli_overrides_env_file(self):
        env_file = self.write_env_file(PERSONAL_MEMORY_RAW_DIR=str(self.root / "env-raw"))
        config = self.config_from_cli([
            "run", "--env-file", str(env_file), "--raw-dir", str(self.root / "cli-raw")
        ])
        self.assertEqual(config.raw_dir, self.root / "cli-raw")

    def test_env_file_beats_process_environment(self):
        env_file = self.write_env_file(PERSONAL_MEMORY_MAX_ATTEMPTS="3")
        with mock.patch.dict(os.environ, {"PERSONAL_MEMORY_MAX_ATTEMPTS": "9"}):
            config = self.config_from_cli(["run", "--env-file", str(env_file)])
        self.assertEqual(config.max_attempts, 3)

    def test_process_environment_beats_default(self):
        with mock.patch.dict(os.environ, {"PERSONAL_MEMORY_MAX_ATTEMPTS": "6"}):
            config = self.config_from_cli(["run"])
        self.assertEqual(config.max_attempts, 6)

    def test_env_file_vault_dir_drives_derived_paths(self):
        vault = self.root / "env-vault"
        env_file = self.write_env_file(PERSONAL_MEMORY_VAULT_DIR=str(vault))
        config = self.config_from_cli(["run", "--env-file", str(env_file)])
        self.assertEqual(config.raw_dir, vault / MODULE.DEFAULT_RAW_REL)
        self.assertEqual(config.daily_dir, vault / MODULE.DEFAULT_DAILY_REL)
        self.assertEqual(config.status_output, vault / MODULE.DEFAULT_STATUS_REL)

    def test_end_to_end_run_uses_env_file_vault(self):
        """Parent and children must agree on one Vault."""
        vault = self.root / "env-vault"
        raw = vault / MODULE.DEFAULT_RAW_REL
        daily = vault / MODULE.DEFAULT_DAILY_REL
        raw.mkdir(parents=True)
        daily.mkdir(parents=True)
        (raw / "2026-05-09.md").write_text("# 2026-05-09\n", encoding="utf-8")
        env_file = self.write_env_file(PERSONAL_MEMORY_VAULT_DIR=str(vault))
        argv = [
            "run", "--env-file", str(env_file), "--today", "2026-05-10",
            "--state-dir", str(self.state_dir), "--log-file", str(self.log_file),
            "--sync-command", shlex.join(self.fake_command("sync")),
            "--daily-command", shlex.join(self.fake_command("daily")),
            "--status-command", shlex.join(self.fake_command("status")),
        ]
        config = self.config_from_cli(argv)
        code, _, _ = self.run_runner(config)
        self.assertEqual(code, 0)
        self.assertIn("daily", self.called_stages())
        self.assertEqual(self.last_run()["plan"]["selected"], ["2026-05-09"])


class R2PlanAfterSyncTests(_RunnerHarness, unittest.TestCase):
    """R2: plan must be computed after sync, inside the same round."""

    def test_plan_is_recomputed_after_sync(self):
        # raw is empty before sync; fake sync creates yesterday's projection.
        config = self.build_config(sync_command=self.sync_command_creating("2026-05-09"))
        code, lines, _ = self.run_runner(config)
        self.assertEqual(code, 0)
        self.assertIn("daily", self.called_stages())
        self.assertTrue(any("本轮生成：2026-05-09" in line for line in lines))

    def test_last_run_uses_post_sync_plan(self):
        config = self.build_config(sync_command=self.sync_command_creating("2026-05-09"))
        self.run_runner(config)
        payload = self.last_run()
        self.assertEqual(payload["plan"]["selected"], ["2026-05-09"])
        self.assertEqual(payload["plan"]["raw_days"], 1)

    def test_no_new_records_after_sync_skips_generation(self):
        self.write_day(self.raw_dir, "2026-05-09")
        self.write_day(self.daily_dir, "2026-05-09")
        code, _, _ = self.run_runner(self.build_config())
        self.assertEqual(code, 0)
        self.assertNotIn("daily", self.called_stages())


class R3DryRunReadOnlyTests(_RunnerHarness, unittest.TestCase):
    """R3: dry-run must not write logs, state, lock or call anything."""

    def test_dry_run_writes_nothing_in_readonly_home(self):
        readonly = self.root / "readonly-home"
        readonly.mkdir()
        (readonly / "marker").write_text("x", encoding="utf-8")
        readonly.chmod(0o500)
        self.addCleanup(lambda: readonly.chmod(0o700))
        config = self.build_config(
            dry_run=True,
            state_dir=readonly / "state",
            log_file=readonly / "logs" / "runner.jsonl",
            status_output=readonly / "vault" / "运行状态.md",
        )
        self.write_day(self.raw_dir, "2026-05-09")
        code, lines, runner = self.run_runner(config)
        self.assertEqual(code, 0)
        self.assertEqual(self.marker_calls(), [])
        self.assertEqual(sorted(os.listdir(readonly)), ["marker"])
        self.assertFalse((readonly / "state").exists())
        self.assertFalse((readonly / "logs").exists())
        self.assertTrue(any("[dry-run]" in line for line in lines))
        self.assertEqual(runner.records[-1]["outcome"], "dry-run")

    def test_dry_run_does_not_create_lock(self):
        self.write_day(self.raw_dir, "2026-05-09")
        config = self.build_config(dry_run=True)
        self.run_runner(config)
        self.assertFalse(config.lock_path().exists())

    def test_dry_run_prints_planned_dates(self):
        for day in ("2026-05-07", "2026-05-08", "2026-05-09"):
            self.write_day(self.raw_dir, day)
        config = self.build_config(dry_run=True, max_daily_days_per_run=2)
        code, lines, _ = self.run_runner(config)
        self.assertEqual(code, 0)
        self.assertTrue(any("仍待处理：2026-05-07" in line for line in lines))


class R4DefaultLayoutTests(unittest.TestCase):
    """R4: default status path must match the real Vault layout."""

    def test_default_status_rel_matches_real_layout(self):
        self.assertEqual(
            MODULE.DEFAULT_STATUS_REL,
            "AI/AI外置记忆/90-系统/运行状态/外置记忆运行状态.md",
        )

    def test_status_output_derived_from_vault(self):
        args = MODULE.build_parser().parse_args(["run", "--vault-dir", "/tmp/Vault"])
        config = MODULE.config_from_args(args)
        self.assertEqual(
            config.status_output,
            Path("/tmp/Vault/AI/AI外置记忆/90-系统/运行状态/外置记忆运行状态.md"),
        )
        self.assertEqual(
            config.raw_dir,
            Path("/tmp/Vault/AI/AI外置记忆/00-系统生成/原始记录/liangzai"),
        )


class R5BacklogQueueTests(_RunnerHarness, unittest.TestCase):
    """R5: old gaps stay queued instead of being dropped forever."""

    def make_backlog(self, days):
        for day in days:
            self.write_day(self.raw_dir, day)

    def test_older_gaps_remain_pending(self):
        self.make_backlog([f"2026-05-{day:02d}" for day in range(1, 10)])
        plan = MODULE.plan_run(self.raw_dir, self.daily_dir, date(2026, 5, 10), 3)
        self.assertEqual(plan["selected"], ["2026-05-07", "2026-05-08", "2026-05-09"])
        self.assertEqual(
            plan["pending"], [f"2026-05-{day:02d}" for day in range(1, 7)]
        )
        self.assertEqual(len(plan["missing"]), 9)

    def test_yesterday_is_selected_first(self):
        self.make_backlog(["2026-04-01", "2026-05-09", "2026-05-01"])
        plan = MODULE.plan_run(self.raw_dir, self.daily_dir, date(2026, 5, 10), 1)
        self.assertEqual(plan["selected"], ["2026-05-09"])
        self.assertEqual(plan["pending"], ["2026-04-01", "2026-05-01"])

    def test_daily_command_covers_only_selected_range(self):
        self.make_backlog([f"2026-05-{day:02d}" for day in range(1, 10)])
        # no injected daily command: assert the real command builder
        config = self.build_config(max_daily_days_per_run=3, daily_command=None)
        runner = MODULE.Runner(config, emit=lambda _line: None)
        plan = runner.make_plan(config.resolved_today())
        command = runner.daily_command_for(plan)
        self.assertIn("2026-05-07", command)
        self.assertIn("2026-05-09", command)
        self.assertNotIn("2026-05-01", command)

    def test_status_reports_selected_and_pending(self):
        self.make_backlog([f"2026-05-{day:02d}" for day in range(1, 6)])
        config = self.build_config(max_daily_days_per_run=2)
        self.run_runner(config)
        payload = self.last_run()
        self.assertEqual(payload["plan"]["selected"], ["2026-05-04", "2026-05-05"])
        self.assertEqual(
            payload["plan"]["pending"], ["2026-05-01", "2026-05-02", "2026-05-03"]
        )
        text = MODULE.render_status(config)
        self.assertIn("本轮生成：2026-05-04, 2026-05-05", text)
        self.assertIn("仍待处理：2026-05-01, 2026-05-02, 2026-05-03", text)


class R6StageTimeoutTests(_RunnerHarness, unittest.TestCase):
    """R6: a hung child must not hold the lock forever."""

    def test_stage_timeout_is_bounded(self):
        self.write_day(self.raw_dir, "2026-05-09")
        config = self.build_config(
            daily_command=self.fake_command("daily", sleep=3),
            stage_timeout=0.2, max_attempts=2,
        )
        code, lines, runner = self.run_runner(config)
        self.assertEqual(code, MODULE.EXIT_FAILED)
        self.assertEqual(self.called_stages().count("daily"), 2)
        timeouts = [item for item in runner.records if item["outcome"] == "timeout"]
        self.assertEqual(len(timeouts), 2)
        self.assertTrue(any("超时" in line for line in lines))

    def test_timeout_retry_can_recover(self):
        self.write_day(self.raw_dir, "2026-05-09")
        config = self.build_config(
            daily_command=self.fake_command("daily", first_sleep=3),
            stage_timeout=0.2, max_attempts=3,
        )
        code, _, runner = self.run_runner(config)
        self.assertEqual(code, 0)
        self.assertEqual(self.called_stages().count("daily"), 2)
        self.assertTrue(any(item["outcome"] == "timeout" for item in runner.records))

    def test_stage_timeout_is_configurable(self):
        with mock.patch.dict(os.environ, {"PERSONAL_MEMORY_STAGE_TIMEOUT": "99"}):
            config = MODULE.config_from_args(MODULE.build_parser().parse_args(["run"]))
        self.assertEqual(config.stage_timeout, 99.0)


if __name__ == "__main__":
    unittest.main()
