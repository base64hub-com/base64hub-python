"""The ``b64`` command: same flags, output and exit codes as the Go reference build."""

from __future__ import annotations

import os
import re
import stat
import sys
from typing import List, Optional

from . import __version__
from .core import Base64Error, _go_quote, _text_bytes, data_uri, decode, encode, validate

PROG = "b64"

EXIT_OK = 0
EXIT_INVALID = 1  # invalid input or I/O error
EXIT_USAGE = 2

HELP = f"""\
{PROG} – Base64 encode, decode and validate. https://base64hub.com/cli/

Usage: {PROG} [flags] [TEXT]

Encodes the UTF-8 bytes of TEXT or, without TEXT, standard input to Base64.

Flags:
  -d, --decode        decode Base64 to raw bytes (whitespace, either alphabet,
                      missing padding and a data: URI prefix are accepted)
  -u, --url           encode with the URL-safe alphabet (- and _)
  -n, --no-pad        encode without = padding
  -w, --wrap N        wrap encoded output every N characters (0 = off, 76 = MIME)
      --data-uri      encode as a data: URI, MIME type detected from the content
  -m, --mime TYPE     MIME type for --data-uri
      --validate      check the input and report its variant and decoded size
  -i, --input FILE    read FILE instead of standard input (- = stdin)
  -o, --output FILE   write FILE instead of standard output (- = stdout)
  -h, --help          show this help
  -v, --version       print the version
  --                  end of flags: the next argument is TEXT even if it starts with -

Exit status: 0 success, 1 invalid input or I/O error, 2 usage error.

Examples:
  {PROG} "Hello, hub!"                 SGVsbG8sIGh1YiE=
  {PROG} -d SGVsbG8sIGh1YiE=           Hello, hub!
  {PROG} --url --no-pad "Привет"       0J_RgNC40LLQtdGC
  {PROG} --validate -i token.txt
  {PROG} -w 76 -i photo.jpg -o photo.b64
  {PROG} --data-uri -i logo.png

Docs: https://base64hub.com/docs/python/
"""

_BOOL = {
    "-d": "decode",
    "--decode": "decode",
    "-u": "url",
    "--url": "url",
    "-n": "no_pad",
    "--no-pad": "no_pad",
    "--data-uri": "data_uri",
    "--validate": "validate",
    "-h": "help",
    "--help": "help",
    "-v": "version",
    "--version": "version",
}
_VALUE = {
    "-w": "wrap",
    "--wrap": "wrap",
    "-m": "mime",
    "--mime": "mime",
    "-i": "input",
    "--input": "input",
    "-o": "output",
    "--output": "output",
}

_WHOLE_NUMBER = re.compile(r"[+-]?[0-9]+")
_INT64_MAX = 2**63 - 1
# The characters Go's strings.TrimSpace removes (unicode.IsSpace).
_GO_SPACE = frozenset(
    map(chr, (9, 10, 11, 12, 13, 32, 0x85, 0xA0, 0x1680, *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000))
)


class UsageError(Exception):
    pass


class Failure(Exception):
    """A run error reported as ``b64: <message>`` with exit code 1."""


class Options:
    def __init__(self) -> None:
        self.decode = False
        self.url = False
        self.no_pad = False
        self.data_uri = False
        self.validate = False
        self.help = False
        self.version = False
        self.wrap = 0
        self.mime = ""
        self.mime_set = False
        self.input = ""  # "" and "-" both mean stdin
        self.output = ""  # "" and "-" both mean stdout
        self.text: Optional[str] = None


