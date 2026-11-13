"""Stored ZIP64 streaming: bounded RAM, no temporary copy of the photographs."""

import struct
import time
from tempfile import TemporaryFile
from zlib import crc32

CHUNK_SIZE = 64 * 1024
MAX_DIRECTORY_BYTES = 64 * 1024 * 1024


def paced_chunks(chunks, bytes_per_second):
    try:
        for chunk in chunks:
            started = time.monotonic()
            yield chunk
            if bytes_per_second:
                delay = len(chunk) / bytes_per_second - (time.monotonic() - started)
                if delay > 0:
                    time.sleep(delay)
    finally:
        chunks.close()


def image_chunks(path):
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            yield chunk


def stream_image(path, bytes_per_second=8 * 1024 * 1024):
    yield from paced_chunks(image_chunks(path), bytes_per_second)


def stream_zip(files, directory, bytes_per_second=8 * 1024 * 1024):
    yield from paced_chunks(zip_chunks(files, directory), bytes_per_second)


def zip_chunks(files, directory):
    """Yield file chunks and spool only the ZIP directory to disk.

    ZIP64 and data descriptors allow unknown sizes and more than 65,535 entries.
    Keeping the directory on disk avoids zipfile.ZipFile's growing in-memory file list.
    """
    offset = count = directory_size = 0
    with TemporaryFile(dir=directory) as central:
        for name, path in files:
            name = name.encode("ascii")
            file_offset = offset
            extra = struct.pack("<HHQQ", 1, 16, 0, 0)
            header = struct.pack("<I5H3I2H", 0x04034B50, 45, 8, 0, 0, 33,
                                 0, 0xFFFFFFFF, 0xFFFFFFFF, len(name), len(extra)) + name + extra
            # Open before emitting this member's header: disappearing files fail the download.
            with path.open("rb") as source:
                yield header
                offset += len(header)
                checksum = size = 0
                while chunk := source.read(CHUNK_SIZE):
                    checksum = crc32(chunk, checksum)
                    size += len(chunk)
                    offset += len(chunk)
                    yield chunk
            descriptor = struct.pack("<IIQQ", 0x08074B50, checksum, size, size)
            yield descriptor
            offset += len(descriptor)
            extra = struct.pack("<HHQQQ", 1, 24, size, size, file_offset)
            entry = struct.pack("<I6H3I5H2I", 0x02014B50, 45, 45, 8, 0, 0, 33,
                                checksum, 0xFFFFFFFF, 0xFFFFFFFF, len(name), len(extra),
                                0, 0, 0, 0, 0xFFFFFFFF) + name + extra
            directory_size += len(entry)
            if directory_size > MAX_DIRECTORY_BYTES:
                raise OSError("Photo archive directory exceeds its disk budget")
            central.write(entry)
            count += 1
        directory_offset = offset
        central.seek(0)
        while chunk := central.read(CHUNK_SIZE):
            yield chunk
            offset += len(chunk)
        yield struct.pack("<IQ2H2I4Q", 0x06064B50, 44, 45, 45, 0, 0,
                          count, count, directory_size, directory_offset)
        yield struct.pack("<IIQI", 0x07064B50, 0, offset, 1)
        yield struct.pack("<I4H2IH", 0x06054B50, 0, 0, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0)
