import hashlib
from datetime import date, time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from app.config import settings
from app.ocr import LocalOCR, paddle_engine, stamp_regions, stamp_text
from app.ocr_models import download_models, verified_models
from app.parsers import CoordinateParser, DateTimeParser

FIXTURES = Path(__file__).parent / "fixtures"
METADATA = "20 апр.2026г. 10:30:07\n61,1024N72,5793E"


def setup_neural(monkeypatch, results):
    monkeypatch.setattr("app.ocr.analysis_image", lambda *_: Image.new("RGB", (100, 100)))
    monkeypatch.setattr("app.ocr.stamp_regions", lambda image: iter([image] * 3))
    recognize = Mock(side_effect=results)
    monkeypatch.setattr(LocalOCR, "_recognize", recognize)
    fallback = Mock(return_value="")
    monkeypatch.setattr("app.ocr.TesseractOCR.recognize", fallback)
    return recognize, fallback


def test_complete_stamp_stops_before_other_regions_and_fallback(monkeypatch):
    recognize, fallback = setup_neural(monkeypatch, [METADATA])
    text = LocalOCR().recognize(FIXTURES / "camera_stamp_original_103007.png")
    assert DateTimeParser().parse(text).photo_date == date(2026, 4, 20)
    assert CoordinateParser().parse(text).longitude == 72.5793
    assert recognize.call_count == 1
    fallback.assert_not_called()


def test_unavailable_neural_model_uses_local_fallback(monkeypatch):
    _, fallback = setup_neural(monkeypatch, [FileNotFoundError("weights unavailable")])
    fallback.return_value = METADATA
    assert LocalOCR().recognize(FIXTURES / "camera_stamp_original_103007.png") == METADATA
    assert 0 < fallback.call_args.kwargs["timeout"] <= settings().ocr_timeout


def test_fallback_failure_keeps_neural_reading(monkeypatch):
    _, fallback = setup_neural(monkeypatch, ["20 апр.2026г."] * 3)
    fallback.side_effect = RuntimeError("timeout")
    result = LocalOCR().recognize(FIXTURES / "russian_date_stamp.png")
    assert DateTimeParser().parse(result).photo_date == date(2026, 4, 20)


def test_conflicting_neural_readings_remain_unresolved(monkeypatch):
    setup_neural(monkeypatch, ["21 апр.2026г.", METADATA, METADATA])
    result = LocalOCR().recognize(FIXTURES / "camera_stamp_photo.png")
    assert DateTimeParser().parse(result).photo_date is None
    assert DateTimeParser().parse(result).photo_time == time(10, 30, 7)


def test_neural_passes_do_not_invent_coordinate_pair(monkeypatch):
    setup_neural(monkeypatch, ["61.1024N", "72.5793E", "20 апр.2026г."])
    assert CoordinateParser().parse(LocalOCR().recognize(FIXTURES / "camera_stamp_photo.png")).latitude is None


def test_decimal_degree_stamp_completes_on_first_neural_reading(monkeypatch):
    recognize, fallback = setup_neural(monkeypatch, ["19.10.2026 15:10\n61.0972° N, 72.6320 E"])
    text = LocalOCR().recognize(FIXTURES / "camera_stamp_photo.png")
    timestamp, coordinates = DateTimeParser().parse(text), CoordinateParser().parse(text)
    assert timestamp.photo_date == date(2026, 10, 19)
    assert timestamp.photo_time == time(15, 10)
    assert coordinates.latitude == pytest.approx(61.0972)
    assert coordinates.longitude == pytest.approx(72.6320)
    recognize.assert_called_once()
    fallback.assert_not_called()


def test_photo88_saved_readings_recover_metadata_without_truncated_time_conflict(monkeypatch):
    first = "14Hоя6.2025г.09:07.35\nC61 11892148333333N72.58083921666666E"
    highlighted = "14 нO96.2025г.09:07:35\n61.11892148333333N72.58083921666666E"
    recognize, fallback = setup_neural(monkeypatch, [first, highlighted])
    result = LocalOCR().recognize(FIXTURES / "camera_stamp_photo88.png")
    timestamp, coordinates = DateTimeParser().parse(result), CoordinateParser().parse(result)
    assert timestamp.photo_date == date(2025, 11, 14)
    assert timestamp.photo_time == time(9, 7, 35)
    assert coordinates.latitude == 61.11892148333333
    assert coordinates.longitude == 72.58083921666666
    assert recognize.call_count == 2
    fallback.assert_not_called()


def test_no_new_pass_starts_after_timeout(monkeypatch):
    recognize, fallback = setup_neural(monkeypatch, ["20 апр.2026г."])
    monkeypatch.setenv("OCR_TIMEOUT", "1")
    monkeypatch.setattr("app.ocr.monotonic", Mock(side_effect=[0, 0, 2, 2]))
    LocalOCR().recognize(FIXTURES / "russian_date_stamp.png")
    assert recognize.call_count == 1
    fallback.assert_not_called()


def test_tesseract_can_be_selected_without_loading_neural_model(monkeypatch):
    recognize, fallback = setup_neural(monkeypatch, [])
    monkeypatch.setenv("OCR_BACKEND", "tesseract")
    fallback.return_value = METADATA
    assert LocalOCR().recognize(FIXTURES / "camera_stamp_photo.png") == METADATA
    recognize.assert_not_called()


