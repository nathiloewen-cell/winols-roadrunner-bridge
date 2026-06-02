"""
Reverse Engineering der Roadrunner Verschlüsselung.

Plaintext: 0x00..0xFF (bekannt, wir haben es selbst geschrieben)
Ciphertext: aus USB-Capture extrahiert
Key = Ciphertext XOR Plaintext
"""
import sys
sys.stdout.reconfigure(line_buffering=True)

# Aus USB-Capture extrahierte TX-Daten (nach dem 8-byte Header)
# Block 0 (Adresse 0x0000): Header 57 00 BF 43 36 D9 88 6F, dann 256 verschlüsselte Bytes
HEADER_0 = bytes.fromhex("5700bf4336d9886f")
CIPHER_0_HEX = "01e6a47735d6b05f39d68c17cda6582fd1a67437e596601fe9967c37dda6a86f21e64437955610df99566cd7eda6782ff1a614f74516c09f4916dcb77d26c86fc166e477f556f05ff956cc170d26182f112634372516201f29163c371d2668ef61e60437d556d05fd9562cd7ada6b8afb1a654f70516001f09161c373d26086f81e62477b5d6305fb9d60c174da6d82f51a6f4376596e01f6996fc375da6286fa1e6c437155690df1956ecd76da6f82f71a694f7c516409fc9165cb7fd26486f416664777556705f79564c178d26982f9126b437a516a01fa916bc379d26e8efe1e684375556505f5956acd72da638af31a6d4f78516801f89169c37bd268870"

# Block 1 (Adresse 0x0100): Header 57 00 22 49 18 FF 92 15
HEADER_1 = bytes.fromhex("570022491 8ff9215".replace(" ",""))
CIPHER_1_HEX = "eb984e3ddf88621deb807e35dfb052c5aba8aead5f38c28d6b10fea55f20d2b56b38ce9d5f6822fdab603e955f10d2a56b082ecd9f58022debb07ec59f4012d56bd84efd5fc862dd6bc07ef55ff05285abe8aeed5ff842cd6bd07ee55fe052f56bf84edd5f28223d2b203ed55fd052e56bc8ae8d9f9882ed6bf07e859f809295eb184ebddf08629deb007eb5df305245ab28ae2d5fb8c20d6b90fe255fa0d2356bb8ce1d5fe8227dabe03e155f90d2256b882e4d9fd802adeb307e459fc012556b584e7d5f48625d6b407e755f705205ab68ae6d5f78424d6b507e655f6052756b784e5d5fa822bd2ba03e555f5052656b48ae0d9f18826d6b707e059f0092eb"

CIPHER_0 = bytes.fromhex(CIPHER_0_HEX)
CIPHER_1 = bytes.fromhex(CIPHER_1_HEX)
PLAIN = bytes(range(256))  # 0x00, 0x01, ..., 0xFF

# Berechne XOR-Key für beide Blöcke
KEY_0 = bytes(c ^ p for c, p in zip(CIPHER_0, PLAIN))
KEY_1 = bytes(c ^ p for c, p in zip(CIPHER_1, PLAIN))

print("=== XOR-Keys ===")
print("Key Block 0 (addr=0x0000):")
for i in range(0, 256, 16):
    print(" ", " ".join(f"{b:02X}" for b in KEY_0[i:i+16]))

print("\nKey Block 1 (addr=0x0100):")
for i in range(0, 256, 16):
    print(" ", " ".join(f"{b:02X}" for b in KEY_1[i:i+16]))

print("\n=== Analyse ===")

# Prüfe Periodicität
print("\nSuche Periode in Key Block 0:")
for period in range(1, 64):
    match = True
    for i in range(period, 256):
        if KEY_0[i] != KEY_0[i % period]:
            match = False
            break
    if match:
        print(f"  PERIODE GEFUNDEN: {period}")
        break
    # Partielle Periode prüfen
    matches = sum(1 for i in range(period, 256) if KEY_0[i] == KEY_0[i % period])
    if matches > 200:
        print(f"  Fast-Periode {period}: {matches}/256 Treffer")

