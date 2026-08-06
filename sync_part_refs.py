#!/usr/bin/env python3
"""Sync part properties from meower_kicad to import2 by reference designator."""

import re
import shutil
import sys
from pathlib import Path

SRC_SHEETS = Path(r"C:\Users\Hayden\Code\meower_kicad\sheets")
SRC_PRETTY = Path(r"C:\Users\Hayden\Code\meower_kicad\ProPrj_BCI-easyedapro.pretty")
DST_DIR = Path(r"C:\Users\Hayden\Code\meower_import2\import2")
DST_PRETTY = DST_DIR / "ProPrj_BCI-easyedapro.pretty"
DST_FP_TABLE = DST_DIR / "fp-lib-table"

# import2 ref -> meower_kicad ref
REF_ALIASES = {
    "C_adc": "C_adc1",
}

# Components that must keep EasyEDA BOM/footprint data (not meower_kicad).
EASYEDA_ONLY_REFS = {"C227"}

# EasyEDA source-of-truth properties for refs in EASYEDA_ONLY_REFS.
EASYEDA_PARTS = {
    "C227": {
        "Footprint": "ProPrj_BCI-easyedapro:C0603",
        "Manufacturer Part": "GRM188Z71C475KE21D",
        "Manufacturer": "muRata(村田)",
        "Supplier Part": "C389010",
        "Supplier": "LCSC",
        "LCSC Part Name": "4.7uF ±10% 16V",
        "Datasheet": "https://www.lcsc.com/product-detail/GRM188Z71C475KE21D_C389010.html",
        "Description": "",
        "Value": "4.7uF",
    },
}

PART_PROPS = [
    "Footprint",
    "Manufacturer Part",
    "Manufacturer",
    "Supplier Part",
    "Supplier",
    "LCSC Part Name",
    "JLC_3DModel_Q",
    "JLC_3D_Size",
    "Datasheet",
    "Description",
    "Mouser Part Number",
    "Arrow Part Number",
    "DK Part Number",
]

INSTANCE_CHUNK_RE = re.compile(r"\t\(symbol\n\t\t\(lib_")


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


def iter_instance_chunks(text: str):
    for start, end in iter_instance_spans(text):
        yield text[start:end]


def extract_property(block: str, name: str) -> str | None:
    m = re.search(
        rf'\(property "{re.escape(name)}" "((?:\\.|[^"\\])*)"',
        block,
    )
    return m.group(1) if m else None


def extract_instances(path: Path) -> dict[str, dict]:
    text = path.read_text(encoding="utf-8")
    instances: dict[str, dict] = {}
    for block in iter_instance_chunks(text):
        ref = extract_property(block, "Reference")
        if not ref:
            continue
        lib_m = re.search(r'\(lib_id "([^"]+)"\)', block)
        props = {}
        for pname in PART_PROPS:
            val = extract_property(block, pname)
            if val is not None:
                props[pname] = val
        instances[ref] = {
            "lib_id": lib_m.group(1) if lib_m else "",
            "props": props,
            "file": path,
        }
    return instances


def kicad_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def set_or_add_property(block: str, name: str, value: str) -> str:
    escaped = kicad_escape(value)
    prop_re = re.compile(
        rf'(\(property "{re.escape(name)}" ")(?:\\.|[^"\\])*(")',
        re.DOTALL,
    )
    if prop_re.search(block):
        return prop_re.sub(rf"\g<1>{escaped}\2", block, count=1)

    ref_re = re.compile(
        r'(\(property "Reference" "(?:\\.|[^"\\])*"\n'
        r'(?:\t\t\t[^\n]*\n)*'
        r'\t\t\))',
        re.DOTALL,
    )
    new_prop = (
        f'\t\t(property "{name}" "{escaped}"\n'
        f"\t\t\t(at 0 0 0)\n"
        f"\t\t\t(effects\n"
        f"\t\t\t\t(font\n"
        f"\t\t\t\t\t(size 1.27 1.27)\n"
        f"\t\t\t\t)\n"
        f"\t\t\t\t(hide yes)\n"
        f"\t\t\t)\n"
        f"\t\t)"
    )
    if ref_re.search(block):
        return ref_re.sub(rf"\1\n{new_prop}", block, count=1)
    return block[:-1] + f"\n{new_prop}\n\t)"


def update_instance_block(block: str, src_props: dict[str, str]) -> tuple[str, list[str]]:
    changes: list[str] = []
    updated = block
    for pname, value in src_props.items():
        old = extract_property(updated, pname)
        if old == value:
            continue
        updated = set_or_add_property(updated, pname, value)
        changes.append(f"{pname}: {old!r} -> {value!r}")
    return updated, changes


