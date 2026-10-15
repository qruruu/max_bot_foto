"""Pinned PaddleOCR weights. Download at image build time, never during photo processing."""

import hashlib
import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import urlopen

MODEL_SOURCE = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv5"
MODELS = (
    ("ch_PP-OCRv5_det_mobile.onnx", "det", "4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae"),
    ("eslav_PP-OCRv5_rec_mobile.onnx", "rec", "08705d6721849b1347d26187f15a5e362c431963a2a62bfff4feac578c489aab"),
)


def verified_models(directory: Path) -> tuple[Path, Path]:
    paths = []
    for filename, _, checksum in MODELS:
        path = directory / filename
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != checksum:
                raise ValueError("OCR_MODEL_CHECKSUM_MISMATCH")
        paths.append(path)
    return tuple(paths)


def download_models(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    for filename, task, checksum in MODELS:
        temporary = None
        try:
            with urlopen(f"{MODEL_SOURCE}/{task}/{filename}", timeout=60) as response:
                with NamedTemporaryFile(dir=directory, delete=False) as target:
                    temporary = Path(target.name)
                    digest, size = hashlib.sha256(), 0
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > 25 * 1024 * 1024:
                            raise ValueError("OCR_MODEL_TOO_LARGE")
                        digest.update(chunk)
                        target.write(chunk)
            if digest.hexdigest() != checksum:
                raise ValueError("OCR_MODEL_CHECKSUM_MISMATCH")
            temporary.chmod(0o644)
            os.replace(temporary, directory / filename)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    verified_models(directory)


if __name__ == "__main__":
    download_models(Path(sys.argv[1]))