def test_adjacent_date_boxes_are_joined_by_geometry():
    def box(x, y, width):
        return [[x, y], [x + width, y], [x + width, y + 20], [x, y + 20]]

    result = SimpleNamespace(
        boxes=[box(0, 50, 300), box(35, 10, 80), box(0, 11, 25), box(120, 12, 100)],
        txts=("61.1024N72.5793E", "апр.", "20", "2026г."),
    )
    text = stamp_text(result)
    assert text == "20 апр. 2026г.\n61.1024N72.5793E"
    assert DateTimeParser().parse(text).photo_date == date(2026, 4, 20)
    assert CoordinateParser().parse(text).latitude == 61.1024


def test_black_stamp_is_selected_before_full_image():
    with Image.open(FIXTURES / "camera_stamp_original_103007.png") as image:
        regions = list(stamp_regions(image))
        assert regions[0].width < image.width * 0.6
        assert regions[0].height < image.height * 0.3
        assert regions[-1].size == image.size


def test_model_checksum_rejects_damaged_weights_without_download(tmp_path, monkeypatch):
    content = b"fixture weights"
    monkeypatch.setattr("app.ocr_models.MODELS", (
        ("det.onnx", "det", hashlib.sha256(content).hexdigest()),
        ("rec.onnx", "rec", hashlib.sha256(content).hexdigest()),
    ))
    for name in ("det.onnx", "rec.onnx"):
        (tmp_path / name).write_bytes(content)
    assert verified_models(tmp_path) == (tmp_path / "det.onnx", tmp_path / "rec.onnx")
    (tmp_path / "rec.onnx").write_bytes(b"damaged")
    with pytest.raises(ValueError, match="CHECKSUM"):
        verified_models(tmp_path)


def test_failed_model_download_preserves_existing_weights(tmp_path, monkeypatch):
    content = b"valid existing model"
    target = tmp_path / "model.onnx"
    target.write_bytes(content)
    monkeypatch.setattr("app.ocr_models.MODELS", (
        (target.name, "rec", hashlib.sha256(content).hexdigest()),
    ))
    monkeypatch.setattr("app.ocr_models.urlopen", lambda *_args, **_kwargs: BytesIO(b"damaged download"))
    with pytest.raises(ValueError, match="CHECKSUM"):
        download_models(tmp_path)
    assert target.read_bytes() == content
    assert list(tmp_path.iterdir()) == [target]


def test_engine_uses_explicit_local_models_and_cpu_limits(tmp_path, monkeypatch):
    import rapidocr

    paddle_engine.cache_clear()
    monkeypatch.setattr("app.ocr.verified_models", lambda _: (tmp_path / "det.onnx", tmp_path / "rec.onnx"))
    factory = Mock()
    monkeypatch.setattr(rapidocr, "RapidOCR", factory)
    try:
        assert paddle_engine(tmp_path, 2) is paddle_engine(tmp_path, 2)
        factory.assert_called_once()
        params = factory.call_args.kwargs["params"]
        assert params["Rec.model_path"] == str(tmp_path / "rec.onnx")
        assert params["Det.model_path"] == str(tmp_path / "det.onnx")
        assert params["EngineConfig.onnxruntime.intra_op_num_threads"] == 2
        assert params["EngineConfig.onnxruntime.inter_op_num_threads"] == 1
        assert params["Global.use_cls"] is False
    finally:
        paddle_engine.cache_clear()


@pytest.mark.ocr
@pytest.mark.parametrize("width", [1050, 700, 525])
@pytest.mark.parametrize(
    "filename,expected_date,expected_time,lat,lon",
    [
        ("camera_stamp_bin_092405.png", date(2026, 4, 20), time(9, 24, 5), 61.0839, 72.6306),
        ("camera_stamp_photo.png", date(2026, 4, 20), time(9, 33, 34), 61.0863, 72.6303),
        ("camera_stamp_photo74.png", date(2026, 4, 20), time(9, 24, 37), 61.0840, 72.6310),
        ("camera_stamp_original_103007.png", date(2026, 4, 20), time(10, 30, 7), 61.1024, 72.5793),
        ("camera_stamp_photo87.png", date(2025, 11, 10), time(10, 45, 19), 61.08588936666667, 72.62705246666665),
        ("camera_stamp_photo88.png", date(2025, 11, 14), time(9, 7, 35), 61.11892148333333, 72.58083921666666),
    ],
)
def test_real_camera_metadata(tmp_path, monkeypatch, width, filename, expected_date, expected_time, lat, lon):
    if not settings().ocr_model_dir.is_dir():
        pytest.skip("Bundled PaddleOCR models required; run inside the service image or set OCR_MODEL_DIR")
    monkeypatch.setattr("app.ocr.TesseractOCR.recognize", Mock(side_effect=AssertionError("Neural OCR must succeed")))
    with Image.open(FIXTURES / filename) as image:
        image = image.convert("RGB").resize((width, round(image.height * width / image.width)))
        path = tmp_path / "photo.jpg"
        image.save(path, quality=85)
    text = LocalOCR().recognize(path)
    timestamp, coordinates = DateTimeParser().parse(text), CoordinateParser().parse(text)
    assert timestamp.photo_date == expected_date, text
    assert timestamp.photo_time == expected_time, text
    assert coordinates.latitude == pytest.approx(lat, abs=0.000001), text
    assert coordinates.longitude == pytest.approx(lon, abs=0.000001), text
