import pytest

from poze import db, users


def test_safe_path_inside(env):
    p = users.safe_path("ana", "2025/04-aprilie/x.jpg")
    assert p == env["homes"].resolve() / "ana/Photos/2025/04-aprilie/x.jpg"


def test_safe_path_rejects_escape(env):
    (env["homes"] / "ana/Photos/link").symlink_to(env["homes"] / "bogdan/Photos")
    for rel in ("../bogdan/Photos/x.jpg", "/etc/passwd", "link/x.jpg"):
        with pytest.raises(ValueError):
            users.safe_path("ana", rel)


def test_uid_of(env):
    assert users.uid_of("ana") == 1030
    assert users.uid_of("bogdan") == 1031
    with pytest.raises(KeyError):
        users.uid_of("nimeni")


def test_schema_created(env):
    conn = db.connect(env["data"])
    names = {r["name"] for r in conn.execute("select name from sqlite_master")}
    assert {"assets", "tokens", "uploads", "trash"} <= names


def test_uid_from_home_folder_when_passwd_is_stale(env, monkeypatch):
    import os

    from poze import users

    (env["homes"] / "dana").mkdir()
    real = os.stat(env["homes"] / "dana")
    monkeypatch.setattr(type(env["homes"]), "lstat", lambda self: type(real)(
        (real.st_mode, 0, 0, 1, 1033 if self.name == "dana" else 0, 100, 0, 0, 0, 0)))
    assert users.uid_of("dana") == 1033


def test_unknown_user_without_home_is_rejected(env):
    import pytest

    from poze import users

    with pytest.raises(KeyError):
        users.uid_of("nimeni")


def test_system_owned_folder_is_not_a_user(env):
    import pytest

    from poze import users

    (env["homes"] / "@eaDir").mkdir()  # al root-ului (uid sub 1024 în teste e uid-ul nostru — verificăm pragul)
    if os_uid() >= 1024:
        pytest.skip("rulat ca utilizator cu uid >= 1024")
    with pytest.raises(KeyError):
        users.uid_of("@eaDir")


def os_uid():
    import os

    return os.getuid()


def test_canonical_ignores_case(env):
    # DSM primește „Dana” la fel ca „dana”; folderul și tokenul trebuie să fie ale contului real
    assert users.canonical("Ana") == "ana"
    assert users.canonical("ANA") == "ana"
    assert users.canonical("ana") == "ana"
    assert users.canonical("nimeni") == "nimeni"
