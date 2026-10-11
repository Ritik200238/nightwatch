"""The cached read-only pages, kept on disk so a restart does not start with none.

The page cache lived only in memory. After every deploy the first visitors found it empty and
each page was recomputed while they waited, under the analysis lock: measured after one restart,
/misses held the lock 31 s and a visitor's chat queued 24 s behind it; /sources took 117-126 s.
A saved page is now read back at start-up and served at once (as "stale") while the warm-up
recomputes it.

What a saved page is, and when it is not used:

* one file per cache key, written whole to a temporary name and renamed into place, so an
  interrupted write leaves the previous file or none, never half a page;
* only an answer that was served as a good one (HTTP 200) is ever saved, so a failed recompute
  never replaces a saved page;
* a page older than ``max_age_s`` (the same six hours the in-memory cache allows) is not used and
  is deleted;
* a page saved by a different API version or file format is not used: what a page contains can
  change between versions;
* a file that cannot be read, does not parse, or whose body length does not match its header is
  ignored and deleted.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

FORMAT = 1  # bump when the file layout changes


class PageStore:
    def __init__(self, folder: Path, *, version: str, max_age_s: float, max_files: int = 200, wall: Callable[[], float] = time.time) -> None:
        self.folder = folder
        self.version = version
        self.max_age_s = max_age_s
        self.max_files = max_files
        self._wall = wall
        self._seq = 0
        self._mu = threading.Lock()

    def _path(self, key: str) -> Path:
        return self.folder / (hashlib.sha256(key.encode("utf-8")).hexdigest()[:32] + ".page")

    def save(self, key: str, body: bytes, media: str) -> bool:
        """Keep one good answer. Never raises: not saving only costs the next restart its head start."""
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            meta = {"key": key, "saved_at": self._wall(), "media": media, "version": self.version, "format": FORMAT, "length": len(body)}
            with self._mu:
                self._seq += 1
                seq = self._seq
            final = self._path(key)
            tmp = final.with_name(f"{final.name}.{os.getpid()}.{seq}.tmp")
            with open(tmp, "wb") as fh:
                fh.write(json.dumps(meta, separators=(",", ":")).encode("utf-8") + b"\n" + body)
            os.replace(tmp, final)
            return True
        except Exception as exc:  # noqa: BLE001
            log.info("could not save page %s: %s", key, exc)
            return False

    def load(self, allowed: Callable[[str], bool]) -> dict[str, tuple[float, bytes, str]]:
        """Every usable saved page: key -> (age in seconds, body, media type). Newest first,
        at most ``max_files``. Leftover temporary files and unusable pages are deleted."""
        out: list[tuple[float, str, bytes, str]] = []
        try:
            entries = list(self.folder.iterdir())
        except FileNotFoundError:
            return {}
        except Exception as exc:  # noqa: BLE001
            log.info("could not list saved pages: %s", exc)
            return {}
        now = self._wall()
        for p in entries:
            if p.name.endswith(".tmp"):
                self._drop(p)  # an interrupted save
                continue
            if not p.name.endswith(".page"):
                continue
            try:
                raw = p.read_bytes()
                head, _, body = raw.partition(b"\n")
                meta = json.loads(head)
                key, saved_at, media = str(meta["key"]), float(meta["saved_at"]), str(meta["media"])
                usable = (
                    meta.get("format") == FORMAT and meta.get("version") == self.version and int(meta["length"]) == len(body)
                    and allowed(key) and p.name == self._path(key).name and 0 <= now - saved_at < self.max_age_s
                )
            except Exception:  # noqa: BLE001 - a damaged file is no page
                usable = False
            if not usable:
                self._drop(p)
                continue
            out.append((now - saved_at, key, body, media))
        out.sort(key=lambda x: x[0])
        return {key: (age, body, media) for age, key, body, media in out[: self.max_files]}

    @staticmethod
    def _drop(p: Path) -> None:
        try:
            p.unlink()
        except Exception:  # noqa: BLE001
            pass
