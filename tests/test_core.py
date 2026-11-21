import json
import os
import unittest

from tests import ROOT

import base64hub
from base64hub import Base64Error, data_uri, decode, encode, sniff_mime, validate

with open(os.path.join(ROOT, "testdata", "vectors.json"), encoding="utf-8") as f:
    CASES = json.load(f)["cases"]


class VectorTest(unittest.TestCase):
    def test_vectors_present(self):
        ops = {c["op"] for c in CASES}
        self.assertEqual(ops, {"encode", "decode", "validate"})

    def test_encode(self):
        cases = [c for c in CASES if c["op"] == "encode"]
        self.assertTrue(cases)
        for i, c in enumerate(cases):
            with self.subTest(i=i, in_hex=c["in_hex"][:32], url=c["url"], pad=c["pad"], wrap=c["wrap"]):
                got = encode(bytes.fromhex(c["in_hex"]), url=c["url"], pad=c["pad"], wrap=c["wrap"])
                self.assertEqual(got, c["out"])

    def test_decode(self):
        cases = [c for c in CASES if c["op"] == "decode"]
        self.assertTrue(cases)
        for c in cases:
            with self.subTest(input=c["in"]):
                if c.get("error"):
                    with self.assertRaises(ValueError):
                        decode(c["in"])
                else:
                    self.assertEqual(decode(c["in"]).hex(), c["out_hex"])

    def test_validate(self):
        cases = [c for c in CASES if c["op"] == "validate"]
        self.assertTrue(cases)
        for c in cases:
            with self.subTest(input=c["in"]):
                r = validate(c["in"])
                self.assertEqual(r["valid"], c["valid"])
                if c["valid"]:
                    expected = {"valid": True, "variant": c["variant"], "padded": c["padded"], "bytes": c["bytes"]}
                    self.assertEqual(r, expected)
                else:
                    self.assertEqual(set(r), {"valid", "error"})
                    self.assertIsInstance(r["error"], str)
                    self.assertTrue(r["error"])


class ContractExamplesTest(unittest.TestCase):
    """The four documented examples, through the library."""

    def test_examples(self):
        self.assertEqual(encode("Hello, hub!"), "SGVsbG8sIGh1YiE=")
        self.assertEqual(decode("SGVsbG8sIGh1YiE="), b"Hello, hub!")
        self.assertEqual(encode(b"\xfb\xff\xbf", url=True), "-_-_")
        self.assertEqual(encode("Привет", url=True, pad=False), "0J_RgNC40LLQtdGC")


class EncodeTest(unittest.TestCase):
    def test_str_is_utf8(self):
        self.assertEqual(encode("é"), encode(b"\xc3\xa9"))

    def test_bytearray_and_memoryview(self):
        self.assertEqual(encode(bytearray(b"foo")), "Zm9v")
        self.assertEqual(encode(memoryview(b"foo")), "Zm9v")

    def test_wrap_no_trailing_newline(self):
        out = encode(b"x" * 57, wrap=76)
        self.assertFalse(out.endswith("\n"))
        self.assertEqual(len(out), 76)
        self.assertEqual(encode(b"x" * 58, wrap=76).count("\n"), 1)

    def test_bad_args(self):
        with self.assertRaises(ValueError):
            encode(b"x", wrap=-1)
        with self.assertRaises(TypeError):
            encode(b"x", wrap="4")
        with self.assertRaises(TypeError):
            encode(123)
        with self.assertRaises(TypeError):
            encode(b"x", True)


