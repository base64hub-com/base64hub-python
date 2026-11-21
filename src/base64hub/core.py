"""Base64 encode, decode, validate and data URIs, per the base64hub shared core."""

from __future__ import annotations

import binascii
import re
from typing import Literal, Optional, TypedDict, Union

__all__ = [
    "Base64Error",
    "InvalidResult",
    "ValidResult",
    "ValidationResult",
    "encode",
    "decode",
    "validate",
    "data_uri",
    "sniff_mime",
]

BytesLike = Union[bytes, bytearray, memoryview]

_STD_TO_URL = str.maketrans("+/", "-_")
_URL_TO_STD = bytes.maketrans(b"-_", b"+/")

# Whitespace is exactly space, tab, CR and LF.
_SPACE = b" \t\r\n"
# The first byte that is neither whitespace nor a character of either alphabet.
_OTHER = re.compile(rb"[^A-Za-z0-9+/_\- \t\r\n]")
# After the first '=': the first byte that is neither '=' nor whitespace.
_AFTER_PAD = re.compile(rb"[^= \t\r\n]")
# The ";base64," of a data URI prefix is looked for within this many bytes, as in the Go build.
_HEADER_WINDOW = 64 * 1024


class Base64Error(ValueError):
    """Raised by :func:`decode` when the input is not valid Base64.

    ``position`` is the 0-based position the error points at in the cleaned
    input (whitespace and any data URI prefix removed): the bad character, the
    first ``=``, or the single character left in the last group. ``char`` is
    the offending character for an invalid character or a misplaced ``=``.
    """

    def __init__(self, message: str, position: Optional[int] = None, char: Optional[str] = None) -> None:
        super().__init__(message)
        self.position = position
        self.char = char


class ValidResult(TypedDict):
    valid: Literal[True]
    variant: str
    padded: bool
    bytes: int


class InvalidResult(TypedDict):
    valid: Literal[False]
    error: str


ValidationResult = Union[ValidResult, InvalidResult]


def _to_bytes(data: Union[str, BytesLike]) -> bytes:
    if isinstance(data, str):
        return data.encode("utf-8")
    if isinstance(data, (bytes, bytearray, memoryview)):
        return bytes(data)
    raise TypeError(f"expected bytes or str, got {type(data).__name__}")


def _text_bytes(text: Union[str, BytesLike]) -> bytes:
    if isinstance(text, str):
        try:
            # surrogateescape gives back the original bytes of undecodable input (sys.argv, os APIs).
            return text.encode("utf-8", "surrogateescape")
        except UnicodeEncodeError:
            return text.encode("utf-8", "surrogatepass")
    if isinstance(text, (bytes, bytearray, memoryview)):
        return bytes(text)
    raise TypeError(f"expected str or bytes, got {type(text).__name__}")


def _wrap(text: str, width: int) -> str:
    if width <= 0 or len(text) <= width:
        return text
    return "\n".join(text[i : i + width] for i in range(0, len(text), width))


def encode(data: Union[bytes, str], *, url: bool = False, pad: bool = True, wrap: int = 0) -> str:
    """Encode bytes (or the UTF-8 bytes of a str) as Base64 text.

    ``url`` uses the URL-safe alphabet (``-`` and ``_``), ``pad=False`` drops
    the trailing ``=``, ``wrap=N`` puts a newline after every N output
    characters (none at the end; 76 is MIME).
    """
    if isinstance(wrap, bool) or not isinstance(wrap, int):
        raise TypeError("wrap must be an int")
    if wrap < 0:
        raise ValueError("wrap must be 0 or greater")
    out = binascii.b2a_base64(_to_bytes(data), newline=False).decode("ascii")
    if url:
        out = out.translate(_STD_TO_URL)
    if not pad:
        out = out.rstrip("=")
    return _wrap(out, wrap)


def _payload_start(raw: bytes) -> int:
    """Index where the Base64 starts: after leading whitespace and, when the input
    starts with ``data:`` (any case), after the first ``;base64,`` (lower case)."""
    start = len(raw) - len(raw.lstrip(_SPACE))
    if raw[start : start + 5].lower() == b"data:":
        marker = raw.find(b";base64,", start, start + _HEADER_WINDOW)
        if marker != -1:
            return marker + len(b";base64,")
    return start


def _escape_rune(ch: str, quote: str) -> str:
    """One character escaped the way Go's strconv quoting does it."""
    if ch == quote or ch == "\\":
        return "\\" + ch
    if ch.isprintable():
        return ch
    o = ord(ch)
    named = {7: "a", 8: "b", 12: "f", 10: "n", 13: "r", 9: "t", 11: "v"}
    if o in named:
        return "\\" + named[o]
    if o < 0x20 or o == 0x7F:
        return f"\\x{o:02x}"
    if 0xD800 <= o <= 0xDFFF:
        o = 0xFFFD
    return f"\\u{o:04x}" if o < 0x10000 else f"\\U{o:08x}"


