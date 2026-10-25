from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError

from app.appeal_images import prepare_photo, stamp_lines
from app.appeals import Capture


def frame(size=(1440, 1920), format="JPEG"):
    output = BytesIO()
    Image.new("RGB", size, "#87998d").save(output, format)
    return output.getvalue()


def capture(**kwargs):
    return Capture(captured_at=datetime(2026, 10, 23, 3, 29, tzinfo=UTC),
                   position_at=datetime(2026, 10, 23, 3, 29, tzinfo=UTC),
                   latitude=61.1025, longitude=72.5794, accuracy=8, **kwargs)


def test_stamp_matches_reference_and_original_stays_unmarked():
    metadata = capture()
    assert stamp_lines(metadata, "Asia/Yekaterinburg") == ("23.10.2026 08:29", "61,1025N 72,5794E")
    result = prepare_photo(frame(), metadata, "Asia/Yekaterinburg")
    with Image.open(BytesIO(result["original"])) as original, Image.open(BytesIO(result["stamped"])) as stamped:
        assert original.size == stamped.size == (1440, 1920)
        assert max(original.getpixel((1438, 1918))) > 80
        assert max(stamped.getpixel((1438, 1918))) < 15
        assert stamped.getpixel((10, 10)) == original.getpixel((10, 10))
    with Image.open(BytesIO(result["preview"])) as preview:
        assert max(preview.size) == 800
    assert result["width"] == 1440 and result["height"] == 1920


def test_negative_coordinates_keep_hemispheres():
    metadata = SimpleNamespace(captured_at=capture().captured_at, latitude=-12.123456, longitude=-77.98765)
    assert stamp_lines(metadata, "UTC")[1] == "12,1235S 77,9877W"


@pytest.mark.parametrize("content", [b"not an image", frame(format="PNG"), frame(size=(640, 480))])
def test_invalid_or_small_frames_are_rejected(content):
    with pytest.raises(HTTPException) as error:
        prepare_photo(content, capture(), "UTC")
    assert error.value.status_code == 422


@pytest.mark.parametrize("changes", [
    {"latitude": float("nan")}, {"longitude": 181}, {"accuracy": 101}, {"accuracy": 0},
    {"position_at": "2026-10-23T03:28:00Z"}, {"captured_at": "2026-10-23T03:29:00"},
])
def test_unusable_location_or_timestamp_is_rejected(changes):
    data = capture().model_dump()
    with pytest.raises(ValidationError):
        Capture.model_validate({**data, **changes})


@pytest.mark.ocr
@pytest.mark.parametrize("size", [(1440, 1920), (1920, 1080), (720, 1280)])
def test_camera_stamp_is_readable_by_existing_ocr(size, tmp_path, monkeypatch):
    from app.config import settings
    from app.ocr import LocalOCR
    from app.ocr_models import verified_models
    from app.parsers import CoordinateParser, DateTimeParser

    try:
        verified_models(settings().ocr_model_dir)
    except FileNotFoundError:
        pytest.skip("Pinned OCR weights required for the camera stamp regression")
    monkeypatch.setattr("app.recognition.TesseractOCR.recognize", lambda *_args, **_kwargs: pytest.fail("Neural OCR must read the generated stamp"))
    prepared = prepare_photo(frame(size), capture(), "Asia/Yekaterinburg")
    target = tmp_path / "stamped.jpg"
    target.write_bytes(prepared["stamped"])
    text = LocalOCR().recognize(target)
    date, coordinates = DateTimeParser().parse(text), CoordinateParser().parse(text)
    assert date.photo_date == capture().captured_at.date()
    assert str(date.photo_time) == "08:29:00"
    assert coordinates.latitude == 61.1025 and coordinates.longitude == 72.5794
