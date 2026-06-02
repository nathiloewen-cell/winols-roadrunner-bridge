"""
Tiefe Analyse der OLS3_FW.hex Firmware.
Sucht nach EP6-relevanten FX2-Register-Schreibvorgängen.
"""
HEX = r"C:\Users\Nates\WinOLS_Bridge\OLS3_FW.hex"
mem = {}
with open(HEX) as f:
    for line in f:
        line = line.strip()
        if not line.startswith(":"): continue
        bc=int(line[1:3],16); addr=int(line[3:7],16); rt=int(line[7:9],16)
        if rt==0:
            for i in range(bc): mem[addr+i]=int(line[9+i*2:11+i*2],16)
        elif rt==1: break
def rd(a): return mem.get(a,255)

# Zeige alle MOVX @DPTR,A Instruktionen mit 15-Byte Kontext
print("=== Alle MOVX @DPTR,A mit Kontext (0xF0 Opcodes) ===")
movx_addrs = [a for a in sorted(mem.keys()) if mem.get(a)==0xF0]
print(f"Gesamt MOVX @DPTR,A: {len(movx_addrs)}")
for a in movx_addrs[:30]:
    ctx_before = [rd(a-i) for i in range(15,0,-1)]
    ctx_after  = [rd(a+i) for i in range(0,5)]
    print(f"  @0x{a:04X}: ...{' '.join(f'{b:02X}' for b in ctx_before)} [F0] {' '.join(f'{b:02X}' for b in ctx_after[1:])}")

# Suche nach Byte-Folgen die DPTR auf EP6-Bereich setzen:
# 90 F4 xx = MOV DPTR, #0xF4xx (EP6 FIFO area)
print("\n=== Suche nach MOV DPTR,#0xF4xx (EP6 FIFO) ===")
for a in sorted(mem.keys()):
    if rd(a)==0x90 and rd(a+1)==0xF4:
        print(f"  0x{a:04X}: MOV DPTR,#0x{rd(a+1):02X}{rd(a+2):02X}")

# Suche nach MOV DPTR,#0xE6xx (FX2 USB SFR)
print("\n=== Suche nach MOV DPTR,#0xE6xx (FX2 USB SFR) ===")
for a in sorted(mem.keys()):
    if rd(a)==0x90 and rd(a+1)==0xE6:
        print(f"  0x{a:04X}: MOV DPTR,#0xE6{rd(a+2):02X}")

# Zeige Firmware bei 0x094B (aus Summary erwähnt)
print("\n=== Code bei 0x094B ===")
pc = 0x094B
for _ in range(30):
    if pc not in mem: break
    b = [rd(pc+i) for i in range(5)]
    print(f"  0x{pc:04X}: {' '.join(f'{x:02X}' for x in b)}")
    if b[0]==0x02: pc=(b[1]<<8)|b[2]
    elif b[0] in (0x32,0x22,0x80): break
    else: pc+=1

# Zeige Firmware bei 0x0A67 (aus Main-Loop nach Reset)
print("\n=== Code bei 0x0A67 ===")
pc = 0x0A67
for _ in range(30):
    if pc not in mem: break
    b = [rd(pc+i) for i in range(5)]
    print(f"  0x{pc:04X}: {' '.join(f'{x:02X}' for x in b)}")
    if b[0]==0x02: pc=(b[1]<<8)|b[2]
    elif b[0] in (0x32,0x22,0x80): break
    else: pc+=1
