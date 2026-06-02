"""
Traciert die EP6-Buffer-Initialisierung bei 0x07ED.
Die FX2-Firmware schreibt den 448-Byte-Identifikations-Packet nach 0x7C00.
"""
HEX = r"C:\Users\Nates\WinOLS_Bridge\OLS3_FW.hex"
code = [0xFF]*0x10000
with open(HEX) as f:
    for line in f:
        line=line.strip()
        if not line.startswith(':'): continue
        bc=int(line[1:3],16); addr=int(line[3:7],16); rt=int(line[7:9],16)
        if rt==0:
            for i in range(bc): code[addr+i]=int(line[9+i*2:11+i*2],16)
        elif rt==1: break
def rd(a): return code[a&0xFFFF]

# Vollständige Simulation der Init-Routine für EP6 Buffer
# Startet bei 0x07ED, traciert alle Writes zu 0x7Cxx

# 8051 Mini-Simulator für diesen Abschnitt
iram = [0]*256
xram = [0]*0x10000
# Kopiere Firmware nach xram (FX2 teilt Code/XRAM)
for i,b in enumerate(code): xram[i]=b

A=0; B=0; DPTR=0; PSW=0; SP=0x07
R=[0]*8

def wr_x(addr,v):
    xram[addr&0xFFFF] = v&0xFF
    if 0x7C00 <= addr <= 0x7CFF:
        print(f"    EP6[{addr-0x7C00:3d}] = 0x{v:02X}  ({chr(v) if 0x20<=v<0x7F else '.'})")

def rd_i(a):
    if a<0x80: return iram[a]
    return 0  # SFR simplified
def wr_i(a,v):
    if a<0x80: iram[a]=v&0xFF

PC = 0x07A8  # Start of main init (from reset trace)
steps = 0
ep6_buf = {}

print("=== Simuliere ab 0x07A8 (Haupt-Init) ===\n")
print("EP6 Buffer Writes (0x7C00 = EP6 Start):")