# XOR der beiden Keys (zeigt Differenz zwischen Blöcken)
KEY_DIFF = bytes(a ^ b for a, b in zip(KEY_0, KEY_1))
print("\nXOR(Key0, Key1) - Differenz zwischen Blöcken:")
for i in range(0, 64, 16):
    print(" ", " ".join(f"{b:02X}" for b in KEY_DIFF[i:i+16]))

# Prüfe ob KEY_1 = KEY_0 XOR Konstante
const_candidates = set(KEY_DIFF)
print(f"\nAnzahl eindeutiger Differenzbytes: {len(const_candidates)}")
if len(const_candidates) == 1:
    print(f"  ALLE GLEICH: KEY_1 = KEY_0 XOR 0x{list(const_candidates)[0]:02X}")

# Header-Analyse
print(f"\nHeader Block 0: {HEADER_0.hex()}")
print(f"Header Block 1: {HEADER_1.hex()}")
print(f"Header XOR: {bytes(a^b for a,b in zip(HEADER_0,HEADER_1)).hex()}")

# Vergleiche Header-Bytes mit Key-Start
print(f"\nKey_0[:8]: {KEY_0[:8].hex()}")
print(f"Key_1[:8]: {KEY_1[:8].hex()}")
print(f"Header_0[2:8]: {HEADER_0[2:8].hex()}")
print(f"Header_1[2:8]: {HEADER_1[2:8].hex()}")

# Prüfe ob Key aus Header abgeleitet
print("\n--- Key vs Header Vergleich ---")
for i in range(8):
    print(f"  Key_0[{i}]={KEY_0[i]:02X} Header_0[{i+2}]={HEADER_0[i+2]:02X if i+2<8 else '??'} XOR={KEY_0[i]^HEADER_0[i+2 if i+2<8 else 0]:02X}")

# Prüfe LFSR-Hypothese für 8-bit LFSR
print("\n--- LFSR-Analyse (8-bit) ---")
def check_lfsr_8(key, poly):
    state = key[0]
    for i in range(1, min(64, len(key))):
        # LFSR step
        bit = 0
        s = state
        for j in range(8):
            if poly & (1 << j):
                bit ^= (s >> j) & 1
        state = ((state >> 1) | (bit << 7)) & 0xFF
        if state != key[i]:
            return False
    return True

found_poly = None
for poly in range(1, 256):
    if check_lfsr_8(KEY_0, poly):
        print(f"  LFSR-8 passt mit Polynom 0x{poly:02X}!")
        found_poly = poly
        break

if not found_poly:
    print("  Kein einfaches 8-bit LFSR gefunden")

# LCG-Analyse: state = (a * state + c) mod 256
print("\n--- LCG-Analyse (mod 256) ---")
found_lcg = False
for a in range(1, 256, 2):  # Nur ungerade a für maximale Periode
    c = (KEY_0[1] - a * KEY_0[0]) % 256
    # Prüfe ob alle Key-Bytes passen
    state = KEY_0[0]
    ok = True
    for i in range(1, min(32, len(KEY_0))):
        state = (a * state + c) % 256
        if state != KEY_0[i]:
            ok = False
            break
    if ok:
        print(f"  LCG passt: a={a}, c={c}, state0={KEY_0[0]}")
        found_lcg = True
        break

if not found_lcg:
    print("  Kein LCG mod 256 gefunden")

# LCG mod 65536 (16-bit)
print("\n--- LCG-Analyse (mod 65536, 16-bit pairs) ---")
key_16 = []
for i in range(0, len(KEY_0)-1, 2):
    key_16.append((KEY_0[i] << 8) | KEY_0[i+1])

print(f"  16-bit Key-Werte: {[f'{v:04X}' for v in key_16[:8]]}")
found_lcg16 = False
for a in [0x0019, 0x4E6D, 0x6C07, 0x5849, 0xEEEB, 0xF935]:
    for c in range(0, 65536, 1):
        state = key_16[0]
        ok = True
        for i in range(1, min(12, len(key_16))):
            state = (a * state + c) % 65536
            if state != key_16[i]:
                ok = False
                break
        if ok:
            print(f"  LCG-16 passt: a=0x{a:04X}, c=0x{c:04X}")
            found_lcg16 = True
            break
    if found_lcg16:
        break

if not found_lcg16:
    print("  Kein standard LCG-16 gefunden")
