#!/usr/bin/env python3
"""
decode_ols_fw.py — Cypress FX2 (8051) firmware analyzer for OLS3_FW.hex

Parses the OLS300 Cypress FX2 firmware, simulates the 8051 startup path,
and extracts the EP6 IN identification packet (448 bytes) that WinOLS expects.

Cypress FX2 memory map (8051 core):
  CODE  0x0000-0x3FFF : program memory (mapped from internal/external)
  XDATA 0x0000-0x7FFF : general XDATA
  XDATA 0x4000-0x43FF : EP2 IN FIFO  (512 bytes)
  XDATA 0x4400-0x47FF : EP4 IN FIFO  (512 bytes)
  XDATA 0x4800-0x4BFF : EP6 IN FIFO  (512 bytes)  ← OLS300 uses this
  XDATA 0x4C00-0x4FFF : EP8 IN FIFO  (512 bytes)
  XDATA 0x6000-0x63FF : EP2 OUT FIFO (512 bytes)
  XDATA 0x6800-0x6BFF : EP6 OUT FIFO (512 bytes)
  SFR   0x7E00-0x7FFF : Cypress FX2 USB SFRs

Usage: python decode_ols_fw.py [path_to_OLS3_FW.hex]
"""

import sys
import struct
from collections import defaultdict

DEFAULT_HEX = r"C:\Program Files\EVC\WinOLS\OLS3_FW.hex"

# ── Intel HEX parser ─────────────────────────────────────────────────────
def parse_ihex(path):
    """Returns dict {address: byte_value} for all data records."""
    mem = {}
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line.startswith(':'): continue
            bc   = int(line[1:3],   16)
            addr = int(line[3:7],   16)
            rt   = int(line[7:9],   16)
            if rt == 0x00:  # data
                for i in range(bc):
                    mem[addr + i] = int(line[9 + i*2 : 11 + i*2], 16)
    return mem

def mem_to_binary(mem):
    if not mem: return b''
    hi = max(mem.keys())
    data = bytearray(hi + 1)
    for a, v in mem.items():
        data[a] = v
    return bytes(data)

# ── EP6 FIFO range ────────────────────────────────────────────────────────
EP6_IN_BASE  = 0x4800   # Cypress FX2 EP6 IN FIFO start
EP6_IN_END   = 0x4BFF   # Cypress FX2 EP6 IN FIFO end (512 bytes)
EP2_OUT_BASE = 0x6000
EP2_OUT_END  = 0x63FF

# ── 8051 opcode decoder (minimal — only what we need) ────────────────────
def decode_movx_writes(firmware, mem):
    """
    Scan all MOVX @DPTR,A instructions (opcode 0xF0) in program memory.
    For each, try to statically determine DPTR value at that point.

    Returns list of (code_addr, dptr_value, context_bytes) for writes
    where dptr_value is in the EP6 IN FIFO range.
    """
    code = firmware
    ep6_writes = []
    xdata_writes = defaultdict(list)   # addr → [code_addr, ...]

    i = 0
    dptr_hi = 0
    dptr_lo = 0
    a_reg   = 0

    while i < len(code):
        op = code[i]

        # MOVX @DPTR, A  (0xF0) — write A to [DPTR]
        if op == 0xF0:
            dptr = (dptr_hi << 8) | dptr_lo
            xdata_writes[dptr].append(i)
            if EP6_IN_BASE <= dptr <= EP6_IN_END:
                ep6_writes.append((i, dptr, code[max(0,i-8):i+4]))
            i += 1
            continue

        # MOV DPTR, #imm16  (0x90 hi lo) — most common DPTR load
        if op == 0x90 and i + 2 < len(code):
            dptr_hi = code[i+1]
            dptr_lo = code[i+2]
            i += 3
            continue

        # INC DPTR  (0xA3)
        if op == 0xA3:
            dptr_lo += 1
            if dptr_lo > 0xFF:
                dptr_lo = 0
                dptr_hi = (dptr_hi + 1) & 0xFF
            i += 1
            continue

        # MOV A, #imm8  (0x74 imm)
        if op == 0x74 and i + 1 < len(code):
            a_reg = code[i+1]
            i += 2
            continue

        # LCALL addr16  (0x12 hi lo) — 3 bytes
        if op == 0x12 and i + 2 < len(code):
            i += 3
            continue

        # LJMP addr16  (0x02 hi lo) — 3 bytes
        if op == 0x02 and i + 2 < len(code):
            i += 3
            continue

        # MOVX A, @DPTR  (0xE0) — read from XDATA
        if op == 0xE0:
            i += 1
            continue

        # All other opcodes: advance by 1 (approximation)
        i += 1

    return ep6_writes, dict(xdata_writes)


# ── EP6 write cluster analyzer ────────────────────────────────────────────
def extract_ep6_sequence(ep6_writes, firmware):
    """
    Group consecutive EP6 FIFO writes and reconstruct the data sequence.
    Returns sorted list of (dptr_offset, code_addr) pairs.
    """
    if not ep6_writes:
        return []

    # Sort by DPTR (write offset into FIFO)
    by_dptr = sorted(ep6_writes, key=lambda x: x[1])

    print(f"\n[+] Found {len(ep6_writes)} MOVX @DPTR,A writes targeting EP6 IN FIFO")
    print(f"    Offset range: 0x{by_dptr[0][1]:04X} – 0x{by_dptr[-1][1]:04X}")

    # Show each write with code address
    print("\n    DPTR (offset)  Code addr  A value (if known)")
    print("    " + "-"*50)
    for code_addr, dptr, ctx in by_dptr[:64]:
        off = dptr - EP6_IN_BASE
        # Try to find the most recent MOV A,#imm before this MOVX
        a_val = "?"
        for j in range(code_addr - 1, max(0, code_addr - 10), -1):
            if j < len(firmware) and firmware[j-1] == 0x74:
                a_val = f"0x{firmware[j]:02X} ({chr(firmware[j]) if 32<=firmware[j]<127 else '.'})"
                break
        print(f"    [+{off:3d}] 0x{dptr:04X}   0x{code_addr:04X}     {a_val}")

    return by_dptr


