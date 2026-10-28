import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    homes_root: Path
    data_dir: Path
    dsm_url: str
    port: int
    passwd_file: Path
    group_file: Path


def get_settings() -> Settings:
    """Citește variabilele de mediu la fiecare apel (testele le pot schimba)."""
    return Settings(
        homes_root=Path(os.environ.get("POZE_HOMES_ROOT", "/volume1/homes")),
        data_dir=Path(os.environ.get("POZE_DATA_DIR", "data")),
        dsm_url=os.environ.get("POZE_DSM_URL", "http://127.0.0.1:5000"),
        port=int(os.environ.get("POZE_PORT", "8090")),
        passwd_file=Path(os.environ.get("POZE_PASSWD_FILE", "/etc/passwd")),
        group_file=Path(os.environ.get("POZE_GROUP_FILE", "/etc/group")),
    )
