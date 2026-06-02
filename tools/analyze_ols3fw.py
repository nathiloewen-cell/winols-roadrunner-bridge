"""
Analysiert OLS3_FW.hex (Cypress FX2 8051-Firmware für OLS300).
Sucht nach EP6 FIFO-Daten (die 448-Byte ID-Pakete die WinOLS erwartet).
"""
import sys

HEX = r"C:\Users\Nates\WinOLS_Bridge\OLS3_FW.hex"

# Parse Intel HEX → Speicher
mem = {}
with open(HEX) as f:
    for line in f:
        line = line.strip()
        if not line.startswith(':'): continue
        bc   = int(line[1:3],16)
        addr = int(line[3:7],16)
        rt   = int(line[7:9],16)
        if rt == 0x00:
            for i in range(bc):
                mem[addr+i] = int(line[9+i*2:11+i*2],16)
        elif rt == 0x01:
            break

max_addr = max(mem.keys())
print(f"Firmware: {len(mem)} bytes, max addr=0x{max_addr:04X}")

# Reset-Vektoren (8051)
print("\nReset-Vektoren:")
for addr in [0x0000,0x0003,0x000B,0x0013,0x001B,0x0023,0x002B,0x0033]:
    if addr in mem:
        b = [mem.get(addr+i,0xFF) for i in range(3)]
        label = ""
        if b[0]==0x02: label=f" LJMP 0x{b[1]:02X}{b[2]:02X}"
        elif b[0]==0xC3: label=" CLR C"
        print(f"  0x{addr:04X}: {b[0]:02X} {b[1]:02X} {b[2]:02X}{label}")

# ASCII-Strings in der Firmware
print("\nStrings (>= 5 Zeichen):")
buf=""; start=0
for a in sorted(mem.keys()):
    c=mem[a]
    if 0x20<=c<=0x7E:
        if not buf: start=a
        buf+=chr(c)
    else:
        if len(buf)>=5: print(f"  0x{start:04X}: {repr(buf)}")
        buf=""

# 0x55 0xAA (typischer OLS300 ID-Sync)
print("\n0x55 0xAA Muster:")
for a in sorted(mem.keys()):
    if mem.get(a)==0x55 and mem.get(a+1)==0xAA:
        ctx=[mem.get(a+i,0xFF) for i in range(16)]
        print(f"  0x{a:04X}: {' '.join(f'{b:02X}' for b in ctx)}")

# EP6 FIFO-Adressen im FX2: 0xF000-0xF1FF (Puffer)
# Suche nach MOVX @DPTR,A mit DPTR im Bereich 0xE600-0xF400 (FX2 SFR)
print("\nEP6-relevante Datenbereiche (Addr 0x7C00-0x7FFF):")
for a in range(0x7C00, min(0x8000, max_addr+1)):
    if a in mem:
        row = [mem.get(a+i,0xFF) for i in range(16)]
        if any(b!=0xFF for b in row):
            print(f"  0x{a:04X}: {' '.join(f'{b:02X}' for b in row)}")
    else:
        pass  # sparse

# Zeige erste 64 Bytes der Firmware
print("\nFirmware Bytes 0x0000-0x003F:")
for a in range(0,0x40,16):
    row=[mem.get(a+i,0xFF) for i in range(16)]
    ascii_str=''.join(chr(b) if 0x20<=b<=0x7E else '.' for b in row)
    print(f"  {a:04X}: {' '.join(f'{b:02X}' for b in row)}  {ascii_str}")

# Zeige Bytes bei 0x1000 (oft Daten-Segment in FX2-Firmware)
print("\nFirmware Bytes 0x1000-0x103F:")
for a in range(0x1000,0x1040,16):
    if any(a+i in mem for i in range(16)):
        row=[mem.get(a+i,0xFF) for i in range(16)]
        ascii_str=''.join(chr(b) if 0x20<=b<=0x7E else '.' for b in row)
        print(f"  {a:04X}: {' '.join(f'{b:02X}' for b in row)}  {ascii_str}")
