# OCR regression images

These are user-provided examples, not generated stamps. Photo fixtures are cropped from
screenshots to exclude form fields, so a test cannot mistakenly recognize the date already
entered in the interface. They do not replace validation on the original camera files.

- `russian_date_stamp.png`: supplied close-up, `20 апр. 2026 г.`.
- `camera_stamp_photo.png`: bench/bin screenshot, `20 апр. 2026 г. 09:33:34`.
- `camera_stamp_bin_092405.png`: first October 9 comparison screenshot, `20 апр. 2026 г. 09:24:05`.
- `camera_stamp_photo74.png`: second comparison screenshot (#74), `20 апр. 2026 г. 09:24:37`.
- `camera_stamp_photo87.png`: photo-only screenshot crop (#87), white text over the scene,
  `10 нояб. 2025 г. 10:45:19`, `61.08588936666667N 72.62705246666665E`.
- `camera_stamp_original_103007.png`: supplied 960×1280 photo, black panel,
  `20 апр. 2026 г. 10:30:07`, `61,1024N 72,5793E`.

The user's saved OCR for #74 reads `20 anp. 2026 r.` on its second pass; its relevant lines
are also retained in a text regression test. Real-image tests need Tesseract with `rus+eng`
installed, as in the service Docker image. Neural OCR regressions use bundled PP-OCRv5
weights (`OCR_MODEL_DIR`) and additionally resize and JPEG-compress the photos.
