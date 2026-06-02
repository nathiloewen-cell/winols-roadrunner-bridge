"""
Reverse Engineering der Roadrunner Verschlüsselung.
Extrahiert Keys aus 2 Captures mit bekanntem Plaintext:
1. Test: 0x00..0xFF (128x wiederholt für 32KB)
2. ECU: Echte Daten (aus rr_full_read.bin)
"""
import sys, struct
sys.stdout.reconfigure(line_buffering=True)

# Alle Write-Blöcke aus den Captures (hex-Strings nach dem 57 00 Header)
# Format: (token_2bytes, extra_bytes_before_data, cipherdata_256bytes, checksum)
# Aus test_capture (Plaintext = 0x00..0xFF für alle Blöcke):
TEST_BLOCKS = [
    # (token_hex, header_extra_hex, cipher_hex)  -- cipher = 256 bytes nach dem 8-byte header
    ("BF43", "36D9886F", "01E6A47735D6B05F39D68C17CDA6582FD1A67437E596601FE9967C37DDA6A86F21E64437955610DF99566CD7EDA6782FF1A614F74516C09F4916DCB77D26C86FC166E477F556F05FF956CC170D26182F112634372516201F29163C371D2668EF61E60437D556D05FD9562CD7ADA6B8AFB1A654F70516001F09161C373D26086F81E62477B5D6305FB9D60C174DA6D82F51A6F4376596E01F6996FC375DA6286FA1E6C437155690DF1956ECD76DA6F82F71A694F7C516409FC9165CB7FD26486F416664777556705F79564C178D26982F9126B437A516A01FA916BC379D26E8EFE1E684375556505F5956ACD72DA638AF31A6D4F78516801F89169C37BD268870"),
    ("2249", "18FF9215", "EB984E3DDF88621DEB807E35DFB052C5ABA8AEAD5F38C28D6B10FEA55F20D2B56B38CE9D5F6822FDAB603E955F10D2A56B082ECD9F58022DEBB07EC59F4012D56BD84EFD5FC862DD6BC07EF55FF05285ABE8AEED5FF842CD6BD07EE55FE052F56BF84EDD5F28223D2B203ED55FD052E56BC8AE8D9F9882ED6BF07E859F809295EB184EBDDF08629DEB007EB5DF305245AB28AE2D5FB8C20D6B90FE255FA0D2356BB8CE1D5FE8227DABE03E155F90D2256B882E4D9FD802ADEB307E459FC012556B584E7D5F48625D6B407E755F705205AB68AE6D5F78424D6B507E655F6052756B784E5D5FA822BD2BA03E555F5052656B48AE0D9F18826D6B707E059F0092EB"),
]

# ECU-Blöcke (Plaintext = echte Roadrunner-Daten aus rr_full_read.bin)
ECU_BLOCKS = [
    # Block 0: repeating 09 99 (128x = 256 bytes)
    ("BF43", "03660999", "09990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999099909990999CB"),
    # Block 1: complex data
    ("2249", "395F32BC", "26881AA40E9002ECF6F8EA941E80129C06E8FA846E70624C56584A747E60727C66485A644E5042AC36B82A545E40525C46A83A44AE30A20C96188A34BE20B23CA6089A248E10826C76786A149E00921C86687A04EEF0E2CCD6D8CAF4FEE0F2FCE6C8DAE4CED0C22CB638AAD4DEC0D2DCC628BAC42EB0228C16980AB43EA032BC26881AA40E9002ECF6F8EA941E80129C06E8FA846E70624C56584A747E60727C66485A644E5042AC36B82A545E40525C46A83A44AE30A20C96188A34BE20B23CA6089A248E10826C76786A149E00921C86687A04EEF0E2CCD6D8CAF4FEE0F2FCE6C8DAE4CED0C22CB638AAD4DEC0D2DCC628BAC42EB0228C16980AB43EA0328C"),
    # Block 4: repeating a3 03 e3 c3...
    ("46B9", "49BCA303", "E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A303E3C323836343A3FE"),
]

