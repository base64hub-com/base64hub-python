# base64hub

Base64 encode, decode and validate from Python or the shell. One small package, standard library only,
with a `b64` command that behaves the same as the base64hub CLI for Go and npm.

- **Lenient decoding**: standard and URL-safe alphabets (even mixed), missing padding, spaces, tabs
  and line breaks, `data:...;base64,` prefixes. Errors name the problem and its position.
- **Encoding options**: URL-safe alphabet (RFC 4648 §5), no padding, line wrapping (76 for MIME),
  data URIs with the MIME type sniffed from the bytes (PNG, JPEG, GIF, WebP, PDF, SVG, text).
- **Validation** that tells you the variant, whether it is padded and how many bytes it holds.
- Python 3.9 or newer, zero dependencies, type hints included.

Home page: [base64hub.com/pypi](https://base64hub.com/pypi/) · Docs: [base64hub.com/docs/python](https://base64hub.com/docs/python/) ·
Online tools: [base64hub.com](https://base64hub.com/)

## Install

As a command-line tool (isolated environment, puts `b64` on your PATH):

```sh
pipx install base64hub
```

As a library:

```sh
pip install base64hub
```

## Command line

```
b64 [flags] [TEXT]
```

With TEXT, `b64` works on its UTF-8 bytes; without it, it reads stdin (or `-i FILE`).

```console
$ b64 "Hello, hub!"
SGVsbG8sIGh1YiE=
$ b64 -d SGVsbG8sIGh1YiE=
Hello, hub!
$ printf '\xfb\xff\xbf' | b64 --url
-_-_
$ b64 --url --no-pad "Привет"
0J_RgNC40LLQtdGC
```

| Flag | Meaning |
|---|---|
| `-d`, `--decode` | decode (writes the raw bytes, nothing appended) |
| `-u`, `--url` | URL-safe alphabet, `-` and `_` (encode) |
| `-n`, `--no-pad` | no `=` padding (encode) |
| `-w N`, `--wrap N` | wrap encoded output every N characters; 0 = no wrap, 76 = MIME |
| `--data-uri` | output `data:<mime>;base64,...` (encode) |
| `-m TYPE`, `--mime TYPE` | MIME type for `--data-uri` (default: sniffed) |
| `--validate` | print `valid (<variant>, <bytes> bytes)`, or `invalid: <reason>` and exit 1 |
| `-i FILE`, `--input FILE` | read FILE instead of stdin (`-` = stdin) |
| `-o FILE`, `--output FILE` | write FILE instead of stdout (`-` = stdout) |
| `-h`, `--help` | help |
| `-v`, `--version` | print `b64 <version>` |

More examples:

```console
$ b64 -w 76 -i photo.jpg -o photo.b64
$ b64 -d -i photo.b64 -o photo.jpg
$ b64 --data-uri -i logo.png
data:image/png;base64,iVBORw0KGgo...
$ b64 --validate "SGVsbG8sIGh1YiE"
valid (either, 11 bytes)
$ b64 -d -- -_-_ | xxd -p
fbffbf
```

Flags may come before or after TEXT. Short flags can't be combined (`-d -n`, not `-dn`) and take
their value as the next argument (`-w 76`, not `-w76`); long flags also accept `--wrap=76`. Use `--`
before TEXT that starts with `-`, which URL-safe Base64 often does. A bare `-` as TEXT means stdin.

These are usage errors: encoding flags (`-u`, `-n`, `-w`, `--data-uri`, `-m`) with `-d` or
`--validate`; `-u`, `-n` or `-w` with `--data-uri` (data URIs are standard padded Base64 on one line);
`--mime` without `--data-uri`; TEXT together with `-i`; the same file for `-i` and `-o`.

Errors go to stderr as `b64: <message>`. Exit codes: `0` success, `1` invalid input or I/O error,
`2` usage error. When a run fails, a file written with `-o` is removed, so no partial output is left.
`b64` behaves exactly like the Go build of the command, the reference implementation.

The package installs the same command under a second name, `base64hub`, and runs as
`python -m base64hub` too.

## Library

```python
from base64hub import encode, decode, validate, data_uri

encode("Hello, hub!")                      # 'SGVsbG8sIGh1YiE='
encode(b"\xfb\xff\xbf", url=True)          # '-_-_'
encode("Привет", url=True, pad=False)      # '0J_RgNC40LLQtdGC'
encode(bytes(100), wrap=76)                # MIME lines, no trailing newline

decode("SGVsbG8sIGh1YiE")                  # b'Hello, hub!'  (padding optional)
decode("data:text/plain;base64,SGk=")      # b'Hi'
decode("a+b_")                             # b'k\xe6\xff'    (mixed alphabets)

validate("-_-_")
# {'valid': True, 'variant': 'url', 'padded': True, 'bytes': 3}
validate("Zm9v!")
# {'valid': False, 'error': "invalid character '!' at position 4"}

data_uri(b"hi")                            # 'data:text/plain;charset=utf-8;base64,aGk='
data_uri(png_bytes)                        # 'data:image/png;base64,...'
data_uri(svg_bytes, "image/svg+xml")       # MIME given explicitly
```

- `encode(data: bytes | str, *, url=False, pad=True, wrap=0) -> str`. A `str` is encoded as UTF-8 first.
- `decode(text: str | bytes) -> bytes` raises `base64hub.Base64Error`, a subclass of `ValueError`,
  for the first problem from the left. Its `position` attribute is the 0-based position in the
  cleaned input; for a bad character or a misplaced `=`, `char` is that character.
- `validate(text) -> dict` never raises. Valid input gives
  `{"valid": True, "variant": ..., "padded": ..., "bytes": ...}`: `variant` is `standard` (`+` or `/`
  seen), `url` (`-` or `_`), `mixed` (both) or `either` (neither); `padded` means the length with `=`
  is a multiple of 4; `bytes` is the decoded length. Invalid input gives
  `{"valid": False, "error": "<message decode would raise>"}`.
- `data_uri(data, mime=None) -> str` uses the standard alphabet with padding and never wraps.
  `sniff_mime(data)` returns the type it would pick.

### How decoding works

Whitespace means exactly space, tab, CR and LF; anything else, such as a no-break space, is an
invalid character.

1. Skip leading whitespace. If the input starts with `data:` (any case) and contains `;base64,`
   (lower case), drop everything up to and including `;base64,`.
2. Remove every space, tab, CR and LF.
3. Strip up to two trailing `=`; more, or `=` anywhere else, is an error.
4. Accept both alphabets; any other character is an error with its position.
5. A length that leaves one character over (length mod 4 = 1) is an error.

Errors are found left to right, positions count characters of the cleaned input from 0, and the
messages are exactly:

- `invalid character '!' at position 4`
- `unexpected '=' at position 2: padding is only allowed at the end`
- `too much padding: 3 '=' at position 2, at most 2 are allowed`
- `invalid length: 5 characters leave a single character in the last group`

## Links

- Package page: [base64hub.com/pypi](https://base64hub.com/pypi/)
- Documentation: [base64hub.com/docs/python](https://base64hub.com/docs/python/)
- Base64 tools in the browser: [base64hub.com](https://base64hub.com/)
- Source and issues: [github.com/base64hub-com/base64hub-python](https://github.com/base64hub-com/base64hub-python)

## License

MIT
