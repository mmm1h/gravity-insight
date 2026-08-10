"""Runtime-safe HTTP content-encoding negotiation."""

from __future__ import annotations

from typing import Collection


_BASE_CONTENT_ENCODINGS = ("gzip", "deflate")
_OPTIONAL_CONTENT_ENCODINGS = ("br", "zstd")


def _load_optional_content_encodings() -> frozenset[str]:
    """Return optional encodings that urllib3 can actually decode."""

    try:
        from urllib3 import response as urllib3_response

        decoder_names = frozenset(urllib3_response.BaseHTTPResponse.CONTENT_DECODERS)
        decoder_factory = urllib3_response._get_decoder
    except Exception:
        return frozenset()

    supported: set[str] = set()
    for encoding in _OPTIONAL_CONTENT_ENCODINGS:
        if encoding not in decoder_names:
            continue
        try:
            decoder_factory(encoding)
        except Exception:
            continue
        supported.add(encoding)
    return frozenset(supported)


def _build_accept_encoding(
    optional_encodings: Collection[str] | None = None,
) -> str:
    try:
        supported = (
            _load_optional_content_encodings()
            if optional_encodings is None
            else frozenset(optional_encodings)
        )
    except Exception:
        supported = frozenset()
    encodings = _BASE_CONTENT_ENCODINGS + tuple(
        encoding for encoding in _OPTIONAL_CONTENT_ENCODINGS if encoding in supported
    )
    return ", ".join(encodings)


ACCEPT_ENCODING = _build_accept_encoding()
