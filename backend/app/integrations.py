"""Real MAX and Yandex Disk adapters with separate TLS policies."""

import ipaddress
import os
import socket
import ssl
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from app.config import settings


class DownloadRejected(ValueError):
    pass


def safe_url(url: str, allowed_hosts: tuple[str, ...] = ()) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise DownloadRejected("HTTPS URL required")
    if allowed_hosts and not any(host == x or host.endswith("." + x) for x in allowed_hosts):
        raise DownloadRejected("Download domain is not allowed")
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(x[4][0]).is_global for x in addresses):
        raise DownloadRejected("Non-public download address")
    return url


def download_file(
    url: str, target: Path, allowed_hosts: tuple[str, ...], verify: ssl.SSLContext | bool = True
):
    """Streaming bounded download; redirects are validated individually and carry no token."""
    temp = target.with_suffix(".part")
    try:
        with httpx.Client(
            timeout=httpx.Timeout(60, connect=15), verify=verify, follow_redirects=False
        ) as client:
            for _ in range(6):
                safe_url(url, allowed_hosts)
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = urljoin(url, response.headers["location"])
                        continue
                    response.raise_for_status()
                    if int(response.headers.get("content-length", "0")) > settings().max_file_bytes:
                        raise DownloadRejected("File too large")
                    size = 0
                    with temp.open("wb") as out:
                        for chunk in response.iter_bytes(64 * 1024):
                            size += len(chunk)
                            if size > settings().max_file_bytes:
                                raise DownloadRejected("File too large")
                            out.write(chunk)
                        out.flush()
                        os.fsync(out.fileno())
                    os.replace(temp, target)
                    return
            raise DownloadRejected("Too many redirects")
    finally:
        temp.unlink(missing_ok=True)


class MaxClient:
    def __init__(self):
        cfg = settings()
        self.verify: ssl.SSLContext | bool = False
        if cfg.max_verify_tls:
            self.verify = ssl.create_default_context()
            if cfg.max_ca_bundle:
                self.verify.load_verify_locations(cfg.max_ca_bundle)

    def request(self, method, path, **kwargs):
        cfg = settings()
        if not cfg.max_bot_token:
            raise RuntimeError("MAX_NOT_CONFIGURED")
        with httpx.Client(timeout=45, verify=self.verify) as client:
            response = client.request(
                method,
                cfg.max_api_url.rstrip("/") + path,
                headers={"Authorization": cfg.max_bot_token},
                **kwargs,
            )
            response.raise_for_status()
            result = response.json()
            if result.get("success") is False:
                raise RuntimeError("MAX_API_UNSUCCESSFUL")
            return result

    def reply(self, chat_id: int, message_id: str, text: str):
        return self.request(
            "POST",
            "/messages",
            params={"chat_id": chat_id},
            json={"text": text, "link": {"type": "reply", "mid": message_id}},
        )

    def refresh_attachment(self, message_id: str, index: int) -> dict:
        message = self.request("GET", f"/messages/{message_id}")
        return message["body"]["attachments"][index]

    def download(self, attachment: dict, target: Path):
        url = (attachment.get("payload") or {}).get("url")
        if not url:
            raise RuntimeError("MAX_ATTACHMENT_URL_MISSING")
        hosts = tuple(h.strip() for h in settings().max_download_hosts.split(",") if h.strip())
        if not hosts:
            raise RuntimeError("MAX_DOWNLOAD_HOSTS_REQUIRED")
        download_file(url, target, hosts, self.verify)

    def subscribe(self, url: str):
        if not url.startswith("https://") or len(settings().max_webhook_secret) < 32:
            raise ValueError("HTTPS and a 32+ character webhook secret are required")
        return self.request(
            "POST",
            "/subscriptions",
            json={"url": url, "update_types": ["message_created"], "secret": settings().max_webhook_secret},
        )


class YandexDisk:
    API = "https://cloud-api.yandex.net/v1/disk"

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if not settings().yandex_disk_token:
            raise RuntimeError("YANDEX_DISK_NOT_CONFIGURED")
        with httpx.Client(timeout=60) as client:
            response = client.request(
                method,
                self.API + path,
                headers={"Authorization": f"OAuth {settings().yandex_disk_token}"},
                **kwargs,
            )
        return response

    def metadata(self, path: str) -> dict | None:
        response = self.request("GET", "/resources", params={"path": path, "fields": "type,sha256,size,path"})
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def matches(self, path: str, digest: str) -> bool:
        meta = self.metadata(path)
        if meta is None:
            return False
        if meta.get("sha256") != digest:
            raise RuntimeError("YANDEX_DESTINATION_CONFLICT")
        return True

    def mkdirs(self, path: str):
        current = "disk:"
        for part in path.removeprefix("disk:").strip("/").split("/"):
            current += "/" + part
            response = self.request("PUT", "/resources", params={"path": current})
            if response.status_code == 409:
                meta = self.metadata(current)
                if not meta or meta.get("type") != "dir":
                    raise RuntimeError("YANDEX_FOLDER_CONFLICT")
            else:
                response.raise_for_status()

    def wait_for_file(self, path: str, digest: str):
        # 202 means accepted by the uploader, not durable completion on Disk.
        for _ in range(12):
            if self.matches(path, digest):
                return
            time.sleep(1)
        raise RuntimeError("YANDEX_FILE_NOT_READY")

    def upload(self, original: Path, target: str, digest: str):
        if self.matches(target, digest):
            return
        self.mkdirs(target.rsplit("/", 1)[0])
        response = self.request("GET", "/resources/upload", params={"path": target, "overwrite": "false"})
        response.raise_for_status()
        url = safe_url(response.json()["href"], ("yandex.net", "yandex.ru", "yandex.com"))
        # OAuth stays on cloud-api; pre-signed storage URLs receive no credentials.
        with httpx.Client(timeout=180) as client, original.open("rb") as file:
            uploaded = client.put(url, content=file, headers={"Content-Length": str(original.stat().st_size)})
            uploaded.raise_for_status()
        self.wait_for_file(target, digest)

    def move(self, source: str, target: str, digest: str):
        if source == target or self.matches(target, digest):
            return
        self.mkdirs(target.rsplit("/", 1)[0])
        response = self.request(
            "POST", "/resources/move", params={"from": source, "path": target, "overwrite": "false"}
        )
        response.raise_for_status()
        if response.status_code == 202:
            url = response.json()["href"]
            prefix = self.API + "/operations/"
            if not url.startswith(prefix):
                raise RuntimeError("YANDEX_INVALID_OPERATION_URL")
            for _ in range(15):
                operation = self.request("GET", url.removeprefix(self.API))
                operation.raise_for_status()
                status = operation.json()["status"]
                if status == "success":
                    break
                if status == "failed":
                    raise RuntimeError("YANDEX_MOVE_FAILED")
                time.sleep(1)
        self.wait_for_file(target, digest)

    def download(self, source: str, target: Path):
        response = self.request("GET", "/resources/download", params={"path": source})
        response.raise_for_status()
        download_file(response.json()["href"], target, ("yandex.net", "yandex.ru", "yandex.com"))