try:
    while steps < 200000:
        op = rd(PC)
        steps += 1

        if op == 0x00: PC+=1  # NOP
        elif op == 0x02:  # LJMP
            PC=(rd(PC+1)<<8)|rd(PC+2)
        elif op == 0x12:  # LCALL
            t=(rd(PC+1)<<8)|rd(PC+2)
            ret=PC+3
            SP=(SP+1)&0xFF; iram[SP]=ret&0xFF
            SP=(SP+1)&0xFF; iram[SP]=(ret>>8)&0xFF
            PC=t
        elif op == 0x22:  # RET
            hi=iram[SP]; SP=(SP-1)&0xFF
            lo=iram[SP]; SP=(SP-1)&0xFF
            PC=(hi<<8)|lo
        elif op == 0x32: PC+=1  # RETI simplified
        elif op == 0x80:  # SJMP
            rel=rd(PC+1); rel=rel-256 if rel>=128 else rel
            PC=(PC+2+rel)&0xFFFF
        elif op == 0x74:  # MOV A,#
            A=rd(PC+1); PC+=2
        elif op == 0x75:  # MOV direct,#
            wr_i(rd(PC+1),rd(PC+2)); PC+=3
        elif op == 0x78: R[0]=rd(PC+1); PC+=2
        elif op == 0x79: R[1]=rd(PC+1); PC+=2
        elif op == 0x7A: R[2]=rd(PC+1); PC+=2
        elif op == 0x7B: R[3]=rd(PC+1); PC+=2
        elif op == 0x7C: R[4]=rd(PC+1); PC+=2
        elif op == 0x7D: R[5]=rd(PC+1); PC+=2
        elif op == 0x7E: R[6]=rd(PC+1); PC+=2
        elif op == 0x7F: R[7]=rd(PC+1); PC+=2
        elif op == 0x90: DPTR=(rd(PC+1)<<8)|rd(PC+2); PC+=3
        elif op == 0xA3: DPTR=(DPTR+1)&0xFFFF; PC+=1
        elif op == 0xE0: A=xram[DPTR]; PC+=1
        elif op == 0xF0:
            wr_x(DPTR, A)
            if 0x7C00<=DPTR<=0x7CFF:
                ep6_buf[DPTR-0x7C00] = A
            PC+=1
        elif op == 0xE4: A=0; PC+=1
        elif op == 0xF4: A=(~A)&0xFF; PC+=1
        elif op == 0xE5: A=rd_i(rd(PC+1)); PC+=2
        elif op == 0xF5: wr_i(rd(PC+1),A); PC+=2
        elif op in range(0xE8,0xF0): A=R[op-0xE8]; PC+=1
        elif op in range(0xF8,0x100): R[op-0xF8]=A; PC+=1
        elif op == 0x04: A=(A+1)&0xFF; PC+=1
        elif op == 0x14: A=(A-1)&0xFF; PC+=1
        elif op == 0x24:
            tmp=A+rd(PC+1); PSW=(PSW&~1)|(1 if tmp>255 else 0)
            A=tmp&0xFF; PC+=2
        elif op == 0x25:
            tmp=A+rd_i(rd(PC+1)); A=tmp&0xFF; PC+=2
        elif op == 0x44: A|=rd(PC+1); PC+=2
        elif op == 0x54: A&=rd(PC+1); PC+=2
        elif op == 0x64: A^=rd(PC+1); PC+=2
        elif op == 0x60:
            rel=rd(PC+1); rel=rel-256 if rel>=128 else rel
            PC=(PC+2+rel)&0xFFFF if A==0 else PC+2
        elif op == 0x70:
            rel=rd(PC+1); rel=rel-256 if rel>=128 else rel
            PC=(PC+2+rel)&0xFFFF if A!=0 else PC+2
        elif op == 0x40:
            rel=rd(PC+1); rel=rel-256 if rel>=128 else rel
            PC=(PC+2+rel)&0xFFFF if (PSW&1) else PC+2
        elif op == 0x50:
            rel=rd(PC+1); rel=rel-256 if rel>=128 else rel
            PC=(PC+2+rel)&0xFFFF if not(PSW&1) else PC+2
        elif op == 0xB4:
            imm=rd(PC+1); rel=rd(PC+2)
            rel=rel-256 if rel>=128 else rel
            PSW=(PSW&~1)|(1 if A<imm else 0)
            PC=(PC+3+rel)&0xFFFF if A!=imm else PC+3
        elif op in range(0xD8,0xE0):
            n=op-0xD8; rel=rd(PC+1); rel=rel-256 if rel>=128 else rel
            R[n]=(R[n]-1)&0xFF
            PC=(PC+2+rel)&0xFFFF if R[n]!=0 else PC+2
        elif op == 0x85:
            wr_i(rd(PC+2),rd_i(rd(PC+1))); PC+=3
        elif op == 0xC3: PSW&=~1; PC+=1
        elif op == 0xD3: PSW|=1; PC+=1
        elif op in (0xC2,0xD2): PC+=2  # CLR/SETB bit (simplified)
        elif op in (0x20,0x30,0x10): PC+=3  # JB/JNB/JBC (simplified: not taken)
        elif op == 0x93:  # MOVC A,@A+DPTR
            A=rd((A+DPTR)&0xFFFF); PC+=1
        elif op == 0x83:  # MOVC A,@A+PC
            A=rd((A+PC+1)&0xFFFF); PC+=1
        elif op == 0xE6: A=rd_i(R[0]); PC+=1
        elif op == 0xE7: A=rd_i(R[1]); PC+=1
        elif op == 0xF6: wr_i(R[0],A); PC+=1
        elif op == 0xF7: wr_i(R[1],A); PC+=1
        elif op == 0x76: wr_i(R[0],rd(PC+1)); PC+=2
        elif op == 0x77: wr_i(R[1],rd(PC+1)); PC+=2
        elif op == 0x05:
            addr=rd(PC+1)
            wr_i(addr,(rd_i(addr)+1)&0xFF); PC+=2
        else:
            PC=(PC+1)&0xFFFF

        if len(ep6_buf) >= 16 and PC < 0x07A8:
            print(f"\n  (Schleife zurück vor Init, {len(ep6_buf)} Bytes gesammelt)")
            break

except Exception as e:
    print(f"Fehler bei PC=0x{PC:04X}: {e}")

print(f"\n=== EP6 Buffer Inhalt ({len(ep6_buf)} Bytes) ===")
if ep6_buf:
    buf = [ep6_buf.get(i,0) for i in range(448)]
    for i in range(0, min(64,len(ep6_buf)), 16):
        row = buf[i:i+16]
        print(f"  {i:04X}: {' '.join(f'{b:02X}' for b in row)}")
    # Save
    out = r"C:\dev\winols-roadrunner-bridge\tools\ols300_ep6_real.bin"
    with open(out,'wb') as f: f.write(bytes(buf))
    print(f"\nGespeichert: {out}")
else:
    print("  Keine Writes gefunden")