class DecodeTest(unittest.TestCase):
    def test_error_position_and_char(self):
        with self.assertRaises(Base64Error) as cm:
            decode("  Zm9v\n!abc")
        self.assertEqual(cm.exception.position, 4)
        self.assertEqual(cm.exception.char, "!")
        self.assertEqual(str(cm.exception), "invalid character '!' at position 4")
        self.assertIsInstance(cm.exception, ValueError)

    def test_messages_left_to_right(self):
        bs = "\\"
        cases = [
            ("Zm9v!", "invalid character '!' at position 4", 4),
            ("Zm=9v", "unexpected '=' at position 2: padding is only allowed at the end", 2),
            ("Zm9vY", "invalid length: 5 characters leave a single character in the last group", 4),
            ("Zg===", "too much padding: 3 '=' at position 2, at most 2 are allowed", 2),
            ("====", "too much padding: 4 '=' at position 0, at most 2 are allowed", 0),
            ("data:x;base64,Zm 9" + chr(0xE9), "invalid character '" + chr(0xE9) + "' at position 3", 3),
            ("Zm" + chr(0) + "v", f"invalid character '{bs}x00' at position 2", 2),
            ("Zm" + chr(11) + "v", f"invalid character '{bs}v' at position 2", 2),
            ("Zm'v", f"invalid character '{bs}'' at position 2", 2),
            # The first problem from the left wins.
            ("Zm9v!=YmFy", "invalid character '!' at position 4", 4),
            ("Zm=!", "unexpected '=' at position 2: padding is only allowed at the end", 2),
            ("Zm9vY!", "invalid character '!' at position 5", 5),
            ("Zm9vY===", "too much padding: 3 '=' at position 5, at most 2 are allowed", 5),
            # Whitespace is only space, tab, CR and LF.
            (chr(0xA0) + "Zg==", f"invalid character '{bs}u00a0' at position 0", 0),
            ("Zg" + chr(12), f"invalid character '{bs}f' at position 2", 2),
            # ";base64," is matched in lower case only.
            ("data:text/plain;BASE64,SGk=", "invalid character ':' at position 4", 4),
        ]
        for text, message, position in cases:
            with self.subTest(text=text):
                with self.assertRaises(Base64Error) as cm:
                    decode(text)
                self.assertEqual(str(cm.exception), message)
                self.assertEqual(cm.exception.position, position)
                self.assertEqual(validate(text), {"valid": False, "error": message})

    def test_invalid_utf8_byte(self):
        with self.assertRaises(Base64Error) as cm:
            decode(b"Zg\xff")
        self.assertEqual(str(cm.exception), "invalid character '\\xff' at position 2")

    def test_non_zero_trailing_bits_accepted(self):
        self.assertEqual(decode("Zh"), b"f")
        self.assertEqual(decode("Zm9"), b"fo")

    def test_bytes_input(self):
        self.assertEqual(decode(b"Zm9v"), b"foo")
        self.assertEqual(decode(bytearray(b"-_-_")), b"\xfb\xff\xbf")

    def test_data_prefix_needs_base64_marker(self):
        with self.assertRaises(Base64Error):
            decode("data:text/plain,hello")

    def test_round_trip_all_bytes(self):
        raw = bytes(range(256)) * 3
        for url in (False, True):
            for pad in (False, True):
                for wrap in (0, 4, 76):
                    with self.subTest(url=url, pad=pad, wrap=wrap):
                        self.assertEqual(decode(encode(raw, url=url, pad=pad, wrap=wrap)), raw)


class ValidateTest(unittest.TestCase):
    def test_shape(self):
        self.assertEqual(validate("Zm9v!"), {"valid": False, "error": "invalid character '!' at position 4"})
        self.assertEqual(validate("-_-_"), {"valid": True, "variant": "url", "padded": True, "bytes": 3})

    def test_padded(self):
        self.assertFalse(validate("Zg=")["padded"])
        self.assertTrue(validate("Zg==")["padded"])
        self.assertEqual(validate("=="), {"valid": True, "variant": "either", "padded": False, "bytes": 0})

    def test_whitespace_and_data_uri(self):
        self.assertEqual(validate(" \t\r\nZm9v YmFy\n")["bytes"], 6)
        self.assertEqual(validate("DATA:image/png;base64,iVBORw0KGgo=")["bytes"], 8)


class DataUriTest(unittest.TestCase):
    def test_sniffing(self):
        cases = [
            (b"\x89PNG\r\n\x1a\n\x00\x00", "image/png"),
            (b"\xff\xd8\xff\xe0\x00\x10JFIF", "image/jpeg"),
            (b"GIF89a\x01\x00", "image/gif"),
            (b"GIF87a\x01\x00", "image/gif"),
            (b"RIFF\x24\x00\x00\x00WEBPVP8 ", "image/webp"),
            (b"%PDF-1.7\n", "application/pdf"),
            (b'<svg xmlns="http://www.w3.org/2000/svg"/>', "image/svg+xml"),
            (b'<?xml version="1.0"?>\n<svg/>', "image/svg+xml"),
            (b'<?xml version="1.0"?>\n<note/>', "text/plain;charset=utf-8"),
            (b"Hello\tworld\r\n", "text/plain;charset=utf-8"),
            ("Привет".encode(), "text/plain;charset=utf-8"),
            (b"", "text/plain;charset=utf-8"),
            (b"hi\x00", "application/octet-stream"),
            (b"\x1b[0m", "application/octet-stream"),
            ("a\u0085".encode(), "application/octet-stream"),
            (b"\xff\xfe", "application/octet-stream"),
            (b" \n<svg/>", "image/svg+xml"),
            (b"<svg\xff", "image/svg+xml"),
            (b"\xef\xbb\xbf<svg/>", "text/plain;charset=utf-8"),
        ]
        for raw, mime in cases:
            with self.subTest(raw=raw):
                self.assertEqual(sniff_mime(raw), mime)

    def test_data_uri(self):
        self.assertEqual(data_uri(b"hi"), "data:text/plain;charset=utf-8;base64,aGk=")
        self.assertEqual(data_uri(b"hi", "text/x-test"), "data:text/x-test;base64,aGk=")
        long = data_uri(b"\x00" * 200)
        self.assertNotIn("\n", long)
        self.assertTrue(long.startswith("data:application/octet-stream;base64,AAAA"))

    def test_data_uri_decodes_back(self):
        raw = b"\x89PNG\r\n\x1a\nrest"
        self.assertEqual(decode(data_uri(raw)), raw)


class PackageTest(unittest.TestCase):
    def test_version(self):
        self.assertEqual(base64hub.__version__, "1.0.0")

    def test_py_typed(self):
        pkg_dir = os.path.dirname(base64hub.__file__)
        self.assertTrue(os.path.exists(os.path.join(pkg_dir, "py.typed")))


if __name__ == "__main__":
    unittest.main()
