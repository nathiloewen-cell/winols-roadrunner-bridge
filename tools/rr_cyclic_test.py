"""
Verifiziert: Sind die Keys zyklische Rotationen voneinander?
Wenn key_addr1[i] = key_addr0[(i+shift)%256], was ist der shift?
"""
import sys, subprocess, re
sys.stdout.reconfigure(line_buffering=True)

TSHARK = r"C:\Program Files\Wireshark\tshark.exe"
CAP = r"C:\dev\winols-roadrunner-bridge\tools\rr_addr_test.pcapng"

result = subprocess.run([TSHARK, "-r", CAP, "-T", "pdml"],
                       capture_output=True, text=True, errors='replace')
output = result.stdout + result.stderr

writes = []
for m in re.finditer(r'if_a_tx_payload.*?value="([0-9a-f]{528})"', output, re.DOTALL):
    data = bytes.fromhex(m.group(1))
    if data[0] == 0x57:
        writes.append(data)

# Keys (all-zero plaintext, so key = cipher data)
keys = [w[7:263] for w in writes]
tokens = [w[2:4].hex() for w in writes]
extras = [w[4:7].hex() for w in writes]

print(f"Blocks: {len(keys)}")
for i, (k, t, e) in enumerate(zip(keys, tokens, extras)):
    print(f"  Block {i}: token={t} extra={e} key[:4]={k[:4].hex()}")

print("\n=== Zyklische Rotations-Test ===")
base_key = keys[0]  # addr=0x0000, token BF43

# Find shift for each subsequent key relative to base
def find_shift(k_base, k_target):
    """Finde shift s so dass k_target[i] = k_base[(i+s)%256] für alle i."""
    # Look for first byte of k_target in k_base
    first_byte = k_target[0]
    candidates = [i for i in range(256) if k_base[i] == first_byte]
    for s in candidates:
        if all(k_target[i] == k_base[(i + s) % 256] for i in range(256)):
            return s
    return None

for i, (k, t, e) in enumerate(zip(keys, tokens, extras)):
    if i == 0:
        print(f"  Block 0: BASE (token={t}, extra={e})")
        continue
    s = find_shift(base_key, k)
    print(f"  Block {i} (token={t}, addr=0x{i//2*0x100:04X}, extra={e}): shift={s}")
    if s is not None:
        # Verify
        ok = all(k[i] == base_key[(i+s)%256] for i in range(256))
        print(f"    Verifikation: {'✓ VOLLSTÄNDIG' if ok else '✗ FEHLER'}")

# Check if all same-token blocks use the base_key
print("\n=== Token 2249 Basis-Key ===")
key2249_0 = keys[1]  # First 2249 block
print(f"  token=2249 key[:8]: {key2249_0[:8].hex()}")
for i, (k, t) in enumerate(zip(keys, tokens)):
    if t == "2249" and i > 1:
        s = find_shift(key2249_0, k)
        print(f"  Block {i} (addr=0x{i//2*0x100:04X}): shift={s}")

# Now test: is shift = addr * factor?
print("\n=== Shift-Formel ===")
shifts_bf43 = []
for i in range(0, len(keys), 2):  # BF43 blocks (even indices)
    if i == 0:
        shifts_bf43.append(0)
        continue
    s = find_shift(base_key, keys[i])
    shifts_bf43.append(s)

print(f"Shifts für BF43 bei Adressen 0x0000, 0x0100, 0x0200, 0x0300:")
for addr_idx, s in enumerate(shifts_bf43):
    addr = addr_idx * 0x100
    print(f"  addr=0x{addr:04X}: shift={s}")

if len(shifts_bf43) >= 2 and shifts_bf43[0] == 0:
    # Check linearity
    if len(shifts_bf43) >= 3:
        d1 = shifts_bf43[1] - shifts_bf43[0]
        d2 = shifts_bf43[2] - shifts_bf43[1]
        d3 = shifts_bf43[3] - shifts_bf43[2] if len(shifts_bf43) > 3 else None
        print(f"\nDifferenzen: d1={d1}, d2={d2}, d3={d3}")
        if d1 == d2:
            print(f"✓ LINEAR! shift = (addr / 0x100) * {d1} = addr * {d1/0x100:.4f}")
            shift_per_byte = d1 / 0x100
            print(f"  shift_per_byte = {d1}/{0x100} = {shift_per_byte}")
            if d1 % 0x100 == 0:
                print(f"  shift_per_256 = {d1 // 0x100} * 0x100")
            else:
                print(f"  shift for addr 0xN00 = N * {d1}")

print("\n=== Base Key (addr=0x0000, token=BF43) - erste 32 Bytes ===")
print(f"{base_key[:32].hex()}")
print(f"\nAlle 256 unique? {len(set(base_key)) == 256}")
