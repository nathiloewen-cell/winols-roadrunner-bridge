"""
OLS3_FW.hex 8051-Simulator.
Simuliert die Cypress FX2 Firmware um die echten OLS300-Responses zu extrahieren.

FX2 Speicherkarte:
  0x0000-0x3FFF: Code/XRAM (shared)
  0xE600-0xE6FF: FX2 USB Register (SFR-mapped)
  0xF000-0xF1FF: EP2 FIFO (OUT, 512 bytes)
  0xF200-0xF3FF: EP4 FIFO
  0xF400-0xF5FF: EP6 IN FIFO (448 bytes genutzt)
  0xF600-0xF7FF: EP8 FIFO
"""
import sys

HEX = r"C:\Users\Nates\WinOLS_Bridge\OLS3_FW.hex"

# ── Parse Intel HEX ──────────────────────────────────────────────────────────
code = [0xFF] * 0x10000  # code/xram memory
with open(HEX) as f:
    for line in f:
        line = line.strip()
        if not line.startswith(':'): continue
        bc   = int(line[1:3],16)
        addr = int(line[3:7],16)
        rt   = int(line[7:9],16)
        if rt == 0x00:
            for i in range(bc):
                code[addr+i] = int(line[9+i*2:11+i*2],16)
        elif rt == 0x01:
            break

print(f"Firmware geladen: max. Adresse = 0x{max(i for i,b in enumerate(code) if b!=0xFF):04X}")

# ── 8051 State ───────────────────────────────────────────────────────────────
iram  = [0] * 256   # internal data RAM (0x00-0xFF)
sfr   = [0] * 128   # SFR (0x80-0xFF) relative index
xram  = [0] * 0x10000  # external XRAM (FX2 registers + FIFOs)
# Copy firmware to XRAM too (FX2 shares code and xram)
for i,b in enumerate(code):
    xram[i] = b

# Registers
PC = 0
A  = 0
B  = 0
DPTR = 0
PSW  = 0
SP   = 7
R    = [0]*8

def rd_iram(addr):
    if addr < 0x80: return iram[addr]
    return sfr[addr-0x80]
def wr_iram(addr, val):
    val &= 0xFF
    if addr < 0x80: iram[addr] = val
    else: sfr[addr-0x80] = val

def rd_xram(addr):
    return xram[addr & 0xFFFF]
def wr_xram(addr, val):
    xram[addr & 0xFFFF] = val & 0xFF

def rd_code(addr):
    return code[addr & 0xFFFF]

def push(val):
    global SP
    SP = (SP+1) & 0xFF
    wr_iram(SP, val & 0xFF)
def pop():
    global SP
    v = rd_iram(SP)
    SP = (SP-1) & 0xFF
    return v

# FX2 FIFO addresses
EP6_FIFO_START = 0xF400
EP2_FIFO_START = 0xF000
EP2IN_RESP_START = 0xF800  # EP2 IN buffer (512 bytes)

# Track writes to EP6 FIFO
ep6_writes = []
ep2_writes = []
ep2in_writes = []

writes_to_fifo = {}  # addr -> list of values

MAX_INSN = 500000  # safety limit

# ── Main simulation loop ──────────────────────────────────────────────────────
PC = 0
step = 0
callstack = []

print("\nSimuliere Firmware (max. 500k Instruktionen)...")

