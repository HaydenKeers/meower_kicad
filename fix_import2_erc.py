#!/usr/bin/env python3
"""ERC fixes for import2.kicad_sch — pin types, references, no_connect only.

Does NOT rename or rewire nets.
"""
from __future__ import annotations

import json
import math
import re
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHEETS = [
    ROOT / "2_ADCs.kicad_sch",
    ROOT / "3_ADC pins and connector.kicad_sch",
    ROOT / "7_ESP and Power.kicad_sch",
]
SYM_LIB = ROOT / "ProPrj_BCI-easyedapro.kicad_sym"
ERC_JSON = ROOT / "import2-erc.json"

# ref -> pin numbers for no_connect (skip BIASIN/BIASOUT — need wiring, not NC)
NO_CONNECT_PINS: dict[str, list[str]] = {
    "ADC1": ["29", "64"],
    "ADC2": ["64"],
    "D1": ["6"],
    "D2": ["6"],
    "D3": ["6"],
    "D4": ["6"],
    "D5": ["2", "6"],
    "D7": ["6"],
    "D8": ["6"],
    "D9": ["6"],
    "D10": ["6"],
    "U14": ["4"],
    "U2": ["4"],
    "USB1": ["3", "9"],
}

INSTANCE_CHUNK_RE = re.compile(r"\t\(symbol\n\t\t\(lib_id ")


def uid() -> str:
    return str(uuid.uuid4())


def iter_instance_spans(text: str):
    for m in INSTANCE_CHUNK_RE.finditer(text):
        start = m.start()
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    yield start, i + 1
                    break


def extract_property(block: str, name: str) -> str | None:
    m = re.search(
        rf'\(property "{re.escape(name)}" "((?:\\.|[^"\\])*)"',
        block,
    )
    return m.group(1) if m else None


