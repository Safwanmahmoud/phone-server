"""Reading log files in pieces, so the browser can poll for whatever is new."""
from __future__ import annotations

from pathlib import Path

TAIL_BYTES = 64 * 1024
MAX_CHUNK = 256 * 1024


def read(path: Path, offset: int | None, *, tail: bool) -> dict:
    """Return text after `offset` and the offset to ask for next.

    With no offset, `tail` starts near the end of the file (app logs) instead of
    at the beginning (deploy logs). `reset` tells the client the file was cleared
    and it should drop what it has.
    """
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return {"text": "", "offset": 0, "reset": bool(offset), "more": False}

    reset = False
    if offset is None:
        start = max(0, size - TAIL_BYTES) if tail else 0
    elif offset > size:  # the file was truncated
        start, reset = 0, True
    else:
        start = offset

    with path.open("rb") as f:
        f.seek(start)
        data = f.read(min(size - start, MAX_CHUNK))
    end = start + len(data)

    if offset is None and start > 0:  # don't show half a line at the top
        nl = data.find(b"\n")
        data = data[nl + 1:] if nl >= 0 else data

    return {"text": data.decode(errors="replace"), "offset": end, "reset": reset, "more": end < size}
