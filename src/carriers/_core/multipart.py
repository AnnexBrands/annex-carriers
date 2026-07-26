from __future__ import annotations

import uuid
from typing import Iterable, List, Optional, Tuple


def encode_multipart_form_data(
    fields: Iterable[Tuple[str, str, Optional[str]]],
    files: Iterable[Tuple[str, str, bytes, str]],
) -> Tuple[bytes, str]:
    """Encode multipart/form-data and return ``(body, content_type)``.

    ``fields`` entries are ``(name, value, content_type)``; ``files`` entries
    are ``(name, filename, content, content_type)``.
    """

    boundary = f"annex-carriers-{uuid.uuid4().hex}"
    chunks: List[bytes] = []

    for name, value, content_type in fields:
        chunks.append(f"--{boundary}\r\n".encode("ascii"))
        chunks.append(f'Content-Disposition: form-data; name="{_quote(name)}"\r\n'.encode("utf-8"))
        if content_type:
            chunks.append(f"Content-Type: {content_type}\r\n".encode("ascii"))
        chunks.append(b"\r\n")
        chunks.append(value.encode("utf-8"))
        chunks.append(b"\r\n")

    for name, filename, content, content_type in files:
        chunks.append(f"--{boundary}\r\n".encode("ascii"))
        disposition = (
            f'Content-Disposition: form-data; name="{_quote(name)}"; '
            f'filename="{_quote(filename)}"\r\n'
        )
        chunks.append(disposition.encode("utf-8"))
        chunks.append(f"Content-Type: {content_type}\r\n".encode("ascii"))
        chunks.append(b"\r\n")
        chunks.append(content)
        chunks.append(b"\r\n")

    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


__all__ = ["encode_multipart_form_data"]