try:
    while step < MAX_INSN:
        if PC >= 0x10000: break
        op = rd_code(PC)
        step += 1

        # Track XRAM writes to interesting areas
        # (done inline below)

        # ── Basic 8051 opcodes ──────────────────────────────────────────
        if op == 0x00:  # NOP
            PC += 1

        elif op == 0x02:  # LJMP addr16
            PC = (rd_code(PC+1)<<8) | rd_code(PC+2)

        elif op == 0x12:  # LCALL addr16
            target = (rd_code(PC+1)<<8) | rd_code(PC+2)
            ret = (PC+3) & 0xFFFF
            push(ret & 0xFF)
            push((ret>>8) & 0xFF)
            callstack.append(ret)
            PC = target

        elif op == 0x22:  # RET
            hi = pop(); lo = pop()
            PC = (hi<<8)|lo
            if callstack: callstack.pop()

        elif op == 0x32:  # RETI
            hi = pop(); lo = pop()
            PC = (hi<<8)|lo

        elif op == 0x80:  # SJMP rel
            rel = rd_code(PC+1)
            if rel >= 128: rel -= 256
            PC = (PC+2+rel) & 0xFFFF

        elif op == 0x01 or op == 0x21 or op == 0x41 or op == 0x61 or op == 0x81 or op == 0xA1 or op == 0xC1 or op == 0xE1:  # AJMP/ACALL
            page = (op >> 5) << 8
            offset = rd_code(PC+1)
            if op & 0x10:  # ACALL
                ret = (PC+2)&0xFFFF
                push(ret & 0xFF); push((ret>>8)&0xFF)
                callstack.append(ret)
                PC = page | offset
            else:  # AJMP
                PC = page | offset

        elif op == 0x74:  # MOV A, #imm
            A = rd_code(PC+1); PC += 2

        elif op == 0x75:  # MOV direct, #imm
            addr = rd_code(PC+1); val = rd_code(PC+2)
            wr_iram(addr, val); PC += 3

        elif op == 0x78: A = 0; R[0] = rd_code(PC+1); PC += 2  # MOV R0,#imm (simplified)
        elif op == 0x79: R[1] = rd_code(PC+1); PC += 2
        elif op == 0x7A: R[2] = rd_code(PC+1); PC += 2
        elif op == 0x7B: R[3] = rd_code(PC+1); PC += 2
        elif op == 0x7C: R[4] = rd_code(PC+1); PC += 2
        elif op == 0x7D: R[5] = rd_code(PC+1); PC += 2
        elif op == 0x7E: R[6] = rd_code(PC+1); PC += 2
        elif op == 0x7F: R[7] = rd_code(PC+1); PC += 2

        elif op == 0x90:  # MOV DPTR, #imm16
            DPTR = (rd_code(PC+1)<<8) | rd_code(PC+2); PC += 3

        elif op == 0xA3:  # INC DPTR
            DPTR = (DPTR+1) & 0xFFFF; PC += 1

        elif op == 0xE0:  # MOVX A, @DPTR
            A = rd_xram(DPTR); PC += 1

        elif op == 0xF0:  # MOVX @DPTR, A
            wr_xram(DPTR, A)
            # Track writes to EP6 FIFO
            if EP6_FIFO_START <= DPTR <= EP6_FIFO_START+511:
                ep6_writes.append((DPTR, A))
                if len(ep6_writes) == 1:
                    print(f"  Erste EP6-Write bei 0x{DPTR:04X} = 0x{A:02X} (PC=0x{PC:04X})")
            elif EP2IN_RESP_START <= DPTR <= EP2IN_RESP_START+511:
                ep2in_writes.append((DPTR, A))
            elif 0xE600 <= DPTR <= 0xE7FF:
                pass  # FX2 SFR writes (normal)
            PC += 1

        elif op == 0xE4:  # CLR A
            A = 0; PC += 1

        elif op == 0xF4:  # CPL A
            A = (~A) & 0xFF; PC += 1

        elif op == 0xE5:  # MOV A, direct
            A = rd_iram(rd_code(PC+1)); PC += 2

        elif op == 0xF5:  # MOV direct, A
            wr_iram(rd_code(PC+1), A); PC += 2

        elif op == 0xE8: A = R[0]; PC += 1
        elif op == 0xE9: A = R[1]; PC += 1
        elif op == 0xEA: A = R[2]; PC += 1
        elif op == 0xEB: A = R[3]; PC += 1
        elif op == 0xEC: A = R[4]; PC += 1
        elif op == 0xED: A = R[5]; PC += 1
        elif op == 0xEE: A = R[6]; PC += 1
        elif op == 0xEF: A = R[7]; PC += 1

        elif op == 0xF8: R[0] = A; PC += 1
        elif op == 0xF9: R[1] = A; PC += 1
        elif op == 0xFA: R[2] = A; PC += 1
        elif op == 0xFB: R[3] = A; PC += 1
        elif op == 0xFC: R[4] = A; PC += 1
        elif op == 0xFD: R[5] = A; PC += 1
        elif op == 0xFE: R[6] = A; PC += 1
        elif op == 0xFF: R[7] = A; PC += 1

        elif op == 0x04:  # INC A
            A = (A+1) & 0xFF; PC += 1

        elif op == 0x05:  # INC direct
            addr = rd_code(PC+1)
            wr_iram(addr, (rd_iram(addr)+1) & 0xFF); PC += 2

        elif op == 0x14:  # DEC A
            A = (A-1) & 0xFF; PC += 1

        elif op == 0x24:  # ADD A, #imm
            tmp = A + rd_code(PC+1)
            PSW = (PSW & ~1) | (1 if tmp > 255 else 0)
            A = tmp & 0xFF; PC += 2

        elif op == 0x25:  # ADD A, direct
            tmp = A + rd_iram(rd_code(PC+1))
            A = tmp & 0xFF; PC += 2

        elif op == 0x44:  # ORL A, #imm
            A = A | rd_code(PC+1); PC += 2

        elif op == 0x45:  # ORL A, direct
            A = A | rd_iram(rd_code(PC+1)); PC += 2

        elif op == 0x54:  # ANL A, #imm
            A = A & rd_code(PC+1); PC += 2

        elif op == 0x64:  # XRL A, #imm
            A = A ^ rd_code(PC+1); PC += 2

        elif op == 0x60:  # JZ rel
            rel = rd_code(PC+1)
            if rel >= 128: rel -= 256
            PC = (PC+2+rel) & 0xFFFF if A == 0 else PC+2

        elif op == 0x70:  # JNZ rel
            rel = rd_code(PC+1)
            if rel >= 128: rel -= 256
            PC = (PC+2+rel) & 0xFFFF if A != 0 else PC+2

        elif op == 0x40:  # JC rel
            rel = rd_code(PC+1)
            if rel >= 128: rel -= 256
            PC = (PC+2+rel) & 0xFFFF if (PSW&1) else PC+2

        elif op == 0x50:  # JNC rel
            rel = rd_code(PC+1)
            if rel >= 128: rel -= 256
            PC = (PC+2+rel) & 0xFFFF if not (PSW&1) else PC+2

        elif op == 0xB4:  # CJNE A,#imm,rel
            imm = rd_code(PC+1); rel = rd_code(PC+2)
            if rel >= 128: rel -= 256
            PSW = (PSW&~1)|(1 if A < imm else 0)
            PC = (PC+3+rel)&0xFFFF if A != imm else PC+3

        elif op == 0xD5:  # DJNZ direct,rel
            addr = rd_code(PC+1); rel = rd_code(PC+2)
            if rel >= 128: rel -= 256
            val = (rd_iram(addr)-1) & 0xFF
            wr_iram(addr, val)
            PC = (PC+3+rel)&0xFFFF if val != 0 else PC+3

        elif op == 0xD8: # DJNZ R0,rel
            rel = rd_code(PC+1)
            if rel >= 128: rel -= 256
            R[0] = (R[0]-1)&0xFF
            PC = (PC+2+rel)&0xFFFF if R[0] != 0 else PC+2

        elif op in range(0xD8,0xE0):  # DJNZ Rn,rel
            n = op-0xD8; rel = rd_code(PC+1)
            if rel >= 128: rel -= 256
            R[n] = (R[n]-1)&0xFF
            PC = (PC+2+rel)&0xFFFF if R[n]!=0 else PC+2

        elif op == 0x85:  # MOV direct,direct
            src=rd_code(PC+1); dst=rd_code(PC+2)
            wr_iram(dst, rd_iram(src)); PC+=3

        elif op == 0xC3:  # CLR C
            PSW &= ~1; PC += 1

        elif op == 0xD3:  # SETB C
            PSW |= 1; PC += 1

        elif op == 0xC2:  # CLR bit
            # simplified: clear a bit
            PC += 2

        elif op == 0xD2:  # SETB bit
            PC += 2

        elif op == 0x30:  # JNB bit,rel
            # simplified: always taken (bit assumed 0)
            rel = rd_code(PC+2)
            if rel >= 128: rel -= 256
            PC = (PC+3+rel)&0xFFFF

        elif op == 0x20:  # JB bit,rel
            PC += 3  # simplified: never taken

        elif op == 0x93:  # MOVC A,@A+DPTR
            A = rd_code((A+DPTR)&0xFFFF); PC+=1

        elif op == 0x83:  # MOVC A,@A+PC
            A = rd_code((A+PC+1)&0xFFFF); PC+=1

        elif op == 0xE6:  # MOV A,@R0
            A = rd_iram(R[0]); PC+=1
        elif op == 0xE7:  # MOV A,@R1
            A = rd_iram(R[1]); PC+=1
        elif op == 0xF6:  # MOV @R0,A
            wr_iram(R[0],A); PC+=1
        elif op == 0xF7:  # MOV @R1,A
            wr_iram(R[1],A); PC+=1

        elif op == 0x76:  # MOV @R0,#imm
            wr_iram(R[0], rd_code(PC+1)); PC+=2
        elif op == 0x77:  # MOV @R1,#imm
            wr_iram(R[1], rd_code(PC+1)); PC+=2

        else:
            # Skip unknown opcodes (1 byte)
            PC = (PC+1) & 0xFFFF

        # Safety: break on infinite loop at address 0
        if PC == 0 and step > 100:
            print(f"  Zurück zu 0x0000 nach {step} Instruktionen")
            break

        # Stop after first 100 EP6 writes (we have the init data)
        if len(ep6_writes) >= 448:
            print(f"  448 EP6-Writes erhalten nach {step} Instruktionen")
            break

