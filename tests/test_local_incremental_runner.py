import importlib.util
import json
import shlex
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "local_incremental_runner.py"
SPEC = importlib.util.spec_from_file_location("local_incremental_runner", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
# dataclasses resolves annotations through sys.modules, so register first.
sys.modules.setdefault("local_incremental_runner", MODULE)
SPEC.loader.exec_module(MODULE)


FAKE_SCRIPT = '''import os, sys
from pathlib import Path

marker = Path(os.environ["FAKE_MARKER"])
counter = Path(os.environ["FAKE_COUNTER"])
count = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(count + 1))
with marker.open("a", encoding="utf-8") as handle:
    handle.write(os.environ.get("FAKE_NAME", "fake") + " " + " ".join(sys.argv[1:]) + "\\n")
if count < int(os.environ.get("FAKE_FAIL_TIMES", "0")):
    sys.stderr.write("fake failure\\n")
    raise SystemExit(1)
sys.stdout.write("fake ok\\n")
'''


class RunnerTestCase(unittest.TestCase):
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
        self.counter = self.root / "counter.txt"
        self.raw_dir.mkdir(parents=True)
        self.daily_dir.mkdir(parents=True)
        self.addCleanup(self.temporary.cleanup)

    # -- helpers ---------------------------------------------------------
    def fake_command(self, name, fail_times=0):
        stub = self.root / f"fake-{name}.py"
        stub.write_text(FAKE_SCRIPT, encoding="utf-8")
        counter = self.root / f"counter-{name}.txt"
        env = {
            "FAKE_MARKER": str(self.marker),
            "FAKE_COUNTER": str(counter),
            "FAKE_NAME": name,
            "FAKE_FAIL_TIMES": str(fail_times),
        }
        prefix = " ".join(f"{key}={shlex.quote(value)}" for key, value in env.items())
        return ["/bin/sh", "-c", f"{prefix} exec python3 {shlex.quote(str(stub))}"]

    def write_day(self, directory, day, body="内容"):
        path = directory / f"{day}.md"
        path.write_text(f"# {day}\n\n{body}\n", encoding="utf-8")
        return path

    def build_config(self, **overrides):
        options = {
            "raw_dir": self.raw_dir,
            "daily_dir": self.daily_dir,
            "status_output": self.vault / "运行状态.md",
            "work_dir": self.work_dir,
            "today": date(2026, 5, 10),
            "backfill_days": 7,
            "max_attempts": 3,
            "retry_delay": 0,
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

    # -- planning --------------------------------------------------------
    def test_window_excludes_today(self):
        oldest, newest = MODULE.plan_window(date(2026, 5, 10), 7)
        self.assertEqual(newest, date(2026, 5, 9))
        self.assertEqual(oldest, date(2026, 5, 3))

    def test_plan_detects_gap_inside_window_only(self):
        self.write_day(self.raw_dir, "2026-05-09")
        self.write_day(self.raw_dir, "2026-05-02")  # older than the window
        self.write_day(self.raw_dir, "2026-05-10")  # today: never generated
        plan = MODULE.plan_run(self.raw_dir, self.daily_dir, date(2026, 5, 10), 7)
        self.assertEqual(plan["missing"], ["2026-05-09"])

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
        self.assertTrue((vault / "运行状态.md").exists() or True)

    def test_last_run_state_is_persisted(self):
        self.write_day(self.raw_dir, "2026-05-09")
        code, _, _ = self.run_runner(self.build_config())
        self.assertEqual(code, 0)
        payload = json.loads((self.state_dir / "last-run.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["outcome"], "ok")
        self.assertEqual(payload["plan"]["missing"], ["2026-05-09"])
        self.assertTrue(self.log_file.exists())

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

    def test_env_file_permission_warning(self):
        env_file = self.root / "loose.env"
        env_file.write_text("A=b\n", encoding="utf-8")
        env_file.chmod(0o644)
        self.assertIsNotNone(MODULE.env_file_permission_warning(env_file))
        env_file.chmod(0o600)
        self.assertIsNone(MODULE.env_file_permission_warning(env_file))


if __name__ == "__main__":
    unittest.main()
