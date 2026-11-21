import os
import subprocess
import sys
import tempfile
import unittest

from tests import ROOT, SRC

import base64hub


def run(*args, stdin=b""):
    """Run the CLI in a subprocess; returns (exit code, stdout bytes, stderr text)."""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if os.environ.get("BASE64HUB_TEST_INSTALLED") != "1":
        env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run(
        [sys.executable, "-m", "base64hub", *args],
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=ROOT,
        timeout=60,
    )
    return p.returncode, p.stdout, p.stderr.decode("utf-8")


class ExamplesTest(unittest.TestCase):
    """The four examples from the docs, exactly."""

    def test_encode_text(self):
        self.assertEqual(run("Hello, hub!"), (0, b"SGVsbG8sIGh1YiE=\n", ""))

    def test_decode_text(self):
        self.assertEqual(run("-d", "SGVsbG8sIGh1YiE="), (0, b"Hello, hub!", ""))

    def test_url_from_stdin(self):
        self.assertEqual(run("--url", stdin=b"\xfb\xff\xbf"), (0, b"-_-_\n", ""))

    def test_url_no_pad_cyrillic(self):
        self.assertEqual(run("--url", "--no-pad", "Привет"), (0, b"0J_RgNC40LLQtdGC\n", ""))


class FlagsTest(unittest.TestCase):
    def test_short_and_long_forms(self):
        self.assertEqual(run("-u", "-n", "Привет")[1], b"0J_RgNC40LLQtdGC\n")
        self.assertEqual(run("--decode", "Zm9v")[1], b"foo")
        self.assertEqual(run("-w", "4", "foobar")[1], b"Zm9v\nYmFy\n")
        self.assertEqual(run("--wrap", "4", "foobar")[1], b"Zm9v\nYmFy\n")
        self.assertEqual(run("--wrap=4", "foobar")[1], b"Zm9v\nYmFy\n")
        self.assertEqual(run("-w", "0", "foobar")[1], b"Zm9vYmFy\n")

    def test_stdin_no_newline_added_and_raw_decode(self):
        self.assertEqual(run(stdin=b"")[1], b"\n")
        self.assertEqual(run(stdin=b"\x00\xff")[1], b"AP8=\n")
        self.assertEqual(run("-d", stdin=b"AP8=\n")[1], b"\x00\xff")
        self.assertEqual(run("-d", stdin=b"Zm9v\r\nYmFy\r\n")[1], b"foobar")

    def test_flags_after_text(self):
        self.assertEqual(run("Zm9v", "-d")[1], b"foo")

    def test_double_dash(self):
        self.assertEqual(run("--", "-d"), (0, b"LWQ=\n", ""))
        self.assertEqual(run("-d", "--", "-_-_")[1], b"\xfb\xff\xbf")

    def test_data_uri(self):
        self.assertEqual(run("--data-uri", "hi")[1], b"data:text/plain;charset=utf-8;base64,aGk=\n")
        self.assertEqual(run("--data-uri", "-m", "text/x-a", "hi")[1], b"data:text/x-a;base64,aGk=\n")
        self.assertEqual(run("--data-uri", "--mime", "image/png", stdin=b"\x89PNG\r\n\x1a\n")[1],
                         b"data:image/png;base64,iVBORw0KGgo=\n")

    def test_validate(self):
        self.assertEqual(run("--validate", "SGVsbG8sIGh1YiE="), (0, b"valid (either, 11 bytes)\n", ""))
        self.assertEqual(run("--validate", "--", "-_-_"), (0, b"valid (url, 3 bytes)\n", ""))
        self.assertEqual(run("--validate", "a+b_")[1], b"valid (mixed, 3 bytes)\n")
        self.assertEqual(run("--validate", stdin=b"+/+/\n")[1], b"valid (standard, 3 bytes)\n")
        code, out, err = run("--validate", "Zm9v!")
        self.assertEqual((code, out), (1, b""))
        self.assertEqual(err, "invalid: invalid character '!' at position 4\n")

    def test_version_and_help(self):
        self.assertEqual(run("-v"), (0, f"b64 {base64hub.__version__}\n".encode(), ""))
        self.assertEqual(run("--version")[1], b"b64 1.0.0\n")
        for flag in ("-h", "--help"):
            code, out, err = run(flag)
            self.assertEqual((code, err), (0, ""))
            self.assertIn(b"\nUsage: b64 [flags] [TEXT]\n", out)
        self.assertEqual(run("a", "b", "-h")[0], 0)
        self.assertEqual(run("-x", "-h")[0], 2)

    def test_files(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.bin")
            dst = os.path.join(d, "out.txt")
            with open(src, "wb") as f:
                f.write(b"foobar")
            self.assertEqual(run("-i", src, "-o", dst), (0, b"", ""))
            with open(dst, "rb") as f:
                self.assertEqual(f.read(), b"Zm9vYmFy\n")
            back = os.path.join(d, "back.bin")
            self.assertEqual(run("--decode", "--input", dst, "--output", back)[0], 0)
            with open(back, "rb") as f:
                self.assertEqual(f.read(), b"foobar")
            self.assertEqual(run("-i", "-", stdin=b"foo")[1], b"Zm9v\n")
            self.assertEqual(run("-o", "-", "foo")[1], b"Zm9v\n")
            self.assertEqual(run("-", stdin=b"foo")[1], b"Zm9v\n")
            self.assertEqual(run("-i", "-", "-", stdin=b"foo")[1], b"Zm9v\n")
            self.assertEqual(run("--", "-")[1], b"LQ==\n")
            self.assertEqual(run("-i", d), (1, b"", f"b64: {d} is a directory\n"))
            self.assertEqual(run("-o", d, "x"), (1, b"", f"b64: open {d}: is a directory\n"))

    def test_same_file_for_input_and_output(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "data.txt")
            with open(f, "wb") as fh:
                fh.write(b"Zm9v")
            self.assertEqual(run("-d", "-i", f, "-o", f), (2, b"", f"b64: input and output are the same file: {f}\n"))
            with open(f, "rb") as fh:
                self.assertEqual(fh.read(), b"Zm9v")

    def test_failed_decode_leaves_no_output_file(self):
        with tempfile.TemporaryDirectory() as d:
            dst = os.path.join(d, "out.bin")
            self.assertEqual(run("-d", "-o", dst, "Zm9v!"), (1, b"", "b64: invalid character '!' at position 4\n"))
            self.assertFalse(os.path.exists(dst))
            with open(dst, "wb") as f:
                f.write(b"old")
            code, _, err = run("--validate", "-o", dst, "Zm9vY")
            self.assertEqual(code, 1)
            self.assertEqual(err, "invalid: invalid length: 5 characters leave a single character in the last group\n")
            self.assertFalse(os.path.exists(dst))


class ErrorsTest(unittest.TestCase):
    def assertError(self, args, code, message_part, stdin=b""):
        got_code, out, err = run(*args, stdin=stdin)
        self.assertEqual(got_code, code, err)
        self.assertEqual(out, b"")
        self.assertTrue(err.startswith("b64: "), err)
        self.assertTrue(err.endswith("\n"))
        self.assertEqual(err.count("\n"), 1, err)
        self.assertIn(message_part, err)

    def test_invalid_input_exits_1(self):
        self.assertError(["-d", "Zm9v!"], 1, "invalid character '!' at position 4")
        self.assertError(["-d", "Zm9vY"], 1, "invalid length")
        self.assertError(["-d", "Zm=9v"], 1, "unexpected '=' at position 2")
        self.assertError(["-d", "Zg==="], 1, "too much padding")
        self.assertError(["-d"], 1, "position 4", stdin=b"Zm9v\n\xff")
        missing = os.path.join(ROOT, "no-such-file")
        self.assertError(["-i", missing], 1, f"b64: open {missing}: no such file or directory\n")

    def test_usage_errors_exit_2(self):
        cases = [
            (["-dn", "x"], "unknown option -dn (short options can't be combined)"),
            (["-w76", "x"], "unknown option -w76 (short options can't be combined)"),
            (["-w=4", "x"], "unknown option -w=4 (short options can't be combined)"),
            (["-x"], "unknown option -x"),
            (["--nope=1"], "unknown option --nope"),
            (["--decode=1", "x"], "option --decode takes no value"),
            (["-o"], "option -o needs a value"),
            (["-w", "abc", "x"], 'option -w needs a whole number of 0 or more, got "abc"'),
            (["-w", "-1", "x"], 'option -w needs a whole number of 0 or more, got "-1"'),
            (["-w", "4\t", "x"], 'option -w needs a whole number of 0 or more, got "4\\t"'),
            (["-w", "99999999999999999999", "x"], 'option -w needs a whole number of 0 or more, got "99999999999999999999"'),
            (["--data-uri", "-m", "a b", "x"], 'option -m needs a MIME type like image/png, got "a b"'),
            (["--data-uri", "--mime=", "x"], 'option --mime needs a MIME type like image/png, got ""'),
            (["a", "b"], "too many arguments: expected one TEXT, got 2 (quote TEXT that contains spaces)"),
            (["-i", "f", "text"], "give either TEXT or --input, not both"),
            (["-i", "f", "-"], "give either TEXT or --input, not both"),
            (["-d", "--validate", "x"], "--decode and --validate can't be combined"),
            (["--wrap=+4", "-d", "x"], "--wrap only applies to encoding, not to --decode"),
            (["--validate", "-m", "a/b", "x"], "--mime only applies to encoding, not to --validate"),
            (["--data-uri", "-w", "4", "x"], "--wrap can't be combined with --data-uri: data URIs use standard padded Base64 on one line"),
            (["-m", "image/png", "x"], "--mime needs --data-uri"),
        ]
        for args, message in cases:
            with self.subTest(args=args):
                self.assertEqual(run(*args), (2, b"", f"b64: {message}\n"))


if __name__ == "__main__":
    unittest.main()
