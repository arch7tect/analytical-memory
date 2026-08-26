from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from analytical_memory.canonical import (
    canonical_json,
    normalize_timestamp,
    sha256_bytes,
)
from analytical_memory.errors import BatchValidationError

LOCATOR_KINDS = {
    "whole_object",
    "structured",
    "record_key",
    "byte_range",
    "line_range",
    "time_interval",
    "sample_interval",
}
LOCATOR_KEYS = {
    "whole_object": {"kind"},
    "structured": {"kind", "input_format", "pointer"},
    "record_key": {"kind", "input_format", "key_field", "key_value"},
    "byte_range": {"kind", "start", "end"},
    "line_range": {"kind", "start_line", "end_line"},
    "time_interval": {"kind", "input_format", "timestamp_field", "start", "end"},
    "sample_interval": {
        "kind",
        "start_sample",
        "end_sample",
        "sample_rate",
        "channels",
        "sample_format",
        "bit_width",
        "byte_order",
        "interleaved",
    },
}
PRIVACY_ORDER = {"public": 0, "private": 1, "restricted": 2, "forbidden": 3}


@dataclass(frozen=True, slots=True)
class FragmentSelection:
    addressed_bytes: bytes
    extracted_bytes: bytes
    locator: dict[str, Any]
    extractor_id: str
    extractor_version: str
    derivation_method: str | None
    derivation_parameters: dict[str, Any] | None


def strictest_privacy(*classes: str) -> str:
    try:
        return max(classes, key=PRIVACY_ORDER.__getitem__)
    except (ValueError, KeyError) as exc:
        raise ValueError("unknown privacy class") from exc


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise BatchValidationError(f"{field} must be an integer >= {minimum}")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise BatchValidationError(f"{field} must be a non-empty string")
    return value


