import os
from pathlib import Path


def db_path() -> Path:
    """The database lives outside the repo. ARGOS_DB overrides it (tests)."""
    override = os.environ.get("ARGOS_DB")
    if override:
        return Path(override)
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return data_home / "argos" / "argos.db"
