from __future__ import annotations

import argparse
import json

from analytical_memory.query_ir import query_ir_contract_document
from analytical_memory.resources import resource_path, source_checkout_root
from analytical_memory.schema_contract import load_schema


def render() -> str:
    schema = load_schema()
    document = query_ir_contract_document(schema.fingerprint)
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    target = resource_path("schema", "query-ir-contract.json")
    rendered = render()
    if arguments.check:
        try:
            return 0 if target.read_text(encoding="utf-8") == rendered else 1
        except OSError:
            return 1
    source_checkout_root()
    target.write_text(rendered, encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