def parse_args(argv: List[str]) -> Options:
    """Flags and TEXT may come in any order; ``--`` ends the flags. Short flags
    take their value as the next argument and can't be combined; long flags also
    accept ``--name=value``."""
    opts = Options()
    positional: List[str] = []
    stdin_dash = False  # a bare "-" before "--" means standard input
    i = 0
    while i < len(argv):
        arg = argv[i]
        i += 1
        if arg == "--":
            positional.extend(argv[i:])
            break
        if arg == "-" or not arg.startswith("-"):
            if arg == "-" and not positional:
                stdin_dash = True
            positional.append(arg)
            continue
        name, has_value, value = arg, False, ""
        if arg.startswith("--") and "=" in arg:
            name, _, value = arg.partition("=")
            has_value = True
        if name in _BOOL:
            if has_value:
                raise UsageError(f"option {name} takes no value")
            setattr(opts, _BOOL[name], True)
        elif name in _VALUE:
            if not has_value:
                if i >= len(argv):
                    raise UsageError(f"option {name} needs a value")
                value = argv[i]
                i += 1
            _set_value(opts, name, _VALUE[name], value)
        elif not arg.startswith("--") and len(_text_bytes(arg)) > 2:
            raise UsageError(f"unknown option {arg} (short options can't be combined)")
        else:
            raise UsageError(f"unknown option {name}")
        if opts.help or opts.version:
            return opts

    if len(positional) == 1:
        if stdin_dash:
            if opts.input not in ("", "-"):
                raise UsageError("give either TEXT or --input, not both")
            opts.input = "-"
        else:
            if opts.input != "":
                raise UsageError("give either TEXT or --input, not both")
            opts.text = positional[0]
    elif len(positional) > 1:
        raise UsageError(
            f"too many arguments: expected one TEXT, got {len(positional)} (quote TEXT that contains spaces)"
        )

    if opts.decode and opts.validate:
        raise UsageError("--decode and --validate can't be combined")
    if opts.decode or opts.validate:
        mode = "--validate" if opts.validate else "--decode"
        for is_set, flag in (
            (opts.url, "--url"),
            (opts.no_pad, "--no-pad"),
            (opts.wrap > 0, "--wrap"),
            (opts.data_uri, "--data-uri"),
            (opts.mime_set, "--mime"),
        ):
            if is_set:
                raise UsageError(f"{flag} only applies to encoding, not to {mode}")
    if opts.data_uri:
        for is_set, flag in ((opts.url, "--url"), (opts.no_pad, "--no-pad"), (opts.wrap > 0, "--wrap")):
            if is_set:
                raise UsageError(
                    f"{flag} can't be combined with --data-uri: data URIs use standard padded Base64 on one line"
                )
    if opts.mime_set and not opts.data_uri:
        raise UsageError("--mime needs --data-uri")
    return opts


def _set_value(opts: Options, flag: str, attr: str, value: str) -> None:
    if attr == "wrap":
        n = int(value) if _WHOLE_NUMBER.fullmatch(value) else -1
        if not 0 <= n <= _INT64_MAX:
            raise UsageError(f"option {flag} needs a whole number of 0 or more, got {_go_quote(_text_bytes(value))}")
        opts.wrap = n
    elif attr == "mime":
        opts.mime = value
        opts.mime_set = True
        if all(c in _GO_SPACE for c in value) or any(c in " \t\r\n," for c in value):
            raise UsageError(f"option {flag} needs a MIME type like image/png, got {_go_quote(_text_bytes(value))}")
    else:
        setattr(opts, attr, value)


def _reason(exc: OSError) -> str:
    """The error text as Go prints it: the C library message, lower case first."""
    text = exc.strerror or str(exc)
    return text[:1].lower() + text[1:]


def _write_err(message: str) -> None:
    sys.stderr.flush()
    sys.stderr.buffer.write(_text_bytes(message))
    sys.stderr.buffer.flush()


