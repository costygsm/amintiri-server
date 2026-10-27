from pathlib import Path

from .config import get_settings


def uid_of(user: str) -> int:
    for line in get_settings().passwd_file.read_text().splitlines():
        parts = line.split(":")
        if len(parts) > 2 and parts[0] == user:
            return int(parts[2])
    # DSM rescrie passwd la fiecare cont nou (fișier nou), iar montarea din container rămâne pe cel vechi
    # până la repornire. Contul nou are însă folderul personal, al lui: îi luăm ID-ul de acolo.
    home = get_settings().homes_root / user
    try:
        st = home.lstat()
    except (FileNotFoundError, ValueError):
        raise KeyError(user) from None
    if not home.is_dir() or home.is_symlink() or st.st_uid < 1024:
        raise KeyError(user)
    return st.st_uid


def canonical(user: str) -> str:
    """Numele contului cum îl știe NAS-ul. DSM nu ține cont de majuscule („Dana” = „dana”), dar
    folderul personal și tokenurile au numele exact; fără potrivire, numele rămâne cum a venit."""
    names = [line.split(":", 1)[0] for line in get_settings().passwd_file.read_text().splitlines()]
    try:
        names += [p.name for p in get_settings().homes_root.iterdir()]
    except OSError:
        pass
    if user in names:
        return user
    return next((n for n in names if n.lower() == user.lower()), user)


def photos_root(user: str) -> Path:
    return get_settings().homes_root / user / "Photos"


def safe_path(user: str, rel: str) -> Path:
    """Rezolvă `rel` sub Photos-ul utilizatorului; ValueError dacă iese din el."""
    root = photos_root(user).resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"cale în afara folderului Photos: {rel}")
    return path


def ensure_photos(user: str) -> None:
    """Un cont nou de DSM n-are folderul Photos până nu deschide Synology Photos: îl facem la prima logare,
    al utilizatorului (nu al root-ului din container). Fără folder home (serviciul „User Home” oprit) nu facem nimic."""
    from . import naming  # naming importă users

    if (get_settings().homes_root / user).is_dir() and not photos_root(user).is_dir():
        naming._make_dirs(user, ".", uid_of(user))