def _json_input(data: bytes, input_format: str) -> Any:
    try:
        text = data.decode("utf-8")
        if input_format in {"json", "canonical-json"}:
            return json.loads(text)
        if input_format in {"jsonl", "canonical-jsonl"}:
            return [json.loads(line) for line in text.splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BatchValidationError("evidence is not valid UTF-8 JSON") from exc
    raise BatchValidationError("fragment.input_format is not supported")


def _json_pointer(value: Any, pointer: str) -> Any:
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise BatchValidationError("fragment.pointer must be an RFC 6901 pointer")
    current = value
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(current, list):
                current = current[int(token)]
            elif isinstance(current, dict):
                current = current[token]
            else:
                raise KeyError(token)
        except (KeyError, IndexError, ValueError) as exc:
            raise BatchValidationError(
                f"fragment.pointer does not resolve: {pointer}"
            ) from exc
    return current


def _canonical_records(value: Any) -> tuple[list[dict[str, Any]], bytes]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise BatchValidationError("record locator input must contain JSON objects")
    records = value
    materialized = b"".join(
        canonical_json(record).encode("utf-8") + b"\n" for record in records
    )
    return records, materialized


def select_fragment(data: bytes, raw_locator: object | None) -> FragmentSelection:
    locator = {"kind": "whole_object"} if raw_locator is None else raw_locator
    if not isinstance(locator, dict):
        raise BatchValidationError("evidence.fragment must be an object")
    kind = _text(locator.get("kind"), "evidence.fragment.kind")
    if kind not in LOCATOR_KINDS:
        raise BatchValidationError("evidence.fragment.kind is invalid")
    unknown_keys = set(locator) - LOCATOR_KEYS[kind]
    if unknown_keys:
        raise BatchValidationError(
            f"evidence.fragment has unknown keys: {sorted(unknown_keys)}"
        )

    if kind == "whole_object":
        normalized: dict[str, Any] = {"kind": kind}
        return FragmentSelection(data, data, normalized, "identity", "1", None, None)

    if kind == "byte_range":
        start = _integer(locator.get("start"), "evidence.fragment.start")
        end = _integer(locator.get("end"), "evidence.fragment.end")
        if end < start or end > len(data):
            raise BatchValidationError("evidence.fragment byte range is out of bounds")
        normalized = {"end": end, "kind": kind, "start": start}
        return FragmentSelection(
            data, data[start:end], normalized, "byte-range", "1", None, None
        )

    if kind == "line_range":
        start = _integer(
            locator.get("start_line"), "evidence.fragment.start_line", minimum=1
        )
        end = _integer(locator.get("end_line"), "evidence.fragment.end_line", minimum=1)
        lines = data.splitlines(keepends=True)
        if end < start or end > len(lines):
            raise BatchValidationError("evidence.fragment line range is out of bounds")
        normalized = {"end_line": end, "kind": kind, "start_line": start}
        return FragmentSelection(
            data,
            b"".join(lines[start - 1 : end]),
            normalized,
            "line-range",
            "1",
            None,
            None,
        )

    if kind == "sample_interval":
        start = _integer(locator.get("start_sample"), "evidence.fragment.start_sample")
        end = _integer(locator.get("end_sample"), "evidence.fragment.end_sample")
        rate = _integer(
            locator.get("sample_rate"), "evidence.fragment.sample_rate", minimum=1
        )
        channels = _integer(
            locator.get("channels"), "evidence.fragment.channels", minimum=1
        )
        bit_width = _integer(
            locator.get("bit_width"), "evidence.fragment.bit_width", minimum=1
        )
        if bit_width % 8 or end < start:
            raise BatchValidationError(
                "sample interval requires byte-aligned ordered samples"
            )
        sample_format = _text(
            locator.get("sample_format"), "evidence.fragment.sample_format"
        )
        byte_order = _text(locator.get("byte_order"), "evidence.fragment.byte_order")
        interleaved = locator.get("interleaved")
        if not isinstance(interleaved, bool):
            raise BatchValidationError("evidence.fragment.interleaved must be boolean")
        bytes_per_sample = bit_width // 8
        frame_bytes = channels * bytes_per_sample
        if len(data) % frame_bytes:
            raise BatchValidationError("sample evidence is not frame aligned")
        frame_count = len(data) // frame_bytes
        if end > frame_count:
            raise BatchValidationError(
                "evidence.fragment sample interval is out of bounds"
            )
        if interleaved:
            extracted = data[start * frame_bytes : end * frame_bytes]
        else:
            channel_bytes = frame_count * bytes_per_sample
            extracted = b"".join(
                data[
                    channel * channel_bytes + start * bytes_per_sample : channel
                    * channel_bytes
                    + end * bytes_per_sample
                ]
                for channel in range(channels)
            )
        normalized = {
            "bit_width": bit_width,
            "byte_order": byte_order,
            "channels": channels,
            "end_sample": end,
            "interleaved": interleaved,
            "kind": kind,
            "sample_format": sample_format,
            "sample_rate": rate,
            "start_sample": start,
        }
        return FragmentSelection(
            data,
            extracted,
            normalized,
            "sample-interval",
            "1",
            None,
            None,
        )

    input_format = _text(
        locator.get("input_format", "json"), "evidence.fragment.input_format"
    )
    parsed = _json_input(data, input_format)
    if kind == "structured":
        materialized = canonical_json(parsed).encode("utf-8")
        pointer = locator.get("pointer", "")
        if not isinstance(pointer, str):
            raise BatchValidationError("evidence.fragment.pointer must be a string")
        selected = _json_pointer(parsed, pointer)
        extracted = canonical_json(selected).encode("utf-8")
        normalized = {
            "input_format": "canonical-json",
            "kind": kind,
            "pointer": pointer,
        }
        parameters = {"input_format": input_format, "output_format": "canonical-json"}
        return FragmentSelection(
            materialized,
            extracted,
            normalized,
            "json-pointer",
            "1",
            "canonicalize-json",
            parameters,
        )

    records, materialized = _canonical_records(parsed)
    if kind == "record_key":
        key_field = _text(locator.get("key_field"), "evidence.fragment.key_field")
        key_value = locator.get("key_value")
        matches = [record for record in records if record.get(key_field) == key_value]
        if len(matches) != 1:
            raise BatchValidationError(
                "record_key locator must select exactly one record"
            )
        extracted = canonical_json(matches[0]).encode("utf-8") + b"\n"
        normalized = {
            "input_format": "canonical-jsonl",
            "key_field": key_field,
            "key_value": key_value,
            "kind": kind,
        }
        return FragmentSelection(
            materialized,
            extracted,
            normalized,
            "record-key",
            "1",
            "canonicalize-json-records",
            {"input_format": input_format},
        )

    timestamp_field = _text(
        locator.get("timestamp_field"), "evidence.fragment.timestamp_field"
    )
    try:
        start_time = normalize_timestamp(
            locator.get("start"), "evidence.fragment.start"
        )
        end_time = normalize_timestamp(locator.get("end"), "evidence.fragment.end")
    except ValueError as exc:
        raise BatchValidationError(str(exc)) from exc
    if end_time < start_time:
        raise BatchValidationError("evidence.fragment time interval is reversed")
    selected_records: list[dict[str, Any]] = []
    for record in records:
        try:
            timestamp = normalize_timestamp(record[timestamp_field], timestamp_field)
        except (KeyError, ValueError) as exc:
            raise BatchValidationError(
                "time_interval record has an invalid timestamp"
            ) from exc
        if start_time <= timestamp < end_time:
            selected_records.append(record)
    extracted = b"".join(
        canonical_json(record).encode("utf-8") + b"\n" for record in selected_records
    )
    normalized = {
        "end": end_time,
        "input_format": "canonical-jsonl",
        "kind": kind,
        "start": start_time,
        "timestamp_field": timestamp_field,
    }
    return FragmentSelection(
        materialized,
        extracted,
        normalized,
        "time-interval",
        "1",
        "canonicalize-json-records",
        {"input_format": input_format},
    )


def fragment_digest(selection: FragmentSelection) -> str:
    return sha256_bytes(selection.extracted_bytes)