def _open_input(opts: Options) -> Optional[int]:
    if opts.text is not None or opts.input in ("", "-"):
        return None
    try:
        fd = os.open(opts.input, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except OSError as exc:
        raise Failure(f"open {opts.input}: {_reason(exc)}") from None
    if stat.S_ISDIR(os.fstat(fd).st_mode):
        os.close(fd)
        raise Failure(f"{opts.input} is a directory")
    return fd


def _open_output(opts: Options):
    """Open the -o file. Returns ``(fd, removable)``: a regular (or new) file is
    removed again when the run fails, so no partial output is left behind."""
    if opts.output in ("", "-"):
        return None, False
    try:
        ost: Optional[os.stat_result] = os.stat(opts.output)
        missing = False
    except FileNotFoundError:
        ost, missing = None, True
    except OSError:
        ost, missing = None, False
    if ost is not None and opts.input not in ("", "-"):
        try:
            same = os.path.samestat(os.stat(opts.input), ost)
        except OSError:
            same = False
        if same:
            raise UsageError(f"input and output are the same file: {opts.output}")
    removable = missing or (ost is not None and stat.S_ISREG(ost.st_mode))
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    try:
        return os.open(opts.output, flags, 0o666), removable
    except OSError as exc:
        raise Failure(f"open {opts.output}: {_reason(exc)}") from None


def _read_input(opts: Options, fd: Optional[int]) -> bytes:
    if opts.text is not None:
        # surrogateescape restores the original bytes of a non-UTF-8 argument on POSIX.
        return _text_bytes(opts.text)
    try:
        if fd is None:
            return sys.stdin.buffer.read()
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    except OSError as exc:
        raise Failure(f"read {opts.input if fd is not None else '/dev/stdin'}: {_reason(exc)}") from None


def _transform(opts: Options, raw: bytes) -> Optional[bytes]:
    """The bytes to write, or None when --validate found the input invalid (already reported)."""
    if opts.validate:
        result = validate(raw)
        if not result["valid"]:
            _write_err(f"invalid: {result['error']}\n")
            return None
        return f"valid ({result['variant']}, {result['bytes']} bytes)\n".encode("ascii")
    if opts.decode:
        try:
            return decode(raw)
        except Base64Error as exc:
            raise Failure(str(exc)) from None
    if opts.data_uri:
        return (data_uri(raw, opts.mime or None) + "\n").encode("utf-8", "surrogateescape")
    return (encode(raw, url=opts.url, pad=not opts.no_pad, wrap=opts.wrap) + "\n").encode("ascii")


def _run(opts: Options) -> int:
    in_fd = _open_input(opts)
    out_fd: Optional[int] = None
    removable = False
    failed = True
    try:
        out_fd, removable = _open_output(opts)
        payload = _transform(opts, _read_input(opts, in_fd))
        if payload is None:
            return EXIT_INVALID
        if out_fd is None:
            sys.stdout.buffer.write(payload)
            sys.stdout.buffer.flush()
        else:
            try:
                view = memoryview(payload)
                while view:
                    view = view[os.write(out_fd, view) :]
            except OSError as exc:
                raise Failure(f"write {opts.output}: {_reason(exc)}") from None
        failed = False
        return EXIT_OK
    finally:
        if in_fd is not None:
            os.close(in_fd)
        if out_fd is not None:
            os.close(out_fd)
            if failed and removable:
                try:
                    os.remove(opts.output)
                except OSError:
                    pass


def main(argv: Optional[List[str]] = None) -> int:
    """Run the CLI and return the exit code."""
    if argv is None:
        argv = sys.argv[1:]
    try:
        opts = parse_args(argv)
        if opts.help:
            sys.stdout.buffer.write(HELP.encode("utf-8"))
            sys.stdout.buffer.flush()
            return EXIT_OK
        if opts.version:
            sys.stdout.buffer.write(f"{PROG} {__version__}\n".encode("utf-8"))
            sys.stdout.buffer.flush()
            return EXIT_OK
        return _run(opts)
    except UsageError as exc:
        _write_err(f"{PROG}: {exc}\n")
        return EXIT_USAGE
    except Failure as exc:
        _write_err(f"{PROG}: {exc}\n")
        return EXIT_INVALID
    except BrokenPipeError:
        # The reader went away (b64 ... | head). Silence the flush at exit.
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except OSError:
            pass
        return EXIT_INVALID
    except KeyboardInterrupt:
        return 130
