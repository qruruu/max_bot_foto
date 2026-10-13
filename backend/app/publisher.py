"""Dedicated durable publisher so disk exchange never occupies the intake worker."""

from app.worker import main

if __name__ == "__main__":
    main(["PUBLISH", "EXCHANGE_GC", "ARCHIVE_ORGANIZE"])
