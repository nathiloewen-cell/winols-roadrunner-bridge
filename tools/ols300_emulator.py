"""
OLS300 Emulator: Simuliert den Cypress FX2 mit OLS3_FW.hex
Extrahiert die korrekten EP6 und EP2 IN Responses für den Proxy.

Architektur:
- FX2 hat 0x7C00 XRAM als EP-Buffer
- EP6 IN Buffer liegt bei 0x7C00+ (konfigurierbar)
- Die Firmware schreibt in der Initialisierung zum EP6-Buffer
"""
import sys

HEX = r"C:\Users\Nates\WinOLS_Bridge\OLS3_FW.hex"

# Firmware laden
code = [0xFF]*0x10000
with open(HEX) as f:
    for line in f:
        line=line.strip()
        if not line.startswith(':'): continue
        bc=int(line[1:3],16); addr=int(line[3:7],16); rt=int(line[7:9],16)
        if rt==0:
            for i in range(bc): code[addr+i]=int(line[9+i*2:11+i*2],16)
        elif rt==1: break

print(f"Firmware: {sum(1 for b in code if b!=0xFF)} bytes")

# Analysiere was bei 0x7Cxx..0x7Fxx geschrieben wird (FX2 EP Buffers)
# Suche Sequenzen: MOV DPTR,#0x7Cxx..0x7Fxx dann MOVX @DPTR,A
print("\n=== Writes zu 0x7C00-0x7FFF (FX2 EP Buffer Area) ===")
writes_7c = []
for a in range(0, 0x1000):
    if code[a]!=0x90: continue
    dptr_hi = code[a+1]; dptr_lo = code[a+2]
    dptr = (dptr_hi<<8)|dptr_lo
    if 0x7C00 <= dptr <= 0x7FFF:
        # Look for MOVX @DPTR,A within next 20 bytes
        for off in range(3,20):
            if code[a+off]==0xF0:  # MOVX @DPTR,A
                # Find the A value
                a_val = "?"
                for back in range(1, off):
                    op = code[a+off-back]
                    if op==0x74:   # MOV A,#imm
                        a_val=f"0x{code[a+off-back+1]:02X}"
                        break
                    elif op==0xE4:  # CLR A
                        a_val="0x00"; break
                    elif op==0xE5:  # MOV A,direct
                        a_val=f"iram[0x{code[a+off-back+1]:02X}]"; break
                    elif op in range(0xE8,0xF0):  # MOV A,Rn
                        a_val=f"R{op-0xE8}"; break
                writes_7c.append((a, dptr, a_val))
                print(f"  0x{a:04X}: MOV DPTR,#0x{dptr:04X} then MOVX (A={a_val})")
                break

# Besonders interessant: sequentielle Writes (Fill-Pattern für ID-Paket)
print("\n=== Suche sequentielle EP-Buffer Fills ===")
# Look for patterns: MOV DPTR,# + MOVX F0 + A3 + F0 + A3 ... (sequential fill)
for a in range(0, 0x1000-10):
    if code[a]!=0x90: continue
    dptr_hi=code[a+1]; dptr_lo=code[a+2]
    dptr=(dptr_hi<<8)|dptr_lo
    if not (0x7C00<=dptr<=0x7FFF): continue
    # Count consecutive A3 F0 (INC DPTR, MOVX) after initial F0
    # Pattern: 90 hi lo [optional setup] F0 A3 F0 A3 F0 ...
    count=0; pos=a+3
    while pos < a+100:
        if code[pos]==0xF0 and code[pos+1]==0xA3:
            count+=1; pos+=2
        elif code[pos]==0xA3 and code[pos+1]==0xF0:
            count+=1; pos+=2
        elif code[pos]==0xF0 and count>0:
            count+=1; pos+=1; break
        else:
            break
    if count >= 3:
        print(f"  0x{a:04X}: Sequential fill at 0x{dptr:04X}, {count} writes")
        print(f"    Bytes: {' '.join(f'{code[a+i]:02X}' for i in range(min(20,count*2+5)))}")

# Versuche den OLS300 EP6 Response anhand der FX2-Firmware zu rekonstruieren
# Schaue bei 0x094B was dort läuft
print("\n=== Vollständige Disassembly 0x094B bis 0x09FF ===")
def disasm_line(pc):
    op=code[pc]
    b1=code[pc+1]; b2=code[pc+2]
    ops = {
        0x00:("NOP",1), 0x02:("LJMP",3), 0x04:("INC A",1),
        0x05:("INC",2), 0x12:("LCALL",3), 0x14:("DEC A",1),
        0x22:("RET",1), 0x24:("ADD A,#",2), 0x25:("ADD A,",2),
        0x32:("RETI",1), 0x40:("JC",2), 0x44:("ORL A,#",2),
        0x50:("JNC",2), 0x54:("ANL A,#",2), 0x60:("JZ",2),
        0x70:("JNZ",2), 0x74:("MOV A,#",2), 0x75:("MOV",3),
        0x80:("SJMP",2), 0x85:("MOV",3), 0x90:("MOV DPTR,#",3),
        0xA3:("INC DPTR",1), 0xB4:("CJNE A,#",3), 0xC2:("CLR bit",2),
        0xC3:("CLR C",1), 0xD2:("SETB bit",2), 0xD3:("SETB C",1),
        0xE0:("MOVX A,@DPTR",1), 0xE4:("CLR A",1), 0xE5:("MOV A,",2),
        0xEE:("MOV A,R6",1), 0xEF:("MOV A,R7",1), 0xF0:("MOVX @DPTR,A",1),
        0xF5:("MOV",2), 0xFE:("MOV R6,A",1), 0xFF:("MOV R7,A",1),
    }
    mnem,sz = ops.get(op,(f"DB 0x{op:02X}",1))
    if sz==1: args=""
    elif sz==2: args=f" 0x{b1:02X}"
    else: args=f" 0x{b1:02X},0x{b2:02X}"
    if op==0x02: args=f" 0x{b1:02X}{b2:02X}"
    elif op==0x90: args=f" #0x{b1:02X}{b2:02X}"
    elif op in(0x80,0x40,0x50,0x60,0x70):
        rel=b1 if b1<128 else b1-256
        args=f" ->0x{(pc+2+rel)&0xFFFF:04X}"
    return f"  {pc:04X}: {mnem}{args}", sz

pc=0x094B
for _ in range(60):
    if pc<0 or pc>=0x10000 or code[pc]==0xFF: break
    line,sz=disasm_line(pc)
    print(line)
    if code[pc] in (0x22,0x32,0x80): break
    pc+=sz