except Exception as e:
    print(f"Simulation error at PC=0x{PC:04X}: {e}")

# ── Ergebnisse ────────────────────────────────────────────────────────────────
print(f"\nSimulation beendet nach {step} Instruktionen")
print(f"EP6 FIFO writes: {len(ep6_writes)}")
print(f"EP2 IN writes:   {len(ep2in_writes)}")

if ep6_writes:
    # Reconstruct EP6 packet
    ep6_buf = [0] * 512
    for addr, val in ep6_writes:
        idx = addr - EP6_FIFO_START
        if 0 <= idx < 512:
            ep6_buf[idx] = val
    print(f"\nEP6 Paket (erste 64 Bytes):")
    for i in range(0, min(64, len(ep6_writes)+16), 16):
        row = ep6_buf[i:i+16]
        hex_str = ' '.join(f'{b:02X}' for b in row)
        asc_str = ''.join(chr(b) if 0x20<=b<0x7F else '.' for b in row)
        print(f"  {i:04X}: {hex_str}  {asc_str}")

    # Save to file
    out_path = r"C:\dev\winols-roadrunner-bridge\tools\ols300_ep6_sim.bin"
    with open(out_path, 'wb') as f:
        f.write(bytes(ep6_buf[:448]))
    print(f"\nGespeichert: {out_path}")

if ep2in_writes:
    print(f"\nEP2 IN Responses ({len(ep2in_writes)} bytes):")
    ep2_buf = [0]*512
    for addr, val in ep2in_writes:
        idx = addr - EP2IN_RESP_START
        if 0<=idx<512: ep2_buf[idx] = val
    print("  " + ' '.join(f'{b:02X}' for b in ep2_buf[:32]))
