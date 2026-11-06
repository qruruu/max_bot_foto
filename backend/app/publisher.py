"""Run archive maintenance separately from photo intake."""

from app.worker import main

if __name__ == "__main__":
    main(["ARCHIVE_ORGANIZE"])
