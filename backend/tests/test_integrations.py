import hashlib
import ssl
from unittest.mock import patch

import httpx
import pytest
import respx
from PIL import Image

from app.config import settings
from app.integrations import DownloadRejected, MaxClient, YandexDisk, download_file, safe_url
from app.media import analysis_jpeg, inspect_image
from app.recognition import TesseractOCR


@pytest.mark.parametrize(
    "url",
    [
        "http://cdn.max.ru/a",
        "https://cdn.max.ru:8080/a",
        "https://user:pass@cdn.max.ru/a",
        "https://max.ru.evil.example/a",
        "file:///tmp/a",
    ],
)
def test_unsafe_download_urls(url):
    with pytest.raises(DownloadRejected):
        safe_url(url, ("max.ru",))


def test_private_ip_rejected(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", lambda *_a, **_k: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(DownloadRejected):
        safe_url("https://cdn.max.ru/a", ("max.ru",))


@respx.mock
def test_max_tls_disabled_in_requests_and_downloads_only(monkeypatch, tmp_path):
    monkeypatch.setenv("MAX_VERIFY_TLS", "false")
    monkeypatch.setenv("MAX_BOT_TOKEN", "test-token")
    settings.cache_clear()
    monkeypatch.setattr("app.integrations.safe_url", lambda url, *_: url)
    respx.get("https://platform-api2.max.ru/me").mock(return_value=httpx.Response(200, json={}))
    respx.get("https://cdn.max.ru/a").mock(return_value=httpx.Response(200, content=b"image"))
    respx.get("https://download.yandex.net/a").mock(return_value=httpx.Response(200, content=b"image"))
    with patch("app.integrations.httpx.Client", wraps=httpx.Client) as clients:
        max_client = MaxClient()
        max_client.request("GET", "/me")
        assert clients.call_args.kwargs["verify"] is False
        max_client.download({"type": "image", "payload": {"url": "https://cdn.max.ru/a"}}, tmp_path / "max")
        assert clients.call_args.kwargs["verify"] is False
        download_file("https://download.yandex.net/a", tmp_path / "disk", ("yandex.net",))
        assert clients.call_args.kwargs["verify"] is True


def test_max_tls_can_be_explicitly_enabled(monkeypatch):
    monkeypatch.setenv("MAX_VERIFY_TLS", "true")
    settings.cache_clear()
    assert isinstance(MaxClient().verify, ssl.SSLContext)


@respx.mock
def test_max_authorization_and_reply(monkeypatch):
    monkeypatch.setenv("MAX_BOT_TOKEN", "secret-token")
    settings.cache_clear()
    route = respx.post("https://platform-api2.max.ru/messages").mock(
        return_value=httpx.Response(200, json={"message": {}})
    )
    MaxClient().reply(123, "mid", "✅ Принято")
    request = route.calls.last.request
    assert request.headers["Authorization"] == "secret-token"
    assert request.url.params["chat_id"] == "123"
    assert b'"type":"reply"' in request.content


@respx.mock
def test_yandex_upload_preserves_bytes_and_does_not_leak_oauth(monkeypatch, tmp_path):
    monkeypatch.setenv("YANDEX_DISK_TOKEN", "disk-secret")
    settings.cache_clear()
    monkeypatch.setattr("app.integrations.safe_url", lambda url, *_: url)
    content = b"original-bytes"
    original = tmp_path / "original"
    original.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    api = "https://cloud-api.yandex.net/v1/disk"
    meta = respx.get(api + "/resources").mock(
        side_effect=[httpx.Response(404), httpx.Response(200, json={"sha256": digest})]
    )
    respx.put(api + "/resources").mock(return_value=httpx.Response(201))
    respx.get(api + "/resources/upload").mock(
        return_value=httpx.Response(200, json={"href": "https://upload.yandex.net/signed"})
    )
    upload = respx.put("https://upload.yandex.net/signed").mock(return_value=httpx.Response(201))
    YandexDisk().upload(original, "disk:/MAX_PHOTOS/date/chat/name.jpg", digest)
    assert upload.calls.last.request.content == content
    assert "authorization" not in upload.calls.last.request.headers
    assert meta.calls.last.request.headers["authorization"] == "OAuth disk-secret"


@respx.mock
def test_yandex_async_move_and_idempotent_retry(monkeypatch):
    monkeypatch.setenv("YANDEX_DISK_TOKEN", "disk-secret")
    settings.cache_clear()
    monkeypatch.setattr("app.integrations.time.sleep", lambda _: None)
    api = "https://cloud-api.yandex.net/v1/disk"
    respx.get(api + "/resources").mock(
        side_effect=[
            httpx.Response(404),
            httpx.Response(200, json={"sha256": "digest"}),
            httpx.Response(200, json={"sha256": "digest"}),
        ]
    )
    respx.put(api + "/resources").mock(return_value=httpx.Response(201))
    move = respx.post(api + "/resources/move").mock(
        return_value=httpx.Response(202, json={"href": api + "/operations/123"})
    )
    op = respx.get(api + "/operations/123").mock(
        side_effect=[
            httpx.Response(200, json={"status": "in-progress"}),
            httpx.Response(200, json={"status": "success"}),
        ]
    )
    disk = YandexDisk()
    disk.move("disk:/old", "disk:/new/f.jpg", "digest")
    disk.move("disk:/old", "disk:/new/f.jpg", "digest")
    assert move.call_count == 1 and op.call_count == 2


@respx.mock
def test_download_limits_and_redirect_validation(monkeypatch, tmp_path):
    monkeypatch.setenv("MAX_FILE_BYTES", "10")
    settings.cache_clear()
    monkeypatch.setattr("app.integrations.safe_url", lambda url, *_: url)
    respx.get("https://cdn.max.ru/a").mock(return_value=httpx.Response(200, content=b"x" * 11))
    target = tmp_path / "original"
    with pytest.raises(DownloadRejected):
        download_file("https://cdn.max.ru/a", target, ("max.ru",))
    assert not target.exists() and not target.with_suffix(".part").exists()


@pytest.mark.parametrize(
    "fmt,ext",
    [
        ("PNG", ".png"),
        ("JPEG", ".jpg"),
        ("GIF", ".gif"),
        ("TIFF", ".tiff"),
        ("BMP", ".bmp"),
        ("WEBP", ".webp"),
    ],
)
def test_image_formats_and_first_frame(tmp_path, fmt, ext):
    path = tmp_path / "test"
    Image.new("RGB", (20, 20), "green").save(path, format=fmt)
    before = path.read_bytes()
    assert inspect_image(path)[0] == ext
    assert analysis_jpeg(path).startswith(b"\xff\xd8")
    assert path.read_bytes() == before


def test_real_ocr_if_available(tmp_path):
    import shutil

    if not shutil.which("tesseract"):
        pytest.skip("Tesseract binary not installed on this host; installed in Docker")
    from PIL import ImageDraw, ImageFont

    path = tmp_path / "stamp.png"
    img = Image.new("RGB", (1000, 220), "white")
    draw = ImageDraw.Draw(img)
    draw.text(
        (20, 20), "30.09.2026 11:43\n61.1060N 72.5780E", fill="black", font=ImageFont.load_default(size=48)
    )
    img.save(path)
    result = TesseractOCR().recognize(path)
    assert "30.09.2026" in result and "61.1060" in result
