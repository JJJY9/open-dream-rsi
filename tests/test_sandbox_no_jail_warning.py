"""Contract for the one-time no-jail warning (external review, 2026-10).

``run_isolated`` is defence in depth only: without ``ODR_SANDBOX_CMD`` there
is no filesystem/network restriction. The gap must be visible in logs, once
per process, and never when a jail is configured.
"""

import unittest
from unittest import mock

from open_dream_rsi import sandbox


class NoJailWarningTest(unittest.TestCase):
    def test_warns_once_without_jail_and_silently_with_jail(self):
        with mock.patch.dict(sandbox.__dict__, {"_JAIL_WARNED": False}):
            with self.assertLogs(sandbox.__name__, level="WARNING") as captured:
                sandbox._warn_no_jail_once()
            self.assertIn("ODR_SANDBOX_CMD", captured.output[0])
            # Second call in the same process: silent (one-time contract).
            with self.assertNoLogs(sandbox.__name__, level="WARNING"):
                sandbox._warn_no_jail_once()
        # A configured jail disables the warning entirely.
        with mock.patch.dict(sandbox.__dict__, {"_JAIL_WARNED": False}), \
                mock.patch.object(sandbox, "jail_prefix",
                                  return_value=["bwrap", "--unshare-all"]):
            with self.assertNoLogs(sandbox.__name__, level="WARNING"):
                sandbox._warn_no_jail_once()


if __name__ == "__main__":
    unittest.main()