def parse_block(token_hex, header_extra_hex, cipher_hex):
    """Parst einen Block und gibt (token, header_extra, cipher_256, checksum) zurück."""
    token = bytes.fromhex(token_hex)
    header_extra = bytes.fromhex(header_extra_hex)
    full_data = bytes.fromhex(cipher_hex)
    # Alles bis auf letztes Byte = cipher, letztes = checksum
    cipher = full_data[:-1]
    checksum = full_data[-1]
    return token, header_extra, cipher, checksum

print("=== Analyse der Roadrunner Verschlüsselung ===\n")

# Test-Block 0: Plaintext = 0x00..0xFF
token, hdr, cipher, cs = parse_block(*TEST_BLOCKS[0])
plain = bytes(range(256))
key_test_0 = bytes(c ^ p for c, p in zip(cipher, plain))
print(f"TEST Block 0: token={token.hex()} hdr={hdr.hex()}")
print(f"  Cipher[:8]: {cipher[:8].hex()}")
print(f"  Key[:8]:    {key_test_0[:8].hex()}")
print(f"  Key SUM:    0x{sum(key_test_0) % 256:02X}")

# Test-Block 1
token1, hdr1, cipher1, cs1 = parse_block(*TEST_BLOCKS[1])
key_test_1 = bytes(c ^ p for c, p in zip(cipher1, plain))
print(f"\nTEST Block 1: token={token1.hex()} hdr={hdr1.hex()}")
print(f"  Key[:8]:    {key_test_1[:8].hex()}")

# ECU Block 0: Plaintext = 0x09 0x99 repeating
token_e0, hdr_e0, cipher_e0, cs_e0 = parse_block(*ECU_BLOCKS[0])
plain_e0 = bytes([0x09, 0x99] * 128)  # 256 bytes of repeating 09 99
key_ecu_0 = bytes(c ^ p for c, p in zip(cipher_e0, plain_e0))
print(f"\nECU Block 0: token={token_e0.hex()} hdr={hdr_e0.hex()}")
print(f"  Key[:8]:    {key_ecu_0[:8].hex()}")

# Verifikation: key_test_0 == key_ecu_0? (gleicher Token = gleicher Block)
print(f"\nKEY VERGLEICH für Block 0 (BF43):")
print(f"  Test key: {key_test_0[:16].hex()}")
print(f"  ECU  key: {key_ecu_0[:16].hex()}")
print(f"  GLEICH:   {key_test_0 == key_ecu_0}")

# Wenn gleich: der Key ist datenunabhängig! Nur vom Block/Token abhängig
if key_test_0 == key_ecu_0:
    print("  ✓ KEY IST DATENUNABHÄNGIG! Nur vom Block abhängig.")
else:
    diff = sum(1 for a,b in zip(key_test_0, key_ecu_0) if a != b)
    print(f"  {diff}/256 Bytes verschieden")

# ECU Block 1
token_e1, hdr_e1, cipher_e1, cs_e1 = parse_block(*ECU_BLOCKS[1])
# Plaintext für Block 1: bytes 256..511 aus rr_full_read.bin
# Die ECU-Daten erkennen wir aus dem Muster in Block 1
# cipher nach hdr: 32bc26881aa40e9002ec...
# Der Header enthält auch verschlüsselte Daten

# Analyse der Token-Reihenfolge
tokens = [
    bytes.fromhex("BF43"),
    bytes.fromhex("2249"),
    bytes.fromhex("E77E"),
    bytes.fromhex("CA3B"),
    bytes.fromhex("46B9"),
    bytes.fromhex("5F41"),
    bytes.fromhex("97D3"),
    bytes.fromhex("A22E"),
    bytes.fromhex("54FD"),
    bytes.fromhex("C506"),
    bytes.fromhex("1994"),
    bytes.fromhex("DD80"),
]
print("\n=== TOKEN-SEQUENZ ANALYSE ===")
print("Tokens als 16-bit LE Werte:")
vals = [(b[0] | (b[1]<<8)) for b in tokens]
for i, v in enumerate(vals):
    print(f"  Block {i:2d}: 0x{v:04X} = {v}")

