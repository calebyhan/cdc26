"""Small, dependency-light HTTP helpers with an on-disk cache and remote ZIP reads."""

from __future__ import annotations

import hashlib
import io
import json
import struct
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# Default urllib headers: the CFPB edge rejects unfamiliar custom User-Agent strings.
HEADERS: dict[str, str] = {}
RAW_DIR = Path("data/raw/atlas")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get(url: str, *, timeout: int = 120, headers: dict | None = None, retries: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url, headers={**HEADERS, **(headers or {})}
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except Exception as error:  # network errors are retried, then raised
            last = error
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET failed after {retries} attempts: {url}") from last


def get_json(url: str, **kwargs) -> dict:
    return json.loads(get(url, **kwargs))


def cached_download(url: str, path: Path, *, reuse: bool = True, timeout: int = 600) -> Path:
    """Download ``url`` to ``path`` once; later runs reuse the local copy."""
    if reuse and path.exists() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers=HEADERS)
    tmp = path.with_suffix(path.suffix + ".part")
    with urllib.request.urlopen(request, timeout=timeout) as response, tmp.open("wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
    tmp.replace(path)
    return path


class RangeFile(io.RawIOBase):
    """Seekable read-only view of a remote file using HTTP range requests."""

    def __init__(self, url: str, block: int = 4 << 20):
        self.url = url
        self.pos = 0
        self.block = block
        self.cache: dict[int, bytes] = {}
        request = urllib.request.Request(url, method="HEAD", headers=HEADERS)
        with urllib.request.urlopen(request, timeout=60) as response:
            self.size = int(response.headers["Content-Length"])

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        base = {0: 0, 1: self.pos, 2: self.size}[whence]
        self.pos = base + offset
        return self.pos

    def _block(self, index: int) -> bytes:
        if index not in self.cache:
            start = index * self.block
            end = min(self.size, start + self.block) - 1
            self.cache[index] = get(self.url, headers={"Range": f"bytes={start}-{end}"})
        return self.cache[index]

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = self.size - self.pos
        size = max(0, min(size, self.size - self.pos))
        out = bytearray()
        while size > 0:
            index = self.pos // self.block
            chunk = self._block(index)[self.pos - index * self.block :][:size]
            if not chunk:
                break
            out += chunk
            self.pos += len(chunk)
            size -= len(chunk)
        return bytes(out)

    def readinto(self, buffer) -> int:
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


def zip_directory(url: str) -> list[dict]:
    """Return member name, offset, and sizes from a remote ZIP's central directory."""
    archive = zipfile.ZipFile(RangeFile(url))
    return [
        {
            "name": info.filename,
            "offset": info.header_offset,
            "compressed": info.compress_size,
            "method": info.compress_type,
        }
        for info in archive.infolist()
    ]


def read_zip_member(url: str, member: dict) -> bytes:
    """Fetch and inflate one member with a single range request (supports Deflate64)."""
    name_len = len(member["name"].encode())
    # Local extra fields rarely exceed a few hundred bytes; over-read and trim.
    span = 30 + name_len + 1024 + member["compressed"]
    start = member["offset"]
    raw = get(url, headers={"Range": f"bytes={start}-{start + span - 1}"})
    local_name, local_extra = struct.unpack("<HH", raw[26:30])
    body_start = 30 + local_name + local_extra
    body = raw[body_start : body_start + member["compressed"]]
    method = member["method"]
    if method == 0:
        return body
    if method == 8:
        import zlib

        return zlib.decompress(body, -15)
    if method == 9:
        try:
            import inflate64
        except ImportError as error:  # pragma: no cover - optional pipeline extra
            raise RuntimeError("Deflate64 members need `uv sync --extra atlas`.") from error
        return inflate64.Inflater().inflate(body)
    raise RuntimeError(f"Unsupported ZIP compression method {method}")
