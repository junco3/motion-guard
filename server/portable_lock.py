"""One-byte file locks on Windows (msvcrt) and Linux (fcntl), for the hosted Space."""
try:
    import msvcrt
except ImportError:
    msvcrt = None
    import fcntl


def lock(handle, blocking=True):
    """Lock the first byte; raises OSError when non-blocking and already held."""
    if msvcrt:
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
    else:
        fcntl.lockf(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB), 1, 0)


def unlock(handle):
    if msvcrt:
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.lockf(handle.fileno(), fcntl.LOCK_UN, 1, 0)
