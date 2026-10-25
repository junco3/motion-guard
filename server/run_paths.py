from pathlib import Path, PurePosixPath, PureWindowsPath


def run_file(folder, recorded):
    """A file a run record names by absolute path, found again inside the same run folder.

    Saved runs copied to another machine (the hosted Space) keep their original absolute
    paths; callers still verify the recorded SHA-256, so only the location is relaxed.
    """
    folder = Path(folder)
    path = Path(recorded)
    if path.is_file():
        return path
    name = PureWindowsPath(recorded).name if '\\' in str(recorded) else PurePosixPath(recorded).name
    return folder/name
