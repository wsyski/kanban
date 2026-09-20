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
import os


def pid_alive(held):
    """Is the pid a lockfile names still on this machine?

    A lock nobody holds is not a lock, so anything unreadable (empty file, a
    half-written pid, garbage) reads as dead: the file is only ever written with
    one pid, by os.write, immediately after creation.
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

    A DEAD holder's lockfile is taken over, not refused. The file survives any driver
    that did not exit through the interpreter (SIGTERM/SIGKILL skip the atexit unlink),
    and refusing on the file's existence alone turns one kill into a manual `rm` before
    the board can restart, while every other guard says the board is free (observed
    2026-09-12: start-board.sh's liveness check passed and run.py refused, so the restart
    silently did nothing).

    `note` is non-empty when a stale lock was taken over — the caller prints it in its
    own voice. A LIVE holder raises SystemExit with `why` after the pid: this is a
    refusal, never a wait.
    """
    os.makedirs(runs_dir, exist_ok=True)
    path = os.path.join(runs_dir, "driver.lock")
    note = ""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        held = open(path).read().strip()
        if pid_alive(held):
            raise SystemExit(f"another driver holds {path} (pid {held}) — {why}")
        note = f"taking over a stale driver lock ({path}: pid {held!r} is gone)"
        fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o644)
    mine = str(os.getpid())
    os.write(fd, mine.encode())
    os.close(fd)
    atexit.register(_release, path, mine)
    return path, note


def _release(path, mine):
    """Unlink the lock, but only while it is still OURS.

    A driver whose lock was taken over must not unlink its successor's: the takeover
    happens precisely because this process looked dead, and an unlink on existence
    alone would hand the board back to two drivers at once.
    """
    try:
        if open(path).read().strip() == mine:
            os.unlink(path)
    except OSError:
        pass