# Prüfe LCG: next = (a * current + c) mod 65536
print("\nSuche LCG-Parameter...")
found = False
for a in range(1, 65536, 2):  # Nur ungerade
    c = (vals[1] - a * vals[0]) % 65536
    ok = True
    for i in range(1, len(vals)):
        if (a * vals[i-1] + c) % 65536 != vals[i]:
            ok = False
            break
    if ok:
        print(f"  LCG GEFUNDEN: a=0x{a:04X}, c=0x{c:04X}")
        found = True
        break

if not found:
    print("  Kein einfacher LCG gefunden")
    # Versuche Differenz zwischen aufeinanderfolgenden Tokens
    print("  Differenzen:")
    for i in range(1, len(vals)):
        diff = (vals[i] - vals[i-1]) % 65536
        ratio = vals[i] / vals[i-1] if vals[i-1] != 0 else 0
        print(f"    {i}: diff=0x{diff:04X}, xor=0x{vals[i]^vals[i-1]:04X}")

# Analysiere Key-Periodizität
print("\n=== KEY PERIODICITÄT (Block 0) ===")
k = key_test_0
for p in range(1, 256):
    matches = sum(1 for i in range(p, 256) if k[i] == k[i % p])
    if matches >= 240:  # > 93.75%
        print(f"  Mögliche Periode {p}: {matches}/256 Treffer ({100*matches/256:.1f}%)")

# Untersuche Bit-Muster im Key
print("\n=== BIT-MUSTER ANALYSE ===")
# Bit 7 (MSB) von jedem Key-Byte
msb = [k[i] >> 7 for i in range(256)]
msb_str = "".join(str(b) for b in msb)
print(f"  MSB-Sequenz (erste 64): {msb_str[:64]}")
# Prüfe Periode für MSB
for p in range(1, 64):
    if all(msb[i] == msb[i % p] for i in range(p, 256)):
        print(f"  MSB Periode: {p}")
        break

# Untere 7 Bits
low7 = [k[i] & 0x7F for i in range(256)]
for p in range(1, 256):
    if all(low7[i] == low7[i % p] for i in range(p, 256)):
        print(f"  Low-7-Bit Periode: {p}")
        break

# 2-bit Gruppen
print("\nKey in 4-byte Blöcken (erste 8):")
for i in range(0, 32, 4):
    print(f"  [{i:3d}]: {' '.join(f'{k[i+j]:02X}' for j in range(4))}")

# Versuche LFSR-Erkennung für 16-bit Pairs
print("\n=== 16-BIT LFSR SUCHE ===")
k16 = [(k[i*2] << 8 | k[i*2+1]) for i in range(128)]
print(f"16-bit Values: {[f'{v:04X}' for v in k16[:8]]}")

# Brute-force LFSR-16
found_lfsr = False
# Galois LFSR: next = (state >> 1) ^ (-(state & 1) & poly)
for poly in range(0x8000, 0x10000):
    state = k16[0]
    ok = True
    for i in range(1, min(20, len(k16))):
        if state & 1:
            state = (state >> 1) ^ poly
        else:
            state = state >> 1
        if state != k16[i]:
            ok = False
            break
    if ok:
        print(f"  Galois LFSR: poly=0x{poly:04X}")
        found_lfsr = True
        break

if not found_lfsr:
    print("  Kein Galois LFSR-16 gefunden")
    # Prüfe ob es additive Folge gibt
    diffs = [(k16[i+1] - k16[i]) % 65536 for i in range(len(k16)-1)]
    unique_diffs = len(set(diffs[:16]))
    print(f"  Diff-Vielfalt (erste 16): {unique_diffs}")
    print(f"  Erste Diffs: {[f'{d:04X}' for d in diffs[:8]]}")

print("\nAnalyse abgeschlossen.")
