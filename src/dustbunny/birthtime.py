"""When a folder was created ("birth time").

Python's os.stat() doesn't report it on Linux, so it is read with the statx()
system call through the C library. File systems that don't record it (NFS,
SMB, older ext3) give ``None``.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
from datetime import UTC, datetime

_AT_FDCWD = -100
_AT_SYMLINK_NOFOLLOW = 0x100
_STATX_BTIME = 0x800


class _Timestamp(ctypes.Structure):
    _fields_ = (("tv_sec", ctypes.c_int64), ("tv_nsec", ctypes.c_uint32), ("_pad", ctypes.c_int32))


class _Statx(ctypes.Structure):  # struct statx from <linux/stat.h>, 256 bytes
    _fields_ = (
        ("stx_mask", ctypes.c_uint32),
        ("stx_blksize", ctypes.c_uint32),
        ("stx_attributes", ctypes.c_uint64),
        ("stx_nlink", ctypes.c_uint32),
        ("stx_uid", ctypes.c_uint32),
        ("stx_gid", ctypes.c_uint32),
        ("stx_mode", ctypes.c_uint16),
        ("_spare0", ctypes.c_uint16),
        ("stx_ino", ctypes.c_uint64),
        ("stx_size", ctypes.c_uint64),
        ("stx_blocks", ctypes.c_uint64),
        ("stx_attributes_mask", ctypes.c_uint64),
        ("stx_atime", _Timestamp),
        ("stx_btime", _Timestamp),
        ("stx_ctime", _Timestamp),
        ("stx_mtime", _Timestamp),
        ("stx_rdev_major", ctypes.c_uint32),
        ("stx_rdev_minor", ctypes.c_uint32),
        ("stx_dev_major", ctypes.c_uint32),
        ("stx_dev_minor", ctypes.c_uint32),
        ("_spare2", ctypes.c_uint64 * 14),
    )


def _load_statx():
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
        statx = libc.statx
    except (OSError, AttributeError):
        return None
    statx.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.POINTER(_Statx),
    )
    statx.restype = ctypes.c_int
    return statx


_statx = _load_statx()


def birth_time(path: str) -> datetime | None:
    """Creation time of ``path`` (not following symlinks), or ``None`` if unknown."""
    if _statx is not None:
        buf = _Statx()
        flags = _AT_SYMLINK_NOFOLLOW
        if _statx(_AT_FDCWD, os.fsencode(path), flags, _STATX_BTIME, ctypes.byref(buf)) == 0:
            if buf.stx_mask & _STATX_BTIME and buf.stx_btime.tv_sec > 0:
                seconds = buf.stx_btime.tv_sec + buf.stx_btime.tv_nsec / 1e9
                return datetime.fromtimestamp(seconds, tz=UTC)
            return None
    try:  # macOS, BSD, Windows
        return datetime.fromtimestamp(os.lstat(path).st_birthtime, tz=UTC)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return None
