"""Explicit translation of documented legacy file DTO variants.

No network access; endpoint/auth/status-code compatibility remains unverified.
Schema identifiers must be mapped per endpoint, not globally renamed.
"""
from dataclasses import dataclass
from typing import Literal, Mapping, Any


@dataclass(frozen=True)
class FileReference:
    filename: str
    url: str
    media_type: str | None = None
    size_bytes: int | None = None


def from_legacy_file(payload: Mapping[str, Any], *, contract: Literal['data_file', 'message', 'storage']) -> FileReference:
    if contract == 'data_file':
        filename, url = payload['filename'], payload['fileUrl']
    elif contract == 'message':
        filename, url = payload['fileName'], payload['messageFileURL']
    elif contract == 'storage':
        # Storage returns only a URL: caller supplies the original filename.
        filename, url = payload['fileName'], payload['url']
    else:
        raise ValueError('Unknown legacy file contract')
    if not isinstance(filename, str) or not filename.strip() or not isinstance(url, str) or not url.strip():
        raise ValueError('Filename and URL must be nonempty strings')
    size = payload.get('fileSize')
    size_bytes = None
    if size is not None:
        if isinstance(size, bool) or not isinstance(size, (str, int)):
            raise ValueError('File size must be an integer or digit string')
        size_bytes = int(size)
        if size_bytes < 0:
            raise ValueError('File size must not be negative')
    return FileReference(filename, url, payload.get('fileType'), size_bytes)
