# OCR regression images

These are user-provided examples, not generated stamps. Photo fixtures are cropped from
screenshots to exclude form fields, so a test cannot mistakenly recognize the date already
entered in the interface. They do not replace validation on the original camera files.

- `russian_date_stamp.png`: supplied close-up, `20 апр. 2026 г.`.
- `camera_stamp_photo.png`: bench/bin screenshot, `20 апр. 2026 г. 09:33:34`.
- `camera_stamp_bin_092405.png`: first October 9 comparison screenshot, `20 апр. 2026 г. 09:24:05`.
- `camera_stamp_photo74.png`: second comparison screenshot (#74), `20 апр. 2026 г. 09:24:37`.

The user's saved OCR for #74 reads `20 anp. 2026 r.` on its second pass; its relevant lines
are also retained in a text regression test. Real-image tests need Tesseract with `rus+eng`
installed, as in the service Docker image.
