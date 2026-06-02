HEX = r"C:\Users\Nates\WinOLS_Bridge\OLS3_FW.hex"
mem={}
with open(HEX) as f:
    for line in f:
        line=line.strip()
        if not line.startswith(":"): continue
        bc=int(line[1:3],16); addr=int(line[3:7],16); rt=int(line[7:9],16)
        if rt==0:
            for i in range(bc): mem[addr+i]=int(line[9+i*2:11+i*2],16)
        elif rt==1: break
def rd(a): return mem.get(a,0xFF)

# Quick 8051 simulation for specific paths
# Simulate from 0x07ED to get the EP6 buffer content
iram = bytearray(256)
xram = bytearray(0x10000)  # starts at 0x00

# FX2 XRAM: copy firmware to low addresses
for a in range(min(0x1010, 0x10000)):
    xram[a] = rd(a)

A=0; DPTR=0; R=[0]*8; PSW=0; SP=7

def rd_i(a):
    return iram[a] if a < 128 else 0
def wr_i(a, v):
    if a < 128: iram[a] = v & 0xFF

ep6_buf = bytearray(448)  # result

def run_at(start, max_steps=5000, stop_at=None):
    global A, DPTR, R, PSW, SP
    pc = start
    for step in range(max_steps):
        if pc not in mem: return pc
        if stop_at and pc == stop_at: return pc
        op = rd(pc)
        if   op==0x00: pc+=1
        elif op==0x02: pc=(rd(pc+1)<<8)|rd(pc+2)
        elif op==0x12:
            t=(rd(pc+1)<<8)|rd(pc+2); ret=pc+3
            SP=(SP+1)&0xFF; iram[SP]=ret&0xFF
            SP=(SP+1)&0xFF; iram[SP]=(ret>>8)&0xFF
            pc=t
        elif op==0x22:
            hi=iram[SP]; SP=(SP-1)&0xFF
            lo=iram[SP]; SP=(SP-1)&0xFF
            pc=(hi<<8)|lo
        elif op==0x32: pc+=1
        elif op==0x80:
            rel=rd(pc+1); rel=rel-256 if rel>=128 else rel
            pc=(pc+2+rel)&0xFFFF
        elif op==0x74: A=rd(pc+1); pc+=2
        elif op==0x75: wr_i(rd(pc+1),rd(pc+2)); pc+=3
        elif op in range(0x78,0x80): R[op-0x78]=rd(pc+1); pc+=2
        elif op==0x90: DPTR=(rd(pc+1)<<8)|rd(pc+2); pc+=3
        elif op==0xA3: DPTR=(DPTR+1)&0xFFFF; pc+=1
        elif op==0xE0: A=xram[DPTR]; pc+=1
        elif op==0xF0:
            xram[DPTR]=A
            if 0x7C00<=DPTR<=0x7C1F:
                ep6_buf[DPTR-0x7C00]=A
            pc+=1
        elif op==0xE4: A=0; pc+=1
        elif op==0xF4: A=(~A)&0xFF; pc+=1
        elif op==0xE5: A=rd_i(rd(pc+1)); pc+=2
        elif op==0xF5: wr_i(rd(pc+1),A); pc+=2
        elif op in range(0xE8,0xF0): A=R[op-0xE8]; pc+=1
        elif op in range(0xF8,0x100): R[op-0xF8]=A; pc+=1
        elif op==0x04: A=(A+1)&0xFF; pc+=1
        elif op==0x14: A=(A-1)&0xFF; pc+=1
        elif op==0x24: tmp=A+rd(pc+1); PSW=(PSW&~1)|(1 if tmp>255 else 0); A=tmp&0xFF; pc+=2
        elif op==0x25: tmp=A+rd_i(rd(pc+1)); A=tmp&0xFF; pc+=2
        elif op==0x34: tmp=A+rd(pc+1)+(PSW&1); PSW=(PSW&~1)|(1 if tmp>255 else 0); A=tmp&0xFF; pc+=2
        elif op==0x44: A|=rd(pc+1); pc+=2
        elif op==0x54: A&=rd(pc+1); pc+=2
        elif op==0x64: A^=rd(pc+1); pc+=2
        elif op==0x45: A|=rd_i(rd(pc+1)); pc+=2
        elif op==0x55: A&=rd_i(rd(pc+1)); pc+=2
        elif op==0x65: A^=rd_i(rd(pc+1)); pc+=2
        elif op==0x60:
            rel=rd(pc+1); rel=rel-256 if rel>=128 else rel
            pc=(pc+2+rel)&0xFFFF if A==0 else pc+2
        elif op==0x70:
            rel=rd(pc+1); rel=rel-256 if rel>=128 else rel
            pc=(pc+2+rel)&0xFFFF if A!=0 else pc+2
        elif op==0x40:
            rel=rd(pc+1); rel=rel-256 if rel>=128 else rel
            pc=(pc+2+rel)&0xFFFF if (PSW&1) else pc+2
        elif op==0x50:
            rel=rd(pc+1); rel=rel-256 if rel>=128 else rel
            pc=(pc+2+rel)&0xFFFF if not(PSW&1) else pc+2
        elif op==0xB4:
            imm=rd(pc+1); rel=rd(pc+2); rel=rel-256 if rel>=128 else rel
            PSW=(PSW&~1)|(1 if A<imm else 0)
            pc=(pc+3+rel)&0xFFFF if A!=imm else pc+3
        elif op in range(0xD8,0xE0):
            n=op-0xD8; rel=rd(pc+1); rel=rel-256 if rel>=128 else rel
            R[n]=(R[n]-1)&0xFF
            pc=(pc+2+rel)&0xFFFF if R[n]!=0 else pc+2
        elif op==0x85: wr_i(rd(pc+2),rd_i(rd(pc+1))); pc+=3
        elif op==0xC3: PSW&=~1; pc+=1
        elif op==0xD3: PSW|=1; pc+=1
        elif op in (0xC2,0xD2): pc+=2
        elif op in (0x20,0x30,0x10): pc+=3
        elif op==0x93: A=rd((A+DPTR)&0xFFFF); pc+=1
        elif op==0x83: A=rd((A+PC+1)&0xFFFF); pc+=1
        elif op==0xE6: A=rd_i(R[0]); pc+=1
        elif op==0xE7: A=rd_i(R[1]); pc+=1
        elif op==0xF6: wr_i(R[0],A); pc+=1
        elif op==0xF7: wr_i(R[1],A); pc+=1
        elif op==0x76: wr_i(R[0],rd(pc+1)); pc+=2
        elif op==0x77: wr_i(R[1],rd(pc+1)); pc+=2
        elif op==0x05: a2=rd(pc+1); wr_i(a2,(rd_i(a2)+1)&0xFF); pc+=2
        elif op==0x15: a2=rd(pc+1); wr_i(a2,(rd_i(a2)-1)&0xFF); pc+=2
        elif op==0xA0: pc+=2  # ORL C,/bit
        elif op==0xB0: pc+=2  # ANL C,/bit
        elif op==0xC4: tmp=A; A=((A<<4)|(A>>4))&0xFF; pc+=1  # SWAP A
        elif op==0xC0: SP=(SP+1)&0xFF; iram[SP]=rd_i(rd(pc+1)); pc+=2  # PUSH
        elif op==0xD0: wr_i(rd(pc+1),iram[SP]); SP=(SP-1)&0xFF; pc+=2  # POP
        elif op==0x03: A=((A>>1)|(A<<7))&0xFF; pc+=1  # RR A
        elif op==0x13: c=PSW&1; PSW=(PSW&~1)|(A&1); A=(A>>1)|(c<<7); pc+=1  # RRC A
        elif op==0x23: PSW=(PSW&~1)|(A>>7); A=((A<<1)|(A>>7))&0xFF; pc+=1  # RL A
        elif op==0x33: c=PSW&1; PSW=(PSW&~1)|(A>>7); A=((A<<1)|c)&0xFF; pc+=1  # RLC A
        elif op==0xD4: # DA A
            if (A&0xF)>9 or (PSW&64): A=(A+6)&0xFF
            if (A>>4)>9 or (PSW&1): A=(A+0x60)&0xFF; PSW|=1
            pc+=1
        elif op==0x84: pc+=1  # DIV (simplified)
        else: pc=(pc+1)&0xFFFF
    return pc

print("Running EP6 init (starting at 0x07ED)...")
R[7]=0x22  # as in firmware before LCALL 0x0FE1
final_pc = run_at(0x07ED, max_steps=50000)
print(f"Stopped at PC=0x{final_pc:04X}")

print("\nEP6 Buffer (0x7C00-0x7C0F):")
for i in range(0,32,8):
    row = ep6_buf[i:i+8]
    print(f"  byte[{i:2d}-{i+7:2d}]: {' '.join(f'{b:02X}' for b in row)}")

# Show relevant xram values
print(f"\nxram[0x4000] = 0x{xram[0x4000]:02X}")
print(f"xram[0x0023] = 0x{xram[0x0023]:02X}")
print(f"xram[0x0024] = 0x{xram[0x0024]:02X}")
print(f"xram[0x0025] = 0x{xram[0x0025]:02X}")
print(f"xram[0x0026] = 0x{xram[0x0026]:02X}")

# Save result
out = r"C:\dev\winols-roadrunner-bridge\tools\ols300_ep6_computed.bin"
with open(out,'wb') as f: f.write(bytes(ep6_buf))
print(f"\nSaved to: {out}")
print("First 32 bytes:", ' '.join(f'{b:02X}' for b in ep6_buf[:32]))