def sync_schematic_file(path: Path, src_by_ref: dict[str, dict]) -> list[str]:
    text = path.read_text(encoding="utf-8")
    out_parts: list[str] = []
    last = 0
    file_changes: list[str] = []

    for start, end in iter_instance_spans(text):
        out_parts.append(text[last:start])
        block = text[start:end]
        ref = extract_property(block, "Reference")
        if ref in EASYEDA_ONLY_REFS:
            new_block, changes = update_instance_block(
                block, {k: v for k, v in EASYEDA_PARTS[ref].items() if k != "Value"}
            )
            if changes:
                file_changes.append(f"{ref}: " + "; ".join(changes))
            block = new_block
            out_parts.append(block)
            last = end
            continue
        src_ref = REF_ALIASES.get(ref, ref) if ref else None
        if src_ref and src_ref in src_by_ref:
            new_block, changes = update_instance_block(
                block, src_by_ref[src_ref]["props"]
            )
            if changes:
                file_changes.append(f"{ref}: " + "; ".join(changes))
            block = new_block
        out_parts.append(block)
        last = end

    out_parts.append(text[last:])
    new_text = "".join(out_parts)
    if file_changes:
        path.write_text(new_text, encoding="utf-8")
    return file_changes


def install_footprint_library() -> None:
    if not SRC_PRETTY.is_dir():
        raise FileNotFoundError(f"Missing source footprint library: {SRC_PRETTY}")
    if DST_PRETTY.exists():
        shutil.rmtree(DST_PRETTY)
    shutil.copytree(SRC_PRETTY, DST_PRETTY)
    DST_FP_TABLE.write_text(
        '(fp_lib_table\n'
        "\t(version 8)\n"
        "\t(lib\n"
        '\t\t(name "ProPrj_BCI-easyedapro")\n'
        '\t\t(type "KiCad")\n'
        '\t\t(uri "${KIPRJMOD}/ProPrj_BCI-easyedapro.pretty")\n'
        '\t\t(options "")\n'
        '\t\t(descr "EasyEDA imported footprints")\n'
        "\t)\n"
        "\t(lib\n"
        '\t\t(name "normalized-easyedapro")\n'
        '\t\t(type "KiCad")\n'
        '\t\t(uri "${KIPRJMOD}/ProPrj_BCI-easyedapro.pretty")\n'
        '\t\t(options "")\n'
        '\t\t(descr "EasyEDA imported footprints (PCB nickname alias)")\n'
        "\t)\n"
        ")\n",
        encoding="utf-8",
    )
    print(f"Installed footprint library: {DST_PRETTY} ({len(list(DST_PRETTY.glob('*.kicad_mod')))} footprints)")


def compare(dry_run: bool = True):
    src_by_ref: dict[str, dict] = {}
    for f in sorted(SRC_SHEETS.glob("*.kicad_sch")):
        src_by_ref.update(extract_instances(f))

    dst_files = [
        f
        for f in sorted(DST_DIR.glob("*.kicad_sch"))
        if f.name != "import2.kicad_sch"
    ]
    dst_by_ref: dict[str, dict] = {}
    for f in dst_files:
        dst_by_ref.update(extract_instances(f))

    print(f"Source refs: {len(src_by_ref)}")
    print(f"Dest refs: {len(dst_by_ref)}")

    mapped_dst = {REF_ALIASES.get(r, r): r for r in dst_by_ref}
    only_src = sorted(set(src_by_ref) - set(mapped_dst))
    only_dst = sorted(
        r for r in dst_by_ref if REF_ALIASES.get(r, r) not in src_by_ref
    )
    if only_src:
        print(f"Only in source ({len(only_src)}): {', '.join(only_src)}")
    if only_dst:
        print(f"Only in dest ({len(only_dst)}): {', '.join(only_dst)}")

    diff_count = 0
    footprint_diffs = []
    for dst_ref, dst in dst_by_ref.items():
        src_ref = REF_ALIASES.get(dst_ref, dst_ref)
        if src_ref not in src_by_ref:
            continue
        sp = src_by_ref[src_ref]["props"]
        dp = dst["props"]
        if any(sp.get(k) != dp.get(k) for k in set(sp) | set(dp)):
            diff_count += 1
        if sp.get("Footprint") != dp.get("Footprint"):
            footprint_diffs.append(
                (dst_ref, dp.get("Footprint"), sp.get("Footprint"))
            )
    print(f"Refs with property diffs: {diff_count}")
    if footprint_diffs:
        print(f"Footprint changes ({len(footprint_diffs)}):")
        for ref, old, new in footprint_diffs[:20]:
            print(f"  {ref}: {old!r} -> {new!r}")
        if len(footprint_diffs) > 20:
            print(f"  ... and {len(footprint_diffs) - 20} more")

    if dry_run:
        return

    install_footprint_library()
    total_changes = 0
    for f in dst_files:
        changes = sync_schematic_file(f, src_by_ref)
        if changes:
            print(f"\nUpdated {f.name} ({len(changes)} components):")
            for line in changes[:8]:
                print(f"  {line}")
            if len(changes) > 8:
                print(f"  ... and {len(changes) - 8} more")
            total_changes += len(changes)
    print(f"\nTotal components updated: {total_changes}")


if __name__ == "__main__":
    dry = "--apply" not in sys.argv
    if dry:
        print("DRY RUN (pass --apply to write changes)\n")
    compare(dry_run=dry)
