"""Offline approval quota tests: no credentials, network, or real CI approvals."""

import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest import mock


spec = importlib.util.spec_from_file_location(
    "triage_approve_under_test", Path(__file__).with_name("triage_bot.py"))
triage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(triage)


class ApprovalQuotaTests(unittest.TestCase):
    def invoke(self, arguments, configured_limit=2):
        gh = mock.Mock(repo="fixture/repo", calls=0, remaining=1000)
        gh.paginate.side_effect = [
            [{"number": n, "head": {"sha": str(n)}} for n in (11, 12, 13)],
            [{"id": n + 100, "head_sha": str(n), "name": "ci"}
             for n in (11, 12, 13)],
        ]
        cfg = {"repo": "fixture/repo", "approve_max_per_run": configured_limit}
        output, errors = io.StringIO(), io.StringIO()
        code = 0
        with mock.patch.object(sys, "argv", ["triage_bot.py", "approve"] + arguments), \
             mock.patch.object(triage, "load_cfg", return_value=cfg), \
             mock.patch.object(triage, "load_token", return_value="offline-fixture") as token, \
             mock.patch.object(triage, "Gh", return_value=gh) as client, \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            try:
                triage.main()
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue(), errors.getvalue(), token, client, gh

    def assert_rejected(self, result):
        code, output, errors, token, client, gh = result
        self.assertEqual(code, 2)
        self.assertIn("non-negative integer", errors)
        self.assertNotIn("would approve", output)
        token.assert_not_called()
        client.assert_not_called()
        gh.req.assert_not_called()

    def test_negative_live_cap_is_rejected_before_credentials_or_api(self):
        for value in ("-1", "-100"):
            with self.subTest(value=value):
                self.assert_rejected(self.invoke(["--max", value]))

    def test_negative_dry_cap_is_also_rejected(self):
        self.assert_rejected(self.invoke(["--max", "-1", "--dry"]))

    def test_invalid_configured_cap_is_rejected_before_credentials_or_api(self):
        for value in (-1, -100, True, 1.5, "2", None):
            with self.subTest(value=value):
                self.assert_rejected(self.invoke([], configured_limit=value))

    def test_zero_cap_approves_nothing(self):
        code, _, _, _, _, gh = self.invoke(["--max", "0"])
        self.assertEqual(code, 0)
        gh.req.assert_not_called()

    def test_positive_cap_only_approves_that_many_runs(self):
        code, _, _, _, _, gh = self.invoke(["--max", "1"])
        self.assertEqual(code, 0)
        self.assertEqual(gh.req.call_args_list, [mock.call(
            "POST", "/repos/fixture/repo/actions/runs/111/approve")])

    def test_omitted_cap_uses_valid_configured_limit(self):
        code, _, _, _, _, gh = self.invoke([])
        self.assertEqual(code, 0)
        self.assertEqual(gh.req.call_count, 2)

    def test_explicit_cap_overrides_invalid_configured_limit(self):
        code, _, _, _, _, gh = self.invoke(["--max", "1"], configured_limit=-1)
        self.assertEqual(code, 0)
        self.assertEqual(gh.req.call_count, 1)

    def test_valid_dry_run_preserves_quota_without_posting(self):
        code, output, _, _, _, gh = self.invoke(["--max", "2", "--dry"])
        self.assertEqual(code, 0)
        self.assertEqual(output.count("DRY would approve:"), 2)
        gh.req.assert_not_called()


if __name__ == "__main__":
    unittest.main()
