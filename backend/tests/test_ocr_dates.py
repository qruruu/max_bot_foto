import shutil
from datetime import date, time
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from app.parsers import CoordinateParser, DateTimeParser
from app.recognition import TesseractOCR

STAMP = Path(__file__).parent / "fixtures" / "russian_date_stamp.png"
PHOTO = Path(__file__).parent / "fixtures" / "camera_stamp_photo.png"
METADATA = "20 апр. 2026 г. 09:33:34\n61,0863N 72,6303E"


def mock_ocr(monkeypatch, results):
    monkeypatch.setattr("app.recognition.analysis_image", lambda *_: Image.new("RGB", (20, 20)))
    recognize = Mock(side_effect=results)
    monkeypatch.setattr("app.recognition.pytesseract.image_to_string", recognize)
    return recognize


def test_grayscale_retry_recovers_date_and_preserves_coordinates(monkeypatch):
    original = "20 апр. 202\n\n6.\n61.1060N 72.5780E"
    recognize = mock_ocr(monkeypatch, [original, "20 апр. 2026 г. 09:33:34"])
    text = TesseractOCR().recognize(STAMP)
    assert original in text
    assert DateTimeParser().parse(text).photo_date == date(2026, 4, 20)
    assert CoordinateParser().parse(text).latitude == 61.1060
    first, second = recognize.call_args_list
    assert first.args[0].mode == "RGB"
    assert second.args[0].mode == "L"
    assert 0 < second.kwargs["timeout"] <= first.kwargs["timeout"]


def test_complete_metadata_needs_only_one_pass(monkeypatch):
    recognize = mock_ocr(monkeypatch, [METADATA])
    assert TesseractOCR().recognize(STAMP) == METADATA
    assert recognize.call_count == 1


def test_grayscale_cannot_override_conflicting_dates(monkeypatch):
    mock_ocr(monkeypatch, ["20.04.2026 21.04.2026", METADATA, METADATA])
    assert DateTimeParser().parse(TesseractOCR().recognize(STAMP)).photo_date is None


@pytest.mark.parametrize("error", [RuntimeError("timeout"), OSError("unavailable")])
def test_failed_retry_preserves_initial_recognition(monkeypatch, error):
    mock_ocr(monkeypatch, ["61.1060N 72.5780E", error])
    assert TesseractOCR().recognize(STAMP) == "61.1060N 72.5780E"


def test_retry_respects_total_timeout(monkeypatch):
    recognize = mock_ocr(monkeypatch, ["61.1060N 72.5780E"])
    monkeypatch.setenv("OCR_TIMEOUT", "1")
    monkeypatch.setattr("app.recognition.monotonic", Mock(side_effect=[0, 2]))
    assert TesseractOCR().recognize(STAMP) == "61.1060N 72.5780E"
    assert recognize.call_count == 1


@pytest.mark.parametrize(
    "original",
    [
        "20 апр. 2026 г. 09:33:\n\n34\n61,0863N 72,6303E",
        "20 апр. 2026 г. 09:33:34\n61,0863N Ир",
    ],
)
def test_missing_time_or_coordinates_triggers_retry(monkeypatch, original):
    recognize = mock_ocr(monkeypatch, [original, METADATA])
    text = TesseractOCR().recognize(PHOTO)
    assert DateTimeParser().parse(text).photo_time == time(9, 33, 34)
    assert CoordinateParser().parse(text).longitude == 72.6303
    assert recognize.call_count == 2


def test_enlarged_block_pass_recovers_small_gps_line(monkeypatch):
    incomplete = "20 апр. 2026 г. 09:33:34\n61,0863М 72,6303Е"
    recognize = mock_ocr(monkeypatch, [incomplete, incomplete, METADATA])
    text = TesseractOCR().recognize(PHOTO)
    assert CoordinateParser().parse(text).latitude == 61.0863
    assert recognize.call_args.kwargs["config"] == "--psm 6"
    assert recognize.call_args.args[0].size == (40, 40)


@pytest.mark.parametrize(
    "original,field",
    [("09:34:34", "time"), ("62,0863N 72,6303E", "coordinates")],
)
def test_conflicting_retry_results_require_review(monkeypatch, original, field):
    mock_ocr(monkeypatch, [original, METADATA, METADATA])
    text = TesseractOCR().recognize(PHOTO)
    if field == "time":
        assert DateTimeParser().parse(text).photo_time is None
    else:
        assert CoordinateParser().parse(text).latitude is None


def test_no_coordinate_pair_is_invented_across_passes(monkeypatch):
    mock_ocr(monkeypatch, ["61,0863N", "72,6303E", ""])
    assert CoordinateParser().parse(TesseractOCR().recognize(PHOTO)).latitude is None


def test_photo74_server_ocr_recovers_date_on_second_pass(monkeypatch):
    # Relevant lines from the user's actual saved OCR, not a transcription of the image.
    first = "a\n\nnp. 202\n\nбг 09:24:37\n\n61,0840М 72,6310Е"
    second = "20 anp. 2026 r.\n\n9:24:37\n\n61,0840N 72,6310E"
    recognize = mock_ocr(monkeypatch, [first, second])
    text = TesseractOCR().recognize(PHOTO)
    timestamp = DateTimeParser().parse(text)
    coordinates = CoordinateParser().parse(text)
    assert timestamp.photo_date == date(2026, 4, 20)
    assert timestamp.photo_time == time(9, 24, 37)
    assert (coordinates.latitude, coordinates.longitude) == (61.0840, 72.6310)
    assert recognize.call_count == 2


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract is installed in the Docker image")
def test_real_russian_camera_stamp():
    text = TesseractOCR().recognize(STAMP)
    assert DateTimeParser().parse(text).photo_date == date(2026, 4, 20), text


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract is installed in the Docker image")
@pytest.mark.parametrize("width", [1050, 700, 525])
def test_real_camera_metadata_at_different_sizes(tmp_path, width):
    with Image.open(PHOTO) as original:
        image = original.resize((width, round(original.height * width / original.width)))
    path = tmp_path / "photo.png"
    image.save(path)
    text = TesseractOCR().recognize(path)
    timestamp = DateTimeParser().parse(text)
    coordinates = CoordinateParser().parse(text)
    assert timestamp.photo_date == date(2026, 4, 20), text
    assert timestamp.photo_time == time(9, 33, 34), text
    assert coordinates.latitude == pytest.approx(61.0863), text
    assert coordinates.longitude == pytest.approx(72.6303), text


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract is installed in the Docker image")
@pytest.mark.parametrize("width", [1050, 840, 700, 525])
@pytest.mark.parametrize(
    "filename,expected_time",
    [("camera_stamp_bin_092405.png", time(9, 24, 5)), ("camera_stamp_photo74.png", time(9, 24, 37))],
)
def test_april_stamp_dates_from_new_screenshots(tmp_path, width, filename, expected_time):
    with Image.open(STAMP.parent / filename) as original:
        image = original.resize((width, round(original.height * width / original.width)))
    path = tmp_path / "photo.png"
    image.save(path)
    text = TesseractOCR().recognize(path)
    timestamp = DateTimeParser().parse(text)
    assert timestamp.photo_date == date(2026, 4, 20), text
    assert timestamp.photo_time == expected_time, text
