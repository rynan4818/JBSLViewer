from __future__ import annotations

import gzip
import hashlib
import io
import math
import struct
from dataclasses import dataclass

from .errors import ApiProblem


MAGIC = 0x442D3D69


@dataclass(frozen=True, slots=True)
class ReplayInfo:
    player_id: str
    platform: str
    hash: str
    difficulty: str
    mode: str
    score: int
    game_version: str
    modifiers: str


@dataclass(frozen=True, slots=True)
class DecodedReplay:
    info: ReplayInfo
    sha256: str
    byte_count: int
    data: bytes


class Reader:
    MAX_STRING_BYTES = 64 * 1024
    MAX_ITEMS = 2_000_000

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def take(self, size: int) -> bytes:
        if size < 0 or self.pos + size > len(self.data):
            raise ApiProblem(422, "replay_invalid", "The BSOR data is truncated.")
        result = self.data[self.pos:self.pos + size]
        self.pos += size
        return result

    def unpack(self, fmt: str):
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.take(size))[0]

    def i32(self) -> int: return self.unpack("<i")
    def u32(self) -> int: return self.unpack("<I")
    def f32(self) -> float:
        value = self.unpack("<f")
        if not math.isfinite(value):
            raise ApiProblem(422, "replay_invalid", "BSOR contains a non-finite number.")
        return value
    def i64(self) -> int: return self.unpack("<q")
    def boolean(self) -> bool:
        value = self.unpack("<B")
        if value not in (0, 1):
            raise ApiProblem(422, "replay_invalid", "BSOR contains an invalid boolean.")
        return bool(value)
    def string(self) -> str:
        length = self.i32()
        if length < 0 or length > self.MAX_STRING_BYTES:
            raise ApiProblem(422, "replay_invalid", "BSOR string length is invalid.")
        try:
            return self.take(length).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ApiProblem(422, "replay_invalid", "BSOR contains invalid UTF-8.") from exc
    def count(self) -> int:
        value = self.u32()
        if value > self.MAX_ITEMS:
            raise ApiProblem(422, "replay_invalid", "BSOR array length is invalid.")
        return value
    def vector(self) -> None:
        for _ in range(3): self.f32()
    def quaternion(self) -> None:
        for _ in range(4): self.f32()


def decompress_gzip(payload: bytes, compressed_limit: int, expanded_limit: int) -> bytes:
    if len(payload) > compressed_limit:
        raise ApiProblem(413, "replay_too_large", "Compressed replay exceeds the configured limit.")
    result = bytearray()
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as stream:
            while True:
                chunk = stream.read(min(64 * 1024, expanded_limit + 1 - len(result)))
                if not chunk:
                    break
                result.extend(chunk)
                if len(result) > expanded_limit:
                    raise ApiProblem(413, "replay_too_large", "Expanded replay exceeds the configured limit.")
    except (gzip.BadGzipFile, EOFError, OSError) as exc:
        raise ApiProblem(422, "replay_invalid", "Replay is not valid gzip data.") from exc
    return bytes(result)


def decode_gzip(payload: bytes, compressed_limit: int, expanded_limit: int) -> DecodedReplay:
    data = decompress_gzip(payload, compressed_limit, expanded_limit)
    r = Reader(data)
    if r.i32() != MAGIC or r.unpack("<B") != 1:
        raise ApiProblem(422, "replay_invalid", "Replay magic or version is invalid.")
    seen: set[int] = set()
    info: ReplayInfo | None = None
    while r.pos < len(data):
        section = r.unpack("<B")
        if section not in range(6) or section in seen:
            raise ApiProblem(422, "replay_invalid", "Replay section order/type is invalid.")
        if section != len(seen):
            raise ApiProblem(422, "replay_invalid", "Replay sections must use BSOR Version 1 order.")
        seen.add(section)
        if section == 0:
            version = r.string(); game_version = r.string(); timestamp = r.string()
            player_id = r.string(); player_name = r.string(); platform = r.string()
            tracking = r.string(); hmd = r.string(); controller = r.string()
            song_hash = r.string(); song_name = r.string(); mapper = r.string(); difficulty = r.string()
            score = r.i32(); mode = r.string(); environment = r.string(); modifiers = r.string()
            r.f32(); r.boolean(); r.f32(); r.f32(); r.f32(); r.f32()
            info = ReplayInfo(player_id, platform, song_hash.strip().upper(), difficulty, mode, score, game_version, modifiers)
        elif section == 1:
            for _ in range(r.count()):
                r.f32(); r.i32()
                for _ in range(3): r.vector(); r.quaternion()
        elif section == 2:
            for _ in range(r.count()):
                r.i32(); r.f32(); r.f32(); event_type = r.i32()
                if event_type not in (0, 1, 2, 3):
                    raise ApiProblem(422, "replay_invalid", "Replay note event type is invalid.")
                if event_type in (0, 1):
                    for _ in range(4): r.boolean()
                    r.f32(); r.vector(); r.i32(); r.f32(); r.f32(); r.vector(); r.vector()
                    for _ in range(4): r.f32()
        elif section == 3:
            for _ in range(r.count()): r.i32(); r.f32(); r.f32(); r.f32()
        elif section == 4:
            for _ in range(r.count()): r.f32(); r.f32()
        elif section == 5:
            for _ in range(r.count()): r.i64(); r.f32()
    if seen != set(range(6)) or info is None:
        raise ApiProblem(422, "replay_invalid", "Replay does not contain all required BSOR sections.")
    return DecodedReplay(info, hashlib.sha256(data).hexdigest(), len(data), data)

