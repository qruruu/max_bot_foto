"""Real MAX and Yandex Disk adapters with separate TLS policies."""

import ipaddress
import os
import re
import socket
import ssl
import time
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlsplit

import httpx

from app.config import settings


class OriginalMissing(RuntimeError):
    """Neither the saved source nor the verified destination exists on Disk."""


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

    def __init__(self, folder_config=None):
        self.folder_config = folder_config

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        from app.disk_accounts import configured_token
        token = configured_token()
        if not token:
            raise RuntimeError("YANDEX_DISK_NOT_CONFIGURED")
        with httpx.Client(timeout=60) as client:
            response = client.request(
                method,
                self.API + path,
                headers={"Authorization": f"OAuth {token}"},
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
        if self.matches(target, digest):
            return
        if source == target or not self.matches(source, digest):
            raise OriginalMissing("ORIGINAL_MISSING")
        self.mkdirs(target.rsplit("/", 1)[0])
        response = self.request(
            "POST", "/resources/move", params={"from": source, "path": target, "overwrite": "false"}
        )
        if response.status_code == 404:
            # A move can finish before a retry, or the source can disappear after the preflight.
            if self.matches(target, digest):
                return
            if self.metadata(source) is None:
                raise OriginalMissing("ORIGINAL_MISSING")
        self.wait_operation(response)
        self.wait_for_file(target, digest)

    def wait_operation(self, response: httpx.Response):
        response.raise_for_status()
        if response.status_code != 202:
            return
        url = response.json()["href"]
        if not url.startswith(self.API + "/operations/"):
            raise RuntimeError("YANDEX_INVALID_OPERATION_URL")
        for _ in range(30):
            operation = self.request("GET", url.removeprefix(self.API))
            operation.raise_for_status()
            status = operation.json()["status"]
            if status == "success":
                return
            if status == "failed":
                raise RuntimeError("YANDEX_OPERATION_FAILED")
            time.sleep(1)
        raise RuntimeError("YANDEX_OPERATION_PENDING")

    def move_folder(self, source: str, target: str):
        src, dst = self.metadata(source), self.metadata(target)
        if src is None:
            return  # absent source, or a previous attempt already moved it
        if src.get("type") != "dir" or dst is not None:
            raise RuntimeError("YANDEX_FOLDER_MOVE_CONFLICT")
        self.mkdirs(target.rsplit("/", 1)[0])
        response = self.request(
            "POST", "/resources/move", params={"from": source, "path": target, "overwrite": "false"}
        )
        self.wait_operation(response)
        dst = self.metadata(target)
        if self.metadata(source) is not None or not dst or dst.get("type") != "dir":
            raise RuntimeError("YANDEX_FOLDER_MOVE_NOT_READY")

    def folder_items(self, path: str) -> list[dict] | None:
        """Read all pages before mutating a directory. None means it is already absent."""
        result, offset, expected_total = [], 0, None
        while True:
            response = self.request(
                "GET",
                "/resources",
                params={
                    "path": path,
                    "limit": 1000,
                    "offset": offset,
                    "fields": "type,_embedded.total,_embedded.items.path,_embedded.items.type,_embedded.items.sha256",
                },
            )
            if response.status_code == 404:
                if offset:
                    raise RuntimeError("YANDEX_FOLDER_CHANGED_DURING_LISTING")
                return None
            response.raise_for_status()
            document = response.json()
            if document.get("type") != "dir":
                raise RuntimeError("YANDEX_EXPECTED_SERVICE_FOLDER")
            embedded = document.get("_embedded", {})
            items, total = embedded.get("items"), embedded.get("total")
            if not isinstance(items, list) or type(total) is not int or total < 0:
                raise RuntimeError("YANDEX_INVALID_FOLDER_LISTING")
            if expected_total is not None and total != expected_total:
                raise RuntimeError("YANDEX_FOLDER_CHANGED_DURING_LISTING")
            expected_total = total
            result.extend(items)
            offset += len(items)
            if offset > total:
                raise RuntimeError("YANDEX_INVALID_FOLDER_LISTING")
            if offset == total:
                return result
            if not items:
                raise RuntimeError("YANDEX_INCOMPLETE_FOLDER_LISTING")

    def trash_legacy_exchange_folder(self, path: str, expected_files: dict[str, str]):
        """Retire only the two obsolete service trees; no active JSON or photo root is eligible."""
        from pathlib import PurePosixPath

        cfg = self.folder_config or settings()
        allowed = {
            f"disk:/{cfg.yandex_disk_root}/ARM_EXCHANGE",
            f"disk:/{cfg.exchange_folder}/legacy/ARM_EXCHANGE",
            f"disk:/{cfg.exchange_folder}/legacy",
        }
        if path not in allowed:
            raise ValueError("LEGACY_EXCHANGE_ROOT_NOT_ALLOWED")
        folders, files = [path], []
        for folder in folders:
            items = self.folder_items(folder)
            if items is None:
                continue
            for item in items:
                child = item.get("path", "")
                if (
                    not child.startswith(folder + "/")
                    or ".." in PurePosixPath(child).parts
                    or child in folders
                    or child in files
                ):
                    raise RuntimeError("YANDEX_INVALID_SERVICE_PATH")
                if item.get("type") == "dir":
                    folders.append(child)
                elif (
                    item.get("type") == "file"
                    and child.endswith(".json")
                    and expected_files.get(child)
                    and item.get("sha256") == expected_files[child]
                ):
                    files.append(child)
                else:
                    raise RuntimeError("LEGACY_EXCHANGE_UNMANAGED_FILE")
        # Check the bytes again after the full inventory, before retiring any part of the tree.
        for file in files:
            if not self.matches(file, expected_files[file]):
                raise RuntimeError("LEGACY_EXCHANGE_FILE_CHANGED")
        response = self.request("DELETE", "/resources", params={"path": path, "permanently": "false"})
        if response.status_code == 404:
            return
        self.wait_operation(response)
        if self.metadata(path) is not None:
            raise RuntimeError("YANDEX_DELETE_NOT_READY")

    def trash_empty_photo_folder(self, path: str):
        """Only empty photo descendants or numbered copies of our roots can go to trash."""
        cfg = self.folder_config or settings()
        roots = (cfg.yandex_disk_root, cfg.training_folder, cfg.spam_folder)
        copy_pattern = (
            r"disk:/(?:"
            + "|".join(re.escape(root) for root in (*roots, cfg.exchange_folder))
            + r") \([1-9]\d*\)"
        )
        eligible = any(path.startswith(f"disk:/{root}/") for root in roots) or re.fullmatch(
            copy_pattern, path
        )
        if str(PurePosixPath(path)) != path or ".." in PurePosixPath(path).parts or not eligible:
            raise ValueError("PHOTO_FOLDER_NOT_ALLOWED")
        if self.folder_items(path) != []:
            return  # A missing directory or any remaining file/subdirectory is never deleted.
        response = self.request("DELETE", "/resources", params={"path": path, "permanently": "false"})
        if response.status_code == 404:
            return
        self.wait_operation(response)
        if self.metadata(path) is not None:
            raise RuntimeError("YANDEX_DELETE_NOT_READY")

    def trash_exchange_file(self, path: str, digest: str):
        if not self.matches(path, digest):
            return
        response = self.request("DELETE", "/resources", params={"path": path, "permanently": "false"})
        if response.status_code == 404:
            return
        self.wait_operation(response)
        if self.metadata(path) is not None:
            raise RuntimeError("YANDEX_DELETE_NOT_READY")

    def download(self, source: str, target: Path):
        response = self.request("GET", "/resources/download", params={"path": source})
        response.raise_for_status()
        download_file(response.json()["href"], target, ("yandex.net", "yandex.ru", "yandex.com"))
