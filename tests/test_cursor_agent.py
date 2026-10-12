"""Tests for the cursor-agent provider: the headless Cursor CLI as the
dreamer's brain (no HTTP endpoint, no proxy, no API key)."""

import unittest
from unittest.mock import patch

from open_dream_rsi.cursor_agent import CursorAgentClient, _flatten
from open_dream_rsi.mcp import _default_provider

EXE = "/usr/local/bin/cursor-agent"


class FlattenTests(unittest.TestCase):
    def test_system_and_user_join(self):
        out = _flatten([{"role": "system", "content": "BE CONTRACT"},
                        {"role": "user", "content": "distil this"}])
        self.assertEqual(out, "[system]\nBE CONTRACT\n\ndistil this")


class ClientTests(unittest.TestCase):
    """subprocess.run is mocked; shutil.which resolves a fake CLI."""

    def _run_client(self, argv_capture, rc=0, out="ok", err="",
                    which=EXE, is_win=False):
        def fake_run(argv, **kwargs):
            argv_capture.append(argv)
            return type("P", (), {"returncode": rc,
                                  "stdout": out, "stderr": err})()
        with patch("open_dream_rsi.cursor_agent.subprocess.run",
                   side_effect=fake_run), \
             patch("open_dream_rsi.cursor_agent.shutil.which",
                   return_value=which), \
             patch("open_dream_rsi.cursor_agent._IS_WIN", is_win):
            return CursorAgentClient(model="composer-2.5").chat(
                [{"role": "system", "content": "s"},
                 {"role": "user", "content": "u"}])

    def test_argv_shape_and_model_passthrough(self):
        seen = []
        reply = self._run_client(seen)
        self.assertEqual(reply, "ok")
        argv = seen[0]
        self.assertEqual(argv[0], EXE)
        for flag in ("-p", "--force", "--output-format", "text"):
            self.assertIn(flag, argv)
        self.assertIn("composer-2.5", argv)
        self.assertIn("u", argv[-1])

    def test_cmd_shim_wraps_in_cmd_exe_on_windows(self):
        seen = []
        self._run_client(seen, which="C:\\x\\cursor-agent.CMD", is_win=True)
        self.assertEqual(seen[0][:3], ["cmd.exe", "/c", "C:\\x\\cursor-agent.CMD"])

    def test_no_wrapper_on_posix(self):
        seen = []
        self._run_client(seen)
        self.assertEqual(seen[0][0], EXE)  # no cmd.exe prefix

    def test_missing_cli_raises_before_spawn(self):
        with patch("open_dream_rsi.cursor_agent.shutil.which",
                   return_value=None):
            with self.assertRaises(RuntimeError) as ctx:
                CursorAgentClient().chat([{"role": "user", "content": "x"}])
        self.assertIn("cursor-agent CLI not found", str(ctx.exception))

    def test_nonzero_rc_raises(self):
        with self.assertRaises(RuntimeError) as ctx:
            self._run_client([], rc=2, err="boom")
        self.assertIn("rc=2", str(ctx.exception))
        self.assertIn("boom", str(ctx.exception))

    def test_empty_output_raises(self):
        with self.assertRaises(RuntimeError):
            self._run_client([], rc=0, out="  ")


class ProviderChainTests(unittest.TestCase):
    def setUp(self):
        import os
        self._saved = {k: os.environ.get(k) for k in
                       ("ODR_LLM_PRESET", "OPENAI_BASE_URL", "OPENAI_API_KEY")}

    def tearDown(self):
        import os
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_cursor_agent_detected_on_path(self):
        import os
        for k in ("ODR_LLM_PRESET", "OPENAI_BASE_URL", "OPENAI_API_KEY"):
            os.environ.pop(k, None)
        with patch("shutil.which", return_value=EXE):
            self.assertEqual(_default_provider(), "cursor-agent")

    def test_openai_env_still_wins_over_cli(self):
        import os
        os.environ.pop("ODR_LLM_PRESET", None)
        os.environ["OPENAI_API_KEY"] = "sk-something"
        with patch("shutil.which", return_value=EXE):
            self.assertEqual(_default_provider(), "openai")


if __name__ == "__main__":
    unittest.main()
