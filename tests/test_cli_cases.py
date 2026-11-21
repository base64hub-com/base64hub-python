"""Runs every case of testdata/cli.json (generated from the Go reference build) against the CLI."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from tests import ROOT, SRC

with open(os.path.join(ROOT, "testdata", "cli.json"), encoding="utf-8") as f:
    CASES = json.load(f)["cases"]


class CliCasesTest(unittest.TestCase):
    def test_all_cases(self):
        self.assertTrue(CASES)
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if os.environ.get("BASE64HUB_TEST_INSTALLED") != "1":
            env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
        # An empty working directory, so relative paths in the cases never touch real files.
        with tempfile.TemporaryDirectory() as cwd:
            for i, c in enumerate(CASES):
                with self.subTest(i=i, args=c["args"]):
                    p = subprocess.run(
                        [sys.executable, "-m", "base64hub", *c["args"]],
                        input=bytes.fromhex(c["stdin_hex"]),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        env=env,
                        cwd=cwd,
                        timeout=60,
                    )
                    self.assertEqual(p.stdout.hex(), c["stdout_hex"], "stdout")
                    self.assertEqual(p.stderr.decode("utf-8"), c["stderr"], "stderr")
                    self.assertEqual(p.returncode, c["exit"], "exit code")


if __name__ == "__main__":
    unittest.main()
