from __future__ import annotations

import argparse

from analytical_memory.schema_compiler import schema_is_current, write_schema


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    if arguments.check:
        return 0 if schema_is_current() else 1
    compiled = write_schema()
    print(compiled["schema_fingerprint"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
