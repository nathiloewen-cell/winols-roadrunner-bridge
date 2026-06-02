"""
Einfacher 8051-Simulator für OLS3_FW.hex.
Traciert den Code-Pfad für EP2 OUT Command 0x20 0x30.
"""

HEX = r"C:\Users\Nates\WinOLS_Bridge\OLS3_FW.hex"

# Parse Intel HEX
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

def rd(a): return mem.get(a & 0xFFFF, 0xFF)
def rd16(a): return (rd(a)<<8)|rd(a+1)

# Show disassembly around interesting addresses
def disasm_at(pc, n=20):
    """Very simple 8051 disassembler."""
    ops = {
        0x00: ("NOP",0),
        0x01: ("AJMP",1),    0x02: ("LJMP",2),
        0x03: ("RR A",0),    0x04: ("INC A",0),
        0x05: ("INC",1),     0x06: ("INC @R0",0),  0x07: ("INC @R1",0),
        0x08: ("INC R0",0),  0x09: ("INC R1",0),   0x0A: ("INC R2",0),
        0x0B: ("INC R3",0),  0x0C: ("INC R4",0),   0x0D: ("INC R5",0),
        0x0E: ("INC R6",0),  0x0F: ("INC R7",0),
        0x10: ("JBC",2),     0x11: ("ACALL",1),    0x12: ("LCALL",2),
        0x13: ("RRC A",0),   0x14: ("DEC A",0),
        0x15: ("DEC",1),     0x20: ("JB",2),        0x22: ("RET",0),
        0x30: ("JNB",2),     0x32: ("RETI",0),
        0x40: ("JC",1),      0x43: ("ORL",2),
        0x44: ("ORL A,#",1), 0x45: ("ORL A,",1),
        0x50: ("JNC",1),     0x52: ("ANL",2),
        0x53: ("ANL",2),     0x54: ("ANL A,#",1),
        0x60: ("JZ",1),      0x70: ("JNZ",1),
        0x74: ("MOV A,#",1), 0x75: ("MOV",2),
        0x76: ("MOV @R0,#",1),0x77: ("MOV @R1,#",1),
        0x78: ("MOV R0,#",1),0x79: ("MOV R1,#",1),
        0x7A: ("MOV R2,#",1),0x7B: ("MOV R3,#",1),
        0x7C: ("MOV R4,#",1),0x7D: ("MOV R5,#",1),
        0x7E: ("MOV R6,#",1),0x7F: ("MOV R7,#",1),
        0x80: ("SJMP",1),
        0x85: ("MOV",2),     0x90: ("MOV DPTR,#",2),
        0xA0: ("ORL C,/",1), 0xA3: ("INC DPTR",0),
        0xB4: ("CJNE A,#",2),0xB5: ("CJNE A,",2),
        0xC2: ("CLR",1),     0xC3: ("CLR C",0),
        0xD2: ("SETB",1),    0xD3: ("SETB C",0),
        0xE0: ("MOVX A,@DPTR",0), 0xE4: ("CLR A",0),
        0xE5: ("MOV A,",1),  0xE6: ("MOV A,@R0",0),0xE7: ("MOV A,@R1",0),
        0xE8: ("MOV A,R0",0),0xE9: ("MOV A,R1",0), 0xEA: ("MOV A,R2",0),
        0xEB: ("MOV A,R3",0),0xEC: ("MOV A,R4",0), 0xED: ("MOV A,R5",0),
        0xEE: ("MOV A,R6",0),0xEF: ("MOV A,R7",0),
        0xF0: ("MOVX @DPTR,A",0),0xF5: ("MOV",1),
        0xF6: ("MOV @R0,A",0),0xF7: ("MOV @R1,A",0),
        0xF8: ("MOV R0,A",0),0xF9: ("MOV R1,A",0), 0xFA: ("MOV R2,A",0),
        0xFB: ("MOV R3,A",0),0xFC: ("MOV R4,A",0), 0xFD: ("MOV R5,A",0),
        0xFE: ("MOV R6,A",0),0xFF: ("MOV R7,A",0),
    }
    result = []
    for _ in range(n):
        if pc not in mem: break
        op = rd(pc)
        mnem, extra = ops.get(op, (f"?{op:02X}",0))
        args = [rd(pc+i+1) for i in range(extra)]
        # Format args
        if extra == 0:
            arg_str = ""
        elif extra == 1:
            arg_str = f" #0x{args[0]:02X}" if '#' in mnem else f" 0x{args[0]:02X}"
        else:
            arg_str = f" 0x{args[0]:02X},0x{args[1]:02X}"

        # Calculate branch targets
        if op in [0x80,0x40,0x50,0x60,0x70]:  # relative jumps
            offset = args[0] if args[0] < 128 else args[0]-256
            target = pc + 2 + offset
            arg_str = f" -> 0x{target:04X}"
        elif op in [0x20,0x30,0x10]:  # bit jumps
            if len(args)>=2:
                offset = args[1] if args[1] < 128 else args[1]-256
                target = pc + 3 + offset
                arg_str = f" bit=0x{args[0]:02X} -> 0x{target:04X}"
        elif op == 0x02:  # LJMP
            if len(args)>=2:
                arg_str = f" -> 0x{args[0]:02X}{args[1]:02X}"
        elif op == 0x12:  # LCALL
            if len(args)>=2:
                arg_str = f" -> 0x{args[0]:02X}{args[1]:02X}"

        bytes_str = ' '.join(f'{rd(pc+i):02X}' for i in range(extra+1))
        result.append(f"  0x{pc:04X}: {bytes_str:<10} {mnem}{arg_str}")
        pc += extra + 1
    return result

# Show code starting at reset target 0x0761
print("=== Code at 0x0761 (Reset target) ===")
for line in disasm_at(0x0761, 30): print(line)

# Look for command dispatch - search for CMP/CJNE with 0x20
print("\n=== Suche nach Befehl-Handler fuer 0x20 ===")
for a in sorted(mem.keys()):
    # CJNE A,#data,rel  = 0xB4
    if rd(a) == 0xB4 and rd(a+1) == 0x20:
        print(f"CJNE A,#0x20 bei 0x{a:04X}:")
        for line in disasm_at(max(0,a-5), 15): print(line)
        print()
    # MOV A,direct then compare pattern
    if rd(a) == 0x20 and a > 0x0100:  # JB instruction sometimes
        pass

# Look for where 8 bytes are written to EP2 response buffer
print("\n=== MOVX @DPTR,A Schreibvorgaenge (EP2 Response) ===")
count = 0
for a in sorted(mem.keys()):
    if rd(a) == 0xF0:  # MOVX @DPTR,A
        ctx = [rd(a+i) for i in range(-5,5)]
        # Check if DPTR was set to something interesting before
        print(f"  MOVX @DPTR,A at 0x{a:04X}")
        count += 1
        if count > 30:
            print("  ... (too many, stopping)")
            break
