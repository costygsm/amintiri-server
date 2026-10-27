import json



def test_app_latest_is_public(client, env):
    # linkul e pe pagina de logare: telefonul fără aplicație n-are încă un cont în ea
    assert client.get("/api/app/latest").status_code == 404
    apk = env["data"] / "apk"
    apk.mkdir(parents=True)
    (apk / "latest.json").write_text(json.dumps({"version_code": 3, "version_name": "0.3.0"}))
    r = client.get("/api/app/latest")
    assert r.json() == {"version_code": 3, "version_name": "0.3.0", "url": "/api/app/apk"}
    assert client.get("/api/app/apk").status_code == 404
    (apk / "amintiri.apk").write_bytes(b"PK\x03\x04apk")
    r = client.get("/api/app/apk")
    assert r.status_code == 200 and r.content == b"PK\x03\x04apk"
    assert r.headers["content-type"] == "application/vnd.android.package-archive"