def _go_quote(raw: bytes) -> str:
    """Go's ``%q`` of a string: double quotes, Go escapes, invalid UTF-8 as ``\\xNN``."""
    out = []
    i = 0
    while i < len(raw):
        ch = _rune_at(raw, i)
        if ch is None:
            out.append(f"\\x{raw[i]:02x}")
            i += 1
        else:
            out.append(_escape_rune(ch, '"'))
            i += len(ch.encode("utf-8"))
    return '"' + "".join(out) + '"'


def _rune_at(raw: bytes, i: int) -> Optional[str]:
    """The UTF-8 character starting at ``raw[i]``, or None if no valid one starts there."""
    for n in range(1, 5):
        try:
            ch = raw[i : i + n].decode("utf-8")
        except UnicodeDecodeError:
            continue
        if len(ch) == 1:
            return ch
    return None


def _scan(raw: bytes) -> "tuple[bytes, bool]":
    """Find the first error left to right, like the Go build's streaming decoder.

    Returns ``(data, padded)``: the alphabet characters (whitespace, data URI
    prefix and padding removed) and whether the cleaned length, ``=`` included,
    is a multiple of 4. Raises :class:`Base64Error`.
    """
    payload = raw[_payload_start(raw) :]
    m = _OTHER.search(payload)
    end = m.start() if m else len(payload)
    data = payload[:end].translate(None, _SPACE)
    pos = len(data)  # position of the stop byte in the cleaned text
    pads = 0
    if m:
        if payload[end] != 0x3D:  # not '='
            ch = _rune_at(payload, end)
            shown = f"'{_escape_rune(ch, chr(39))}'" if ch is not None else f"'\\x{payload[end]:02x}'"
            if ch is None:
                ch = payload[end : end + 1].decode("utf-8", "surrogateescape")
            raise Base64Error(f"invalid character {shown} at position {pos}", pos, ch)
        if _AFTER_PAD.search(payload, end):
            raise Base64Error(
                f"unexpected '=' at position {pos}: padding is only allowed at the end", pos, "="
            )
        pads = payload.count(b"=", end)
        if pads > 2:
            raise Base64Error(f"too much padding: {pads} '=' at position {pos}, at most 2 are allowed", pos)
    if pos % 4 == 1:
        raise Base64Error(
            f"invalid length: {pos} characters leave a single character in the last group", pos - 1
        )
    return data, (pos + pads) % 4 == 0


def decode(text: Union[str, BytesLike]) -> bytes:
    """Decode Base64 text to bytes, leniently.

    Accepts both alphabets (even mixed), missing padding, spaces, tabs, CR and
    LF anywhere and a ``data:...;base64,`` prefix. Raises :class:`Base64Error`
    (a ``ValueError``) on anything else, for the first problem from the left.
    """
    data, _ = _scan(_text_bytes(text))
    if not data:
        return b""
    std = data.translate(_URL_TO_STD) + b"=" * (-len(data) % 4)
    # Non-strict a2b_base64 ignores non-zero trailing bits, as the contract wants.
    return binascii.a2b_base64(std)


def validate(text: Union[str, BytesLike]) -> ValidationResult:
    """Check Base64 text without raising.

    Valid: ``{"valid": True, "variant": ..., "padded": ..., "bytes": ...}`` with
    ``variant`` one of ``standard``, ``url``, ``mixed`` or ``either`` and
    ``bytes`` the decoded length. Invalid: ``{"valid": False, "error": ...}``
    with the message :func:`decode` would raise.
    """
    try:
        data, padded = _scan(_text_bytes(text))
    except Base64Error as exc:
        return {"valid": False, "error": str(exc)}
    std = b"+" in data or b"/" in data
    url = b"-" in data or b"_" in data
    variant = "mixed" if std and url else "standard" if std else "url" if url else "either"
    n = len(data)
    return {"valid": True, "variant": variant, "padded": padded, "bytes": n // 4 * 3 + max(n % 4 - 1, 0)}


def _is_text(raw: bytes) -> bool:
    try:
        s = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    for ch in s:
        o = ord(ch)
        if (o < 0x20 and ch not in "\t\r\n") or 0x7F <= o <= 0x9F:
            return False
    return True


def sniff_mime(data: Union[bytes, str]) -> str:
    """Guess a MIME type from magic bytes, as used by :func:`data_uri`."""
    raw = _to_bytes(data)
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw.startswith(b"%PDF-"):
        return "application/pdf"
    head = raw.lstrip(_SPACE)
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head):
        return "image/svg+xml"
    if _is_text(raw):
        return "text/plain;charset=utf-8"
    return "application/octet-stream"


def data_uri(data: Union[bytes, str], mime: Optional[str] = None) -> str:
    """Return ``data:<mime>;base64,<payload>`` (standard alphabet, padded, never wrapped).

    Without ``mime`` the type is sniffed from the bytes.
    """
    raw = _to_bytes(data)
    return f"data:{mime or sniff_mime(raw)};base64,{encode(raw)}"