# ── Startup path tracer ───────────────────────────────────────────────────
def trace_startup(firmware, mem):
    """
    Trace the OLS300 FX2 startup path and find EP6 data writes.

    FX2 startup: 0x0000 → LJMP 0x0761 (or similar)
    Then C51 runtime → main() → init() → identification broadcast
    """
    print("\n[STARTUP TRACE]")

    # Find reset vector
    if len(firmware) > 3 and firmware[0] == 0x02:
        startup = (firmware[1] << 8) | firmware[2]
        print(f"  Reset vector: LJMP 0x{startup:04X}")
    else:
        startup = 0x0000
        print(f"  Reset vector: unknown (byte 0 = 0x{firmware[0]:02X})")

    # Scan from startup address
    print(f"  Scanning code from 0x{startup:04X}...")

    # Find all LJMP/LCALL targets (potential function addresses)
    targets = set()
    for i in range(0, min(len(firmware)-2, 0x1100)):
        if firmware[i] in (0x02, 0x12):  # LJMP, LCALL
            t = (firmware[i+1] << 8) | firmware[i+2]
            if t < len(firmware):
                targets.add(t)

    print(f"  Found {len(targets)} code targets (LJMP/LCALL destinations)")

    return sorted(targets)


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    hex_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HEX

    print(f"[+] Parsing: {hex_path}")
    mem = parse_ihex(hex_path)
    firmware = mem_to_binary(mem)

    print(f"[+] Firmware: {len(mem)} bytes mapped, max addr = 0x{max(mem.keys()):04X}")
    print(f"[+] Binary image size: {len(firmware)} bytes")

    # Show firmware hex overview
    print("\n[FIRMWARE HEX OVERVIEW - first 64 bytes]")
    for i in range(0, min(64, len(firmware)), 16):
        row = firmware[i:i+16]
        hex_str = ' '.join(f'{b:02X}' for b in row)
        asc_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in row)
        print(f"  0x{i:04X}: {hex_str:<48}  {asc_str}")

    # Trace startup
    code_targets = trace_startup(firmware, mem)

    # Find all EP6 writes
    print("\n[EP6 IN FIFO WRITE ANALYSIS]")
    print(f"  EP6 FIFO range: 0x{EP6_IN_BASE:04X} – 0x{EP6_IN_END:04X}")
    ep6_writes, all_xdata = decode_movx_writes(firmware, mem)

    if ep6_writes:
        by_dptr = extract_ep6_sequence(ep6_writes, firmware)

        # Try to reconstruct the identification packet
        print("\n[RECONSTRUCTED EP6 IDENTIFICATION PACKET]")
        id_packet = bytearray(448)

        for code_addr, dptr, ctx in ep6_writes:
            off = dptr - EP6_IN_BASE
            if 0 <= off < 448:
                # Find A register value before this write
                for j in range(code_addr - 1, max(0, code_addr - 20), -1):
                    if j >= 1 and firmware[j-1] == 0x74:
                        id_packet[off] = firmware[j]
                        break

        # Print non-zero bytes
        print("  Non-zero bytes in reconstructed packet:")
        has_data = False
        for i, b in enumerate(id_packet):
            if b != 0:
                asc = chr(b) if 32 <= b < 127 else '.'
                print(f"    [{i:3d}] 0x{i:02X}: 0x{b:02X}  '{asc}'")
                has_data = True
        if not has_data:
            print("  (no non-zero bytes found — A register values could not be statically determined)")

        # Print full hex dump
        print("\n  Full 448-byte packet hex dump:")
        for i in range(0, 448, 16):
            row = id_packet[i:i+16]
            hex_str = ' '.join(f'{b:02X}' for b in row)
            asc_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in row)
            if any(b != 0 for b in row):
                print(f"  [{i:3d}] {hex_str:<48}  {asc_str}")

    else:
        print("\n  No static EP6 writes found.")
        print("  The identification packet is built dynamically at runtime.")
        print("  → Proceed with Approach B (WinOLS memory analysis) or Approach C (fuzzer).")

    # Show ALL xdata write targets (for discovery)
    print(f"\n[ALL XDATA WRITE TARGETS] ({len(all_xdata)} unique addresses)")
    interesting = sorted((a, len(v)) for a, v in all_xdata.items()
                         if 0x4000 <= a <= 0x7FFF)
    for addr, count in interesting[:30]:
        region = ""
        if EP6_IN_BASE <= addr <= EP6_IN_END:
            region = " ← EP6 IN FIFO"
        elif 0x6000 <= addr <= 0x63FF:
            region = " ← EP2 OUT FIFO"
        elif 0x7E00 <= addr <= 0x7FFF:
            region = " ← FX2 SFR"
        print(f"  0x{addr:04X}: {count:3d} write(s){region}")

    print("\n[DONE]")
    return id_packet if ep6_writes else None


if __name__ == '__main__':
    main()
