"""The board's ONE driver lock.

`runs/driver.lock` is what keeps two runs out of the same `work/`: whichever holds the
file runs that board. The rule lives here, in the layer the driver imports, because a
shared file with two implementations of one policy is an edit away from two behaviours
— and it already had two. run.py unlinked the lock in its atexit on the file's
EXISTENCE alone, so a driver that was SIGKILLed (and whose lock the next driver then
legitimately took over) would drop a lock that by then belonged to somebody else. The
rule below unlinks only its OWN.
"""
import atexit
import fcntl
import os


def pid_alive(held):
    """Is the pid a lockfile names still on this machine?

    Used only for the transition guard in `take` and by callers that want the
    question asked of a pid; who HOLDS the board is decided by the kernel lock, not
    by this. Anything unreadable (empty file, garbage) reads as dead.
    """
    try:
        pid = int(held)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:      # it exists, owned by someone else
        return True
    return True


def take(runs_dir, why):
    """Take `runs_dir/driver.lock`; return `(path, note)`.

    The lock is a KERNEL lock (`flock`) on the file, held for the life of this process;
    the pid written into the file is for the shell doors and the auditor to READ, never
    what decides who holds the board. Two older designs lost a live driver's board:
    creating the file empty and writing the pid two syscalls later let a reader inside
    that window read "" as a dead holder and truncate a LIVE lock (2026-09-23 review,
    Critical 2), and deciding a takeover from the pid let two starters that both saw the
    same dead pid both take the board (measured 2026-09-24: 27 of 30 trials). The kernel
    releases a flock when its holder dies, SIGKILL included, so a dead holder's file is
    taken over without anyone reading a pid, and a live one is refused whatever the file
    says.

    `note` is non-empty when a file left by an earlier holder was taken over — the
    caller prints it in its own voice. A live holder raises SystemExit with `why` after
    the pid: this is a refusal, never a wait.
    """
    global _held_fd
    os.makedirs(runs_dir, exist_ok=True)
    path = os.path.join(runs_dir, "driver.lock")
    while True:
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        except PermissionError as e:
            # Present and not ours to open: somebody else's lock, never "gone".
            raise SystemExit(f"{path} cannot be opened ({e.strerror}) — refusing to take "
                             f"a lock this process cannot account for — {why}")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            held = _read_fd(fd)
            os.close(fd)
            raise SystemExit(f"another driver holds {path} (pid {held or 'unknown'}) — {why}")
        # The file we locked must still be the one at `path`: a holder that released
        # between our open and our flock unlinked it, and a lock on an orphaned inode
        # would let a second starter lock the new file beside us.
        try:
            same = os.fstat(fd).st_ino == os.stat(path).st_ino
        except FileNotFoundError:
            same = False
        if same:
            break
        os.close(fd)
    held = _read_fd(fd)
    if _older_driver_alive(held):
        # Transition guard: a driver started before this lock was a flock holds no
        # kernel lock, so only its pid can say it is alive. Remove after one release.
        os.close(fd)
        raise SystemExit(f"another driver holds {path} (pid {held}, started before the "
                         f"flock lock) — {why}")
    note = f"taking over a stale driver lock ({path}: pid {held!r} is gone)" if held else ""
    mine = str(os.getpid())
    os.ftruncate(fd, 0)
    os.pwrite(fd, mine.encode(), 0)
    _held_fd = fd                     # open for the process lifetime: closing drops the lock
    atexit.register(_release, path, mine)
    return path, note


_held_fd = None


def _read_fd(fd):
    try:
        return os.pread(fd, 64, 0).decode(errors="replace").strip()
    except OSError:
        return ""


def _older_driver_alive(held):
    """Is `held` a live process whose argv names a `run.py`? Only a driver that
    predates the flock lock can be alive without holding it."""
    if not pid_alive(held):
        return False
    try:
        with open(f"/proc/{int(held)}/cmdline", "rb") as f:
            argv = f.read().split(b"\0")
    except (OSError, ValueError):
        return False
    return any(os.path.basename(a) == b"run.py" for a in argv)


def _release(path, mine):
    """Unlink the lock, but only while it is still OURS, then drop the flock.

    A driver whose lock was taken over must not unlink its successor's: the takeover
    happens precisely because this process looked dead, and an unlink on existence
    alone would hand the board back to two runs at once.
    """
    global _held_fd
    try:
        with open(path) as f:
            if f.read().strip() == mine:
                os.unlink(path)
    except OSError:
        pass
    if _held_fd is not None:
        try:
            os.close(_held_fd)
        except OSError:
            pass
        _held_fd = None
