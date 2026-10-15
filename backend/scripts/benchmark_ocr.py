"""Compare local OCR on user fixtures. Run each engine in a separate process, without network."""

import argparse
import json
import os
import resource
import statistics
import sys
from pathlib import Path
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.parsers import CoordinateParser, DateTimeParser  # noqa: E402

CASES = (
    ("camera_stamp_bin_092405.png", "2026-04-20", "09:24:05", 61.0839, 72.6306),
    ("camera_stamp_original_103007.png", "2026-04-20", "10:30:07", 61.1024, 72.5793),
    ("camera_stamp_photo.png", "2026-04-20", "09:33:34", 61.0863, 72.6303),
    ("camera_stamp_photo74.png", "2026-04-20", "09:24:37", 61.0840, 72.6310),
    ("camera_stamp_photo87.png", "2025-11-10", "10:45:19", 61.08588936666667, 72.62705246666665),
    ("russian_date_stamp.png", "2026-04-20", None, None, None),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", choices=("paddle", "tesseract", "easyocr"))
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--easy-model-dir", type=Path)
    args = parser.parse_args()
    if args.repeat < 2:
        parser.error("Use at least two repetitions to separate first-photo and warm timings")
    os.environ.setdefault("OMP_THREAD_LIMIT", "2")
    start = monotonic()
    if args.engine == "paddle":
        from app.ocr import LocalOCR

        recognize = LocalOCR().recognize
    elif args.engine == "tesseract":
        from app.recognition import TesseractOCR

        recognize = TesseractOCR().recognize
    else:
        if args.easy_model_dir is None:
            parser.error("--easy-model-dir with pre-downloaded weights is required; downloads are disabled")
        import easyocr
        import torch

        torch.set_num_threads(2)
        reader = easyocr.Reader(
            ["ru", "en"], gpu=False, download_enabled=False,
            model_storage_directory=str(args.easy_model_dir), verbose=False,
        )

        def recognize(path):
            return "\n".join(reader.readtext(str(path), detail=0, paragraph=False))

    initialization_s = monotonic() - start
    records, warm_timings = [], []
    for filename, expected_date, expected_time, expected_lat, expected_lon in CASES:
        path = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / filename
        timings, readings = [], []
        for repetition in range(args.repeat):
            start = monotonic()
            text = recognize(path)
            timings.append(monotonic() - start)
            timestamp, coords = DateTimeParser().parse(text), CoordinateParser().parse(text)
            readings.append({
                "date": timestamp.photo_date.isoformat() if timestamp.photo_date else None,
                "time": timestamp.photo_time.isoformat() if timestamp.photo_time else None,
                "lat": coords.latitude, "lon": coords.longitude,
            })
            if repetition:
                warm_timings.append(timings[-1])
        correct = all(
            reading["date"] == expected_date and reading["time"] == expected_time
            and all(
                actual is None if expected is None else actual is not None and abs(actual - expected) < 0.000001
                for actual, expected in ((reading["lat"], expected_lat), (reading["lon"], expected_lon))
            )
            for reading in readings
        )
        records.append({"file": filename, "correct": correct, "seconds": timings, "readings": readings})
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    cgroup_peak = Path("/sys/fs/cgroup/memory.peak")
    result = {
        "engine": args.engine, "platform": sys.platform, "initialization_s": initialization_s,
        "correct_cases": sum(record["correct"] for record in records), "total_cases": len(CASES),
        "warm_median_s": statistics.median(warm_timings),
        "process_peak_rss_mib": peak_rss / (1024 * 1024 if sys.platform == "darwin" else 1024),
        "container_peak_mib": int(cgroup_peak.read_text()) / 1024**2 if cgroup_peak.exists() else None,
        "records": records,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