def symbol_block_bounds(lib: str, symbol_id: str) -> tuple[int, int] | None:
    marker = f'(symbol "{symbol_id}"'
    start = lib.find(marker)
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(lib)):
        ch = lib[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return start, i + 1
    return None


def set_symbol_pin_types(lib: str, symbol_id: str, pin_types: dict[str, str]) -> str:
    bounds = symbol_block_bounds(lib, symbol_id)
    if not bounds:
        return lib
    start, end = bounds
    block = lib[start:end]
    for pin_name, pin_type in pin_types.items():
        block = re.sub(
            rf'(\(pin )\S+( line\n\s+\(at [^\n]+\n\s+\(length [^\n]+\n\s+\(name "{re.escape(pin_name)}"\n)',
            rf"\1{pin_type}\2",
            block,
        )
    return lib[:start] + block + lib[end:]


def fix_lib_symbols_block(body: str) -> tuple[str, int]:
    body2, n = re.subn(r"\(pin input line", "(pin passive line", body)

    for ads in ("ProPrj_BCI-easyedapro:ADS1299IPAGR",):
        bounds = symbol_block_bounds(body2, ads)
        if not bounds:
            continue
        s, e = bounds
        ads_block = body2[s:e]
        ads_block = re.sub(
            r"\(pin \S+ line\n\s+\(at [^\n]+\n\s+\(length [^\n]+\n\s+\(name \"(?:NC|RESERVED)\"",
            lambda m: m.group(0).replace(
                re.search(r"\(pin \S+ line", m.group(0)).group(0), "(pin free line", 1
            ),
            ads_block,
        )
        body2 = body2[:s] + ads_block + body2[e:]

    c6 = "ProPrj_BCI-easyedapro:ESP32-C6-MINI-1-N4"
    bounds = symbol_block_bounds(body2, c6)
    if bounds:
        s, e = bounds
        c6_block = body2[s:e]

        def c6_pin_repl(m: re.Match[str]) -> str:
            block = m.group(0)
            name_m = re.search(r'\(name "([^"]+)"', block)
            name = name_m.group(1) if name_m else ""
            if name in ("GND", "3V3"):
                return re.sub(r"\(pin passive line", "(pin power_in line", block, count=1)
            if name.startswith("IO") or name in ("EN", "RXD0", "TXD0"):
                return re.sub(r"\(pin passive line", "(pin bidirectional line", block, count=1)
            if name == "NC":
                return re.sub(r"\(pin passive line", "(pin free line", block, count=1)
            return block

        c6_block = re.sub(
            r"\(pin passive line.*?\(number \"[^\"]+\".*?\)\n\t\t\t\t\)\n\t\t\t\)\n\t\t\t\)\n\t\t\)",
            c6_pin_repl,
            c6_block,
            flags=re.DOTALL,
        )
        body2 = body2[:s] + c6_block + body2[e:]

    body2 = set_symbol_pin_types(
        body2,
        "ProPrj_BCI-easyedapro:TYPE-C 16PIN 2MD(073)",
        {
            "VBUS": "passive",
            "GND": "power_in",
            "SHELL": "power_in",
            "DP1": "bidirectional",
            "DP2": "bidirectional",
            "DN1": "bidirectional",
            "DN2": "bidirectional",
            "SBU1": "free",
            "SBU2": "free",
        },
    )
    body2 = set_symbol_pin_types(body2, "ProPrj_BCI-easyedapro:WAFER-PH2.0-2PWZ", {"1": "power_out"})
    body2 = set_symbol_pin_types(body2, "ProPrj_BCI-easyedapro:TPS63900DSKR", {"CFG1": "passive"})

    for sym, nc_pins in (
        ("ProPrj_BCI-easyedapro:TPD4E1B06DCKR", ("NC", "IO2")),
        ("ProPrj_BCI-easyedapro:ESP32-C6-MINI-1-N4", ("NC",)),
        ("ProPrj_BCI-easyedapro:TP4057", ("NC",)),
        ("ProPrj_BCI-easyedapro:TPS62821DLCR", ("NC",)),
    ):
        bounds = symbol_block_bounds(body2, sym)
        if not bounds:
            continue
        s, e = bounds
        block = body2[s:e]
        for pname in nc_pins:
            block = re.sub(
                rf'(\(pin )\S+( line\n\s+\(at [^\n]+\n\s+\(length [^\n]+\n\s+\(name "{re.escape(pname)}"\n)',
                r"\1free\2",
                block,
            )
        body2 = body2[:s] + block + body2[e:]

    return body2, n


def fix_sheet_lib_symbols(text: str) -> tuple[str, int]:
    m = re.search(
        r"(\t\(lib_symbols\n)(.*?)(\n\t\)\n\t\(symbol\n\t\t\(lib_id )",
        text,
        re.S,
    )
    if not m:
        return text, 0
    head, body, tail = m.group(1), m.group(2), m.group(3)
    body2, n = fix_lib_symbols_block(body)
    return text[: m.start()] + head + body2 + tail + text[m.end() :], n


def annotate_references(text: str) -> tuple[str, dict[str, int]]:
    stats: dict[str, int] = {}
    jp_n = 1
    frame_n = 1

    def next_ref(lib_id: str, ref: str) -> str | None:
        nonlocal jp_n, frame_n
        if ref and ref != "?":
            return None
        if "Short-Symbol" in lib_id:
            r = f"JP{jp_n}"
            jp_n += 1
            return r
        if "Sheet-Symbol_A4" in lib_id:
            r = f"F{frame_n}"
            frame_n += 1
            return r
        return None

    out_parts: list[str] = []
    last = 0
    for start, end in iter_instance_spans(text):
        out_parts.append(text[last:start])
        block = text[start:end]
        lib_m = re.search(r'\(lib_id "([^"]+)"\)', block)
        lib_id = lib_m.group(1) if lib_m else ""
        ref = extract_property(block, "Reference")
        new_ref = next_ref(lib_id, ref or "")
        if new_ref:
            block = re.sub(
                r'(\(property "Reference" ")\?(")',
                rf"\g<1>{new_ref}\2",
                block,
                count=1,
            )
            block = re.sub(r'(\(reference ")\?(")', rf"\g<1>{new_ref}\2", block)
            if "Sheet-Symbol_A4" in lib_id:
                block = block.replace("(in_bom yes)", "(in_bom no)", 1)
                block = block.replace("(on_board yes)", "(on_board no)", 1)
            key = new_ref.rstrip("0123456789") or new_ref
            stats[key] = stats.get(key, 0) + 1
        out_parts.append(block)
        last = end
    out_parts.append(text[last:])
    return "".join(out_parts), stats


def fix_pwr_question_marks(text: str) -> tuple[str, int]:
    used = set(re.findall(r"#PWR\d+", text))
    n = 0

    def repl(_m: re.Match[str]) -> str:
        nonlocal n
        for i in range(1, 300):
            candidate = f"#PWR{i:02d}"
            if candidate not in used:
                used.add(candidate)
                n += 1
                return f'"{candidate}"'
        return '"#PWR99"'

    return re.sub(r'"#PWR\?"', repl, text), n


def parse_lib_pins(text: str) -> dict[str, dict[str, dict]]:
    m = re.search(
        r"(\t\(lib_symbols\n)(.*?)(\n\t\)\n\t\(symbol\n\t\t\(lib_id )",
        text,
        re.S,
    )
    if not m:
        return {}
    lib = m.group(2)
    result: dict[str, dict[str, dict]] = {}
    for sym_m in re.finditer(r'\(symbol "(ProPrj_BCI-easyedapro:[^"]+)"', lib):
        sym_id = sym_m.group(1)
        bounds = symbol_block_bounds(lib, sym_id)
        if not bounds:
            continue
        block = lib[bounds[0] : bounds[1]]
        pins: dict[str, dict] = {}
        for pin_m in re.finditer(
            r"\(pin \S+ line\n\s+\(at ([0-9.-]+) ([0-9.-]+) ([0-9.-]+)\)\n\s+\(length ([0-9.-]+)\)"
            r'[\s\S]*?\(number "([^"]+)"',
            block,
        ):
            pins[pin_m.group(5)] = {
                "x": float(pin_m.group(1)),
                "y": float(pin_m.group(2)),
                "angle": float(pin_m.group(3)),
                "length": float(pin_m.group(4)),
            }
        result[sym_id] = pins
    return result


def parse_instances(text: str) -> dict[str, dict]:
    instances: dict[str, dict] = {}
    for block in (text[s:e] for s, e in iter_instance_spans(text)):
        ref = extract_property(block, "Reference")
        if not ref:
            continue
        lib_m = re.search(r'\(lib_id "([^"]+)"\)', block)
        at_m = re.search(r"\(at ([0-9.-]+) ([0-9.-]+) ([0-9.-]+)\)", block)
        if not lib_m or not at_m:
            continue
        instances[ref] = {
            "lib_id": lib_m.group(1),
            "x": float(at_m.group(1)),
            "y": float(at_m.group(2)),
            "rot": float(at_m.group(3)),
        }
    return instances


def pin_endpoint(pin_def: dict) -> tuple[float, float]:
    x, y = pin_def["x"], pin_def["y"]
    length = pin_def["length"]
    rad = math.radians(pin_def["angle"] % 360)
    return x + length * math.cos(rad), y + length * math.sin(rad)


def pin_world(inst: dict, pin_def: dict) -> tuple[float, float]:
    px, py = pin_endpoint(pin_def)
    rot = math.radians(inst["rot"])
    rx = px * math.cos(rot) - py * math.sin(rot)
    ry = px * math.sin(rot) + py * math.cos(rot)
    return round(inst["x"] + rx, 2), round(inst["y"] + ry, 2)


def no_connect_block(x: float, y: float) -> str:
    return f'\t(no_connect\n\t\t(at {x} {y})\n\t\t(uuid "{uid()}")\n\t)\n'


def insert_before_root_close(text: str, blocks: str) -> str:
    marker = "\t(sheet_instances\n"
    if marker in text:
        return text.replace(marker, blocks + marker, 1)
    trimmed = text.rstrip()
    if trimmed.endswith(")"):
        return trimmed[:-1] + "\n" + blocks + ")\n"
    return text + blocks


def add_no_connects(text: str) -> tuple[str, int]:
    lib_pins = parse_lib_pins(text)
    instances = parse_instances(text)
    existing = {
        (round(float(m.group(1)), 2), round(float(m.group(2)), 2))
        for m in re.finditer(r"\(no_connect\n\t\t\(at ([0-9.-]+) ([0-9.-]+)\)", text)
    }
    blocks: list[str] = []
    for ref, pin_ids in NO_CONNECT_PINS.items():
        inst = instances.get(ref)
        if not inst:
            continue
        pins = lib_pins.get(inst["lib_id"], {})
        for pin_id in pin_ids:
            pin_def = pins.get(pin_id)
            if not pin_def:
                continue
            x, y = pin_world(inst, pin_def)
            if (x, y) in existing:
                continue
            blocks.append(no_connect_block(x, y))
            existing.add((x, y))
    if not blocks:
        return text, 0
    return insert_before_root_close(text, "".join(blocks)), len(blocks)


def fix_sym_lib() -> int:
    if not SYM_LIB.is_file():
        return 0
    text = SYM_LIB.read_text(encoding="utf-8")
    before = text.count("(pin input line")
    text2, _ = fix_lib_symbols_block(text)
    if text2 != text:
        SYM_LIB.write_text(text2, encoding="utf-8")
    return before if text2 != text else 0


def process_sheet(path: Path) -> None:
    print(f"=== {path.name} ===")
    text = path.read_text(encoding="utf-8")
    text, n_pin = fix_sheet_lib_symbols(text)
    print(f"  input->passive in lib_symbols: {n_pin}")
    text, ann = annotate_references(text)
    print(f"  annotated: {ann}")
    text, n_pwr = fix_pwr_question_marks(text)
    print(f"  #PWR? renamed: {n_pwr}")
    path.write_text(text, encoding="utf-8")


def main() -> int:
    n_lib = fix_sym_lib()
    print(f"Symbol library input->passive fixes: {n_lib}")
    for sheet in SHEETS:
        if sheet.is_file():
            process_sheet(sheet)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
