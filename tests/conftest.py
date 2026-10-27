import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    """HOMES_ROOT temporar cu useri ana și bogdan, passwd fals, variabile de mediu setate."""
    homes = tmp_path / "homes"
    for u in ("ana", "bogdan"):
        (homes / u / "Photos").mkdir(parents=True)
    passwd = tmp_path / "passwd"
    passwd.write_text(
        "root:x:0:0::/root:/bin/sh\n"
        "ana:x:1030:100::/var/services/homes/ana:/sbin/nologin\n"
        "bogdan:x:1031:100::/var/services/homes/bogdan:/sbin/nologin\n"
    )
    data = tmp_path / "data"
    monkeypatch.setenv("POZE_HOMES_ROOT", str(homes))
    monkeypatch.setenv("POZE_DATA_DIR", str(data))
    monkeypatch.setenv("POZE_PASSWD_FILE", str(passwd))
    return {"homes": homes, "data": data, "passwd": passwd}


@pytest.fixture
def no_chown(monkeypatch):
    """Înlocuiește os.chown (testele rulează fără root) și înregistrează apelurile."""
    import os

    calls = []
    monkeypatch.setattr(os, "chown", lambda path, uid, gid: calls.append((str(path), uid, gid)))
    return calls


@pytest.fixture
def client(env):
    """Client HTTP pe aplicația FastAPI (fără indexare în fundal)."""
    from fastapi.testclient import TestClient

    from poze.app import create_app

    return TestClient(create_app(start_indexer=False))
