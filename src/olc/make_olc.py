#!/usr/bin/env python3
"""
make_olc.py — Generate a WinOLS .olc simulator profile for the Roadrunner.

The OLC format (from hex analysis of existing WinOLS simulator profiles):

Offset  Length  Content
0       N       ASCII chip descriptor string  (null-terminated)
N+1     1       0x09 — field separator
N+2     8       Config bytes: 0x0F 0xF0 repeating × 4
N+10    2       0x00 0x00
N+12    2       0x01 0x61 ('a' field marker)
N+14    1       0x00
N+15    1       field-a length byte
N+16    M       field-a value: "ols4-32.ncd"
...     ...     fields b (part number), c (date), d (time), e (binary data)

The binary payload (field 'e', ~22 KB) is the Batronix FPGA configuration
for that chip type.  For the Roadrunner we DO NOT send this payload to any
Batronix hardware — instead our proxy intercepts the OLC load and uses it
only to declare the chip type (address space, bit width) to WinOLS.

The binary section is copied from an existing OLC and serves as a valid
placeholder so WinOLS does not reject the file.
"""

import struct
import sys
import os
import datetime

# ── OLC file we base the binary section on ────────────────────────────
BASE_OLC = r"C:\Program Files\EVC\WinOLS\olc\sim27040.olc"

# ── Roadrunner chip profiles to generate ─────────────────────────────
# (descriptor, part_number, variant_suffix)
PROFILES = [
    ("Roadrunner : 27C512",    "27C512",   "rr27C512"),
    ("Roadrunner : 27C256",    "27C256",   "rr27C256"),
    ("Roadrunner : 27C128",    "27C128",   "rr27C128"),
    ("Roadrunner : 27C64",     "27C64",    "rr27C64"),
    ("Roadrunner : 29F400",    "29F400",   "rr29F400"),
]

def build_olc(descriptor: str, part_number: str, base_data: bytes) -> bytes:
    """Build an OLC file for the given chip descriptor."""
    now = datetime.datetime.now()
    date_str = now.strftime("%Y/%m/%d")
    time_str = now.strftime("%H:%M:%S")

    def field(tag: str, value: str) -> bytes:
        """Encode a tagged text field."""
        tag_byte = ord(tag)
        val_bytes = value.encode("ascii")
        # Format: [tag_byte] [0x00] [length_byte] [value_bytes] [0x00]
        return bytes([tag_byte, 0x00, len(val_bytes)]) + val_bytes + b"\x00"

    # Find the binary payload start in the base OLC
    # The payload begins after all text fields (search for the 'e' field
    # marker byte 0x65 followed by binary data start)
    # From analysis: binary starts at approximately byte 105
    PAYLOAD_START = 105
    binary_payload = base_data[PAYLOAD_START:]

    # Build header
    desc_bytes = descriptor.encode("ascii") + b"\x00"
    config     = bytes([0x09, 0x0F, 0xF0, 0x0F, 0xF0, 0x0F, 0xF0, 0x0F, 0xF0,
                        0x00, 0x00, 0x01])

    fields  = b""
    fields += field("a", "ols4-32.ncd")
    fields += field("b", part_number)
    fields += field("c", date_str)
    fields += field("d", time_str)
    # Field 'e' header (tag + binary follows)
    fields += bytes([0x65, 0x20])   # 'e' + space (matches original format)

    olc = desc_bytes + config + fields + binary_payload
    return olc


def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))

    # Load base OLC binary section
    if not os.path.exists(BASE_OLC):
        print(f"ERROR: Base OLC not found: {BASE_OLC}")
        print("Run this script on the machine where WinOLS is installed.")
        sys.exit(1)

    with open(BASE_OLC, "rb") as f:
        base_data = f.read()
    print(f"Base OLC loaded: {len(base_data)} bytes")

    for descriptor, part, suffix in PROFILES:
        olc_bytes = build_olc(descriptor, part, base_data)
        out_path  = os.path.join(out_dir, f"{suffix}.olc")
        with open(out_path, "wb") as f:
            f.write(olc_bytes)
        print(f"  Generated: {out_path} ({len(olc_bytes)} bytes)")

    print()
    print("To install, copy *.olc to:")
    print("  C:\\Program Files\\EVC\\WinOLS\\olc\\")
    print()
    print("WinOLS will then list 'Roadrunner : 27C512' etc. in the Simulator menu.")


if __name__ == "__main__":
    main()
