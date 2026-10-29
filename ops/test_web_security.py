"""Run both real Nginx configs in disposable containers; no production services touched.

Usage: python3 ops/test_web_security.py (requires Docker).
"""

import json
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def docker(*args):
    result = subprocess.run(
        ["docker", *args], check=False, capture_output=True, timeout=90
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace")[:1500])
    return result.stdout.decode()


def check(config):
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    name = "metka-security-test-" + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="metka-nginx-") as directory:
        folder = Path(directory)
        root = folder / "html"
        root.mkdir()
        fixtures = {
            "index.html": "operator-shell",
            "citizens.html": "citizens-shell",
            ".env": "TEST_SECRET",
            ".git/config": "TEST_SECRET",
            "assets/.private": "TEST_SECRET",
            "api/.env": "TEST_SECRET",
            ".well-known/.env": "TEST_SECRET",
            "assets/test.js": "asset-ok",
            ".well-known/acme-challenge/test-token": "acme-ok",
            ".well-known/security.txt": "security-contact",
            "photo.jpg": "photo-ok",
            "version.json": "{}",
        }
        for path, body in fixtures.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
        (folder / "nginx.conf").write_text(
            "events {}\nhttp { include /etc/nginx/mime.types; access_log /dev/stdout; "
            "error_log /dev/stderr; include /etc/nginx/conf.d/default.conf; "
            'server { listen 8000; location / { return 200 "upstream-ok"; } } }'
        )
        try:
            docker(
                "run",
                "-d",
                "--name",
                name,
                "--add-host",
                "api:127.0.0.1",
                "--add-host",
                "appeals-api:127.0.0.1",
                "-p",
                "127.0.0.1::80",
                "-v",
                f"{folder / 'nginx.conf'}:/etc/nginx/nginx.conf:ro",
                "-v",
                f"{frontend / config}:/etc/nginx/conf.d/default.conf:ro",
                "-v",
                f"{frontend}:/etc/nginx/snippets:ro",
                "-v",
                f"{root}:/usr/share/nginx/html:ro",
                "nginx:1.27-alpine",
            )
            port = docker("port", name, "80/tcp").strip().rsplit(":", 1)[1]
            docker("exec", name, "nginx", "-t")

            def request(path, ip="198.51.100.10"):
                req = urllib.request.Request(
                    "http://127.0.0.1:" + port + path, headers={"X-Forwarded-For": ip}
                )
                try:
                    response = urllib.request.urlopen(req, timeout=5)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    return response.status, response.read().decode()

            for _ in range(30):
                try:
                    assert request("/")[0] == 200
                    break
                except (OSError, AssertionError):
                    time.sleep(0.1)
            else:
                raise AssertionError("Nginx did not become ready")
            denied = [
                "/.env",
                "/.env.local",
                "/.git/config",
                "/assets/.private",
                "/api/.env",
                "/.well-known/.env",
                "/%2eenv",
                "/.ENV",
                "/wp-admin/",
                "/wp-login.php",
                "/phpmyadmin/",
                "/vendor/phpunit/x",
            ]
            for i, path in enumerate(denied):
                status, body = request(path, f"198.51.100.{20 + i}")
                assert status == 403 and "TEST_SECRET" not in body, (
                    config,
                    path,
                    status,
                )
            burst = [
                request("/.env?private_marker=DO_NOT_LOG_THIS", "198.51.100.80")[0]
                for _ in range(20)
            ]
            assert burst.count(403) == 6 and burst.count(429) == 14, (config, burst)
            for _ in range(25):
                assert request("/", "198.51.100.80")[0] == 200
                assert request("/assets/test.js", "198.51.100.80") == (200, "asset-ok")
            for path, body in [
                ("/.well-known/acme-challenge/test-token", "acme-ok"),
                ("/.well-known/security.txt", "security-contact"),
                ("/photo.jpg", "photo-ok"),
            ]:
                assert request(path, "198.51.100.80") == (200, body)
            for path in [
                "/api/public/appeals/catalog",
                "/api/public/appeals/1/photos",
                "/a/123",
                "/a/123/card.jpg",
            ]:
                assert request(path, "198.51.100.81") == (200, "upstream-ok"), path
            if config == "nginx.conf":
                for path in [
                    "/api/health",
                    "/api/photos/1/original",
                    "/api/photos/export",
                    "/org/00000000-0000-0000-0000-000000000000/api/me",
                ]:
                    assert request(path) == (200, "upstream-ok"), path
                assert request("/workspace/deep-link") == (200, "operator-shell")
            else:
                assert request("/api/health")[0] == 404
                assert request("/missing-page")[0] == 404
            # All probe requests produce exactly one safe structured record, including rejections.
            logs = docker("logs", name)
            rows = [
                json.loads(line.partition("METKA_SECURITY_V1 ")[2])
                for line in logs.splitlines()
                if line.startswith("METKA_SECURITY_V1 ")
            ]
            assert len(rows) == len(denied) + len(burst), (config, len(rows))
            assert (
                sum(r["limit"] == "REJECTED" and r["status"] == 429 for r in rows) == 14
            )
            assert all(r["policy"] == "service-files-v1" for r in rows)
            assert "DO_NOT_LOG_THIS" not in logs and "TEST_SECRET" not in logs
            result = subprocess.run(
                ["docker", "logs", name], capture_output=True, check=True
            )
            assert b"DO_NOT_LOG_THIS" not in result.stderr
            return {
                "config": config,
                "denied_paths": len(denied),
                "burst_403": 6,
                "burst_429": 14,
                "normal_routes_ok": True,
                "private_log_ok": True,
            }
        finally:
            subprocess.run(
                ["docker", "rm", "-f", name], check=False, capture_output=True
            )


if __name__ == "__main__":
    print(
        json.dumps(
            [check("nginx.conf"), check("nginx-citizens.conf")], ensure_ascii=False
        )
    )
