"""Low-level protobuf wire-format codec for i-Vent protocol.

We implement raw protobuf encoding/decoding without the protobuf library
since we're working with a reverse-engineered protocol and don't have .proto files.
"""
from __future__ import annotations

import struct


# Wire types
VARINT = 0
FIXED64 = 1
LENGTH_DELIMITED = 2
FIXED32 = 5


def encode_varint(value: int) -> bytes:
    """Encode an unsigned integer as a protobuf varint."""
    if value < 0:
        # Protobuf encodes negative varints as 10-byte unsigned
        value = value & 0xFFFFFFFFFFFFFFFF
    parts = []
    while value > 0x7F:
        parts.append((value & 0x7F) | 0x80)
        value >>= 7
    parts.append(value & 0x7F)
    return bytes(parts)


def decode_varint(data: bytes, offset: int) -> tuple[int, int]:
    """Decode a varint from data at offset. Returns (value, new_offset)."""
    result = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, offset
        shift += 7
    raise ValueError("Truncated varint")


def varint_to_signed32(v: int) -> int:
    """Convert unsigned varint to signed 32-bit integer."""
    if v > 0x7FFFFFFF:
        # For large values that represent negative numbers
        return v - (1 << 64) if v > 0xFFFFFFFF else v - (1 << 32)
    return v


def encode_tag(field_number: int, wire_type: int) -> bytes:
    """Encode a protobuf field tag."""
    return encode_varint((field_number << 3) | wire_type)


def encode_field_varint(field_number: int, value: int) -> bytes:
    """Encode a varint field."""
    return encode_tag(field_number, VARINT) + encode_varint(value)


def encode_field_fixed32(field_number: int, value: int) -> bytes:
    """Encode a fixed32 field."""
    return encode_tag(field_number, FIXED32) + struct.pack("<I", value & 0xFFFFFFFF)


def encode_field_fixed64(field_number: int, value: int) -> bytes:
    """Encode a fixed64 field."""
    return encode_tag(field_number, FIXED64) + struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF)


def encode_field_bytes(field_number: int, value: bytes) -> bytes:
    """Encode a length-delimited (bytes) field."""
    return encode_tag(field_number, LENGTH_DELIMITED) + encode_varint(len(value)) + value


def decode_fields(data: bytes) -> list[tuple[int, int, bytes | int]]:
    """Decode all protobuf fields from raw bytes.

    Returns list of (field_number, wire_type, value) tuples.
    For varints, value is int. For fixed32/64, value is int.
    For length-delimited, value is bytes.
    """
    fields = []
    offset = 0
    while offset < len(data):
        tag, offset = decode_varint(data, offset)
        field_number = tag >> 3
        wire_type = tag & 0x07

        if wire_type == VARINT:
            value, offset = decode_varint(data, offset)
            fields.append((field_number, wire_type, value))
        elif wire_type == FIXED64:
            value = struct.unpack("<Q", data[offset : offset + 8])[0]
            offset += 8
            fields.append((field_number, wire_type, value))
        elif wire_type == LENGTH_DELIMITED:
            length, offset = decode_varint(data, offset)
            value = data[offset : offset + length]
            offset += length
            fields.append((field_number, wire_type, value))
        elif wire_type == FIXED32:
            value = struct.unpack("<I", data[offset : offset + 4])[0]
            offset += 4
            fields.append((field_number, wire_type, value))
        else:
            raise ValueError(f"Unknown wire type {wire_type} at field {field_number}")
    return fields


def get_field(fields: list[tuple[int, int, bytes | int]], field_number: int) -> bytes | int | None:
    """Get the first value for a given field number."""
    for fn, _, val in fields:
        if fn == field_number:
            return val
    return None
