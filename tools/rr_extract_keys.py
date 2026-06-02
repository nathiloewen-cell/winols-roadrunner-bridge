"""Extrahiert Keys aus dem Address-Test-Capture (Plaintext = alle 0x00)"""
import sys, subprocess, re
sys.stdout.reconfigure(line_buffering=True)

TSHARK = r"C:\Program Files\Wireshark\tshark.exe"
CAP = r"C:\dev\winols-roadrunner-bridge\tools\rr_addr_test.pcapng"
PLAIN = bytes(256)  # All zeros - key = cipher

# Extract TX payloads
result = subprocess.run([TSHARK, "-r", CAP, "-T", "pdml"],
                       capture_output=True, text=True, errors='replace')
output = result.stdout + result.stderr

# Find all TX payloads of 264 bytes (write commands)
writes = []
for m in re.finditer(r'if_a_tx_payload.*?value="([0-9a-f]{528})"', output, re.DOTALL):
    hex_val = m.group(1)
    data = bytes.fromhex(hex_val)
    if data[0] == 0x57:  # CMD_WRITE
        writes.append(data)

print(f"Gefundene Write-Blöcke: {len(writes)}")
print()

# Analyze each write block
for i, w in enumerate(writes):
    cmd = w[0]
    unk = w[1]
    token = w[2:4]
    extra = w[4:7]
    cipher_data = w[7:263]  # 256 bytes of data
    checksum = w[263]

    # Key = cipher XOR plaintext (all zeros, so key = cipher)
    key = cipher_data  # XOR with 0x00 is identity

    # Verify checksum: SUM(bytes[0..262]) mod 256 = bytes[263]
    calc_cs = sum(w[:263]) % 256
    cs_ok = "✓" if calc_cs == checksum else "✗"

    print(f"Block {i}: Token={token.hex().upper()} Extra={extra.hex().upper()} CS={cs_ok}")
    print(f"  KEY[:16]: {key[:16].hex().upper()}")
    print(f"  KEY[120:128]: {key[120:128].hex().upper()}")
    print(f"  KEY[248:256]: {key[248:256].hex().upper()}")
    print()

# Find address encoding pattern
print("=== TOKEN + EXTRA ANALYSIS ===")
print(f"{'Block':5} {'Token':8} {'Extra':10} {'Address_guess'}")
# Addresses written: 0x0000, 0x0100, 0x0200, 0x0300 (each 2 blocks)
addrs = [0x0000, 0x0000, 0x0100, 0x0100, 0x0200, 0x0200, 0x0300, 0x0300]
for i, (w, addr) in enumerate(zip(writes, addrs[:len(writes)])):
    token = w[2:4]
    extra = w[4:7]
    print(f"  {i:2d}: {token.hex():8} {extra.hex():10} addr=0x{addr:04X}")

# Compare Extra bytes for same token at different addresses
print("\n=== Extra-Byte Pattern (Token BF43) ===")
bf43_extras = [(w[4:7], i//2 * 0x100) for i, w in enumerate(writes) if w[2:4] == b'\xBF\x43']
for extra, addr in bf43_extras:
    print(f"  addr=0x{addr:04X}: extra={extra.hex().upper()}")

print("\n=== Extra-Byte Differenzen (BF43 sequential) ===")
for j in range(1, len(bf43_extras)):
    prev = bf43_extras[j-1][0]
    curr = bf43_extras[j][0]
    diff_addr = bf43_extras[j][1] - bf43_extras[j-1][1]
    diff_extra = bytes(a^b for a,b in zip(curr,prev))
    print(f"  delta_addr=0x{diff_addr:04X}: extra_xor={diff_extra.hex().upper()}, curr={curr.hex().upper()}")

# Full key comparison for BF43 token at different addresses
print("\n=== Key-Unterschied zwischen Adressen (BF43) ===")
bf43_writes = [w for w in writes if w[2:4] == b'\xBF\x43']
if len(bf43_writes) >= 2:
    k0 = bf43_writes[0][7:263]
    k1 = bf43_writes[1][7:263]
    key_diff = bytes(a^b for a,b in zip(k0, k1))
    unique_diffs = len(set(key_diff))
    print(f"  XOR(Key_addr0, Key_addr1) - erste 16: {key_diff[:16].hex().upper()}")
    print(f"  Unique values: {unique_diffs}")
    # Check if diff is constant
    if unique_diffs <= 2:
        print(f"  FAST KONSTANT! diff={set(key_diff)}")

print("\n=== Key für addr=0x0000, BF43 token ===")
if bf43_writes:
    k = bf43_writes[0][7:263]
    print("Key:")
    for row in range(0, 256, 16):
        print(f"  [{row:3d}]: {' '.join(f'{b:02X}' for b in k[row:row+16])}")
