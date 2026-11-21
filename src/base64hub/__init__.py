"""base64hub: Base64 encode, decode and validate, plus the ``b64`` command.

Lenient decoding (both alphabets, missing padding, whitespace, data URIs),
URL-safe and unpadded encoding, MIME line wrapping and data URIs.
Standard library only. https://base64hub.com/docs/python/
"""

from .core import (
    Base64Error,
    InvalidResult,
    ValidationResult,
    ValidResult,
    data_uri,
    decode,
    encode,
    sniff_mime,
    validate,
)

__version__ = "1.0.0"

__all__ = [
    "Base64Error",
    "InvalidResult",
    "ValidResult",
    "ValidationResult",
    "__version__",
    "data_uri",
    "decode",
    "encode",
    "sniff_mime",
    "validate",
]
