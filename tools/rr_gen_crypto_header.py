"""Generiert rr_crypto.h mit allen Konstanten für Sprint 3"""
import sys, subprocess, re
sys.stdout.reconfigure(line_buffering=True)

TSHARK = r"C:\Program Files\Wireshark\tshark.exe"
CAP_ADDR = r"C:\dev\winols-roadrunner-bridge\tools\rr_addr_test.pcapng"
CAP_FULL = r"C:\dev\winols-roadrunner-bridge\tools\rr_prng_full.pcapng"

def extract_write_blocks(cap_file):
    result = subprocess.run([TSHARK, "-r", cap_file, "-T", "pdml"],
                           capture_output=True, text=True, errors='replace')
    output = result.stdout + result.stderr
    blocks = []
    for m in re.finditer(r'if_a_tx_payload.*?value="([0-9a-f]{528})"', output, re.DOTALL):
        data = bytes.fromhex(m.group(1))
        if data[0] == 0x57:
            blocks.append({
                'token': data[2:4],
                'extra0': data[4],
                'extra12': data[5:7],
                'key': data[7:263],
                'checksum': data[263],
                'full': data
            })
    return blocks

# Get base key (from addr test, block 0 = all-zeros write = cipher IS the key)
addr_blocks = extract_write_blocks(CAP_ADDR)
BASE_KEY = bytes(addr_blocks[0]['key'])  # shift=0, cipher=key

def find_shift(base, target):
    b = bytes(target)
    f = b[0]
    for s in range(256):
        if base[s] == f:
            if all(b[i] == base[(i+s)%256] for i in range(256)):
                return s
    return None

# Extract full 512-block sequence from 64KB capture
full_blocks = extract_write_blocks(CAP_FULL)
print(f"Blocks extracted: {len(full_blocks)}")

shifts = []
tokens = []
extra0s = []
for b in full_blocks:
    s = find_shift(BASE_KEY, bytes(b['key']))
    shifts.append(s if s is not None else 0)
    tokens.append(b['token'])
    extra0s.append(b['extra0'])

print(f"Shifts computed: {len([s for s in shifts if s is not None])} valid")

# Verify our encryption formula for first 3 blocks
print("\nVerifikation:")
for i in range(3):
    cipher = bytes(full_blocks[i]['key'])  # plaintext=0, cipher=key
    expected = bytes(BASE_KEY[(j + shifts[i]) % 256] for j in range(256))
    ok = cipher == expected
    print(f"  Block {i}: shift={shifts[i]}, token={tokens[i].hex()}: {'✓' if ok else '✗'}")

# Generate C header
out = []
out.append("/*")
out.append(" * rr_crypto.h - Roadrunner MoatesWare Encryption Constants")
out.append(" * Auto-generated from USB capture analysis.")
out.append(" * Protocol: cipher[i] = plain[i] XOR BASE_KEY[(i + SHIFT[block]) % 256]")
out.append(" * PRNG starts at shift[0]=0 after Roadrunner power-cycle.")
out.append(" */")
out.append("#pragma once")
out.append("#include <windows.h>")
out.append("")
out.append("/* Baud rate for Roadrunner communication */")
out.append("#define RR_BAUD      115200")
out.append("#define RR_ACK_BYTE  0x4F  /* 'O' = OK */")
out.append("#define RR_CMD_WRITE 0x57  /* 'W' */")
out.append("#define RR_CMD_READ  0x52  /* 'R' */")
out.append("")

# Base key
out.append("/* 256-byte XOR base key (permutation of 0..255) */")
out.append("static const BYTE RR_BASE_KEY[256] = {")
row = "    "
for i, b in enumerate(BASE_KEY):
    row += f"0x{b:02X},"
    if (i+1) % 16 == 0:
        out.append(row)
        row = "    "
    else:
        row += " "
if row.strip(): out.append(row)
out.append("};")
out.append("")

# Shift table
out.append("/* PRNG shift for each block (512 blocks = 64KB, starting from power-on) */")
out.append("static const BYTE RR_SHIFTS[512] = {")
row = "    "
for i, s in enumerate(shifts[:512]):
    row += f"{s:3d},"
    if (i+1) % 16 == 0:
        out.append(row)
        row = "    "
    else:
        row += " "
