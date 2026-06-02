"""
PRNG-Analyse: 4KB Write = 32 Blöcke → PRNG-Formel finden
"""
import sys, subprocess, re
sys.stdout.reconfigure(line_buffering=True)

TSHARK = r"C:\Program Files\Wireshark\tshark.exe"

def extract_keys(cap_file):
    result = subprocess.run([TSHARK, "-r", cap_file, "-T", "pdml"],
                           capture_output=True, text=True, errors='replace')
    output = result.stdout + result.stderr
    keys = []
    for m in re.finditer(r'if_a_tx_payload.*?value="([0-9a-f]{528})"', output, re.DOTALL):
        data = bytes.fromhex(m.group(1))
        if data[0] == 0x57:  # CMD_WRITE
            keys.append({'token': data[2:4].hex(), 'extra': data[4:7].hex(),
                         'key': data[7:263]})  # cipher = key since plaintext=zeros
    return keys

# Load base key from addr=0x0000 test
CAP_ADDR = r"C:\dev\winols-roadrunner-bridge\tools\rr_addr_test.pcapng"
CAP_4K = r"C:\dev\winols-roadrunner-bridge\tools\rr_prng_16blocks.pcapng"

addr_blocks = extract_keys(CAP_ADDR)
k4_blocks = extract_keys(CAP_4K)

BASE_KEY = bytes(addr_blocks[0]['key'])  # BF43 at addr=0x0000, shift=0
print(f"Base key: {BASE_KEY[:8].hex()}")

def find_shift(base, target):
    first = target[0]
    for s in range(256):
        if base[s] == first:
            if all(target[i] == base[(i+s)%256] for i in range(256)):
                return s
    return None

# Analyze 4K write blocks
print(f"\n=== 4K Write: {len(k4_blocks)} Blöcke ===")
shifts = []
for i, b in enumerate(k4_blocks):
    s = find_shift(BASE_KEY, bytes(b['key']))
    shifts.append(s)
    print(f"  Block {i:2d} (token={b['token']}, extra={b['extra']}): shift={s}")

# Separate BF43 and 2249 shifts
bf43_shifts = [shifts[i] for i in range(0, len(shifts), 2)]
s2249_shifts = [shifts[i] for i in range(1, len(shifts), 2)]
print(f"\nBF43 shifts: {bf43_shifts}")
print(f"2249 shifts: {s2249_shifts}")

# Find PRNG formula for BF43 sequence
print("\n=== PRNG-Formel Suche (BF43) ===")
s = bf43_shifts
print(f"Sequenz: {s}")

# Check LCG: s[n+1] = (a*s[n] + b) mod 256
print("LCG mod 256:")
if len(s) >= 3:
    for a in range(1, 256):
        b_cand = (s[1] - a*s[0]) % 256
        ok = True
        for i in range(1, len(s)):
            if (a * s[i-1] + b_cand) % 256 != s[i]:
                ok = False
                break
        if ok:
            print(f"  GEFUNDEN: a={a} (0x{a:02X}), b={b_cand} (0x{b_cand:02X})")
            print(f"  Formel: shift[n+1] = ({a} * shift[n] + {b_cand}) % 256")
            break

# Check if shift is directly base_key lookup: shift[n] = base_key[shift[n-1]]?
print("\nBase-Key-Lookup: shift[n] = base_key[shift[n-1]]?")
ok = True
for i in range(1, len(s)):
    expected = BASE_KEY[s[i-1]]
    if expected != s[i]:
        ok = False
        print(f"  Mismatch at i={i}: base_key[{s[i-1]}]={expected} vs shift[{i}]={s[i]}")
        break
if ok:
    print("  ✓ VOLLSTÄNDIGE ÜBEREINSTIMMUNG!")
    print("  PRNG: shift[n] = BASE_KEY[shift[n-1]]")
    print("  Initialer shift: 0 (bzw. bekannt)")

# Verify with 2249 sequence
print("\n=== Verifikation mit 2249 Sequenz ===")
s2 = s2249_shifts
print(f"2249 Sequenz: {s2}")
ok2 = all(BASE_KEY[s2[i-1]] == s2[i] for i in range(1, len(s2)))
if ok2:
    print("  ✓ 2249 folgt auch: shift[n] = BASE_KEY[shift[n-1]]")
else:
    print("  ✗ 2249 passt nicht zum selben Muster")
    for i in range(1, min(5, len(s2))):
        print(f"    base_key[{s2[i-1]}]={BASE_KEY[s2[i-1]]} vs s2[{i}]={s2[i]}")

# Also check if BF43 and 2249 are interleaved in same PRNG
print("\n=== Gemeinsame PRNG (alle Blöcke) ===")
all_shifts = shifts
ok3 = all(BASE_KEY[all_shifts[i-1]] == all_shifts[i] for i in range(1, len(all_shifts)))
if ok3:
    print("  ✓ ALLE Blöcke folgen: shift[n] = BASE_KEY[shift[n-1]]")
else:
    for i in range(1, min(10, len(all_shifts))):
        expected = BASE_KEY[all_shifts[i-1]]
        match = "✓" if expected == all_shifts[i] else "✗"
        print(f"  {match} base_key[{all_shifts[i-1]}]={expected} vs all[{i}]={all_shifts[i]}")

print("\n=== Zusammenfassung ===")
print(f"Base Key (256 bytes): {BASE_KEY.hex()}")
print(f"PRNG: shift[0]=0, shift[n] = BASE_KEY[shift[n-1]]")
print(f"cipher[i] = plaintext[i] XOR BASE_KEY[(i + shift[block]) % 256]")