if row.strip(): out.append(row)
out.append("};")
out.append("")

# Token sequence (stored as flat array of 1024 bytes: token_hi, token_lo, ...)
out.append("/* Token bytes for each block (hi, lo pairs) */")
out.append("static const BYTE RR_TOKENS[512][2] = {")
for i, t in enumerate(tokens[:512]):
    if i % 8 == 0: out.append("    ")
    line = out[-1]
    out[-1] = line + f"{{0x{t[0]:02X},0x{t[1]:02X}}},"
    if (i+1) % 8 == 0:
        out[-1] = out[-1]  # newline done by loop
        out.append("    ")
out.append("};")
out.append("")

# Extra0 sequence
out.append("/* Extra byte 0 for each block header */")
out.append("static const BYTE RR_EXTRA0[512] = {")
row = "    "
for i, e in enumerate(extra0s[:512]):
    row += f"0x{e:02X},"
    if (i+1) % 16 == 0:
        out.append(row)
        row = "    "
    else:
        row += " "
if row.strip(): out.append(row)
out.append("};")
out.append("")

# Encrypt function
out.append("/* Encrypt 256-byte plaintext block for Roadrunner write */")
out.append("static void rr_encrypt_block(int block_nr, const BYTE* plain, BYTE* cipher) {")
out.append("    int shift = RR_SHIFTS[block_nr % 512];")
out.append("    for (int i = 0; i < 256; i++)")
out.append("        cipher[i] = plain[i] ^ RR_BASE_KEY[(i + shift) & 0xFF];")
out.append("}")
out.append("")

# Write block function (COM port)
out.append("/* Write one 256-byte block to Roadrunner (returns 1 on success) */")
out.append("static int rr_write_block_com(HANDLE hCom, int block_nr,")
out.append("                              const BYTE* plain_256) {")
out.append("    BYTE cipher[256], header[7], cs = 0;")
out.append("    DWORD written, got;")
out.append("    int shift = RR_SHIFTS[block_nr % 512];")
out.append("    /* Header */")
out.append("    header[0] = RR_CMD_WRITE;")
out.append("    header[1] = 0x00;")
out.append("    header[2] = RR_TOKENS[block_nr % 512][0];")
out.append("    header[3] = RR_TOKENS[block_nr % 512][1];")
out.append("    header[4] = RR_EXTRA0[block_nr % 512];")
out.append("    header[5] = RR_BASE_KEY[(254 + shift) & 0xFF];")
out.append("    header[6] = RR_BASE_KEY[(255 + shift) & 0xFF];")
out.append("    /* Encrypt */")
out.append("    for (int i = 0; i < 256; i++)")
out.append("        cipher[i] = plain_256[i] ^ RR_BASE_KEY[(i + shift) & 0xFF];")
out.append("    /* Checksum = SUM(header + cipher) % 256 */")
out.append("    for (int i = 0; i < 7; i++) cs += header[i];")
out.append("    for (int i = 0; i < 256; i++) cs += cipher[i];")
out.append("    /* Send */")
out.append("    WriteFile(hCom, header, 7, &written, NULL);")
out.append("    WriteFile(hCom, cipher, 256, &written, NULL);")
out.append("    WriteFile(hCom, &cs, 1, &written, NULL);")
out.append("    /* ACK */")
out.append("    BYTE ack = 0;")
out.append("    ReadFile(hCom, &ack, 1, &got, NULL);")
out.append("    return (got == 1 && ack == RR_ACK_BYTE) ? 1 : 0;")
out.append("}")

header_path = r"C:\dev\winols-roadrunner-bridge\src\proxy\rr_crypto.h"
with open(header_path, "w") as f:
    f.write("\n".join(out) + "\n")
print(f"\nGenerated: {header_path}")
print(f"  BASE_KEY: 256 bytes")
print(f"  SHIFTS: {len(shifts)} entries")
print(f"  TOKENS: {len(tokens)} pairs")
print(f"  EXTRA0: {len(extra0s)} entries")
