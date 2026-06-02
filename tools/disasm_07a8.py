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
def rd(a): return mem.get(a,255)

ops = {
    0x00:("NOP",1),0x02:("LJMP",3),0x04:("INC A",1),0x05:("INC d",2),
    0x12:("LCALL",3),0x14:("DEC A",1),0x22:("RET",1),0x24:("ADD A,#",2),
    0x25:("ADD A,d",2),0x32:("RETI",1),0x44:("ORL A,#",2),0x54:("ANL A,#",2),
    0x60:("JZ",2),0x70:("JNZ",2),0x74:("MOV A,#",2),0x75:("MOV d,#",3),
    0x78:("MOV R0,#",2),0x79:("MOV R1,#",2),0x7A:("MOV R2,#",2),0x7B:("MOV R3,#",2),
    0x7C:("MOV R4,#",2),0x7D:("MOV R5,#",2),0x7E:("MOV R6,#",2),0x7F:("MOV R7,#",2),
    0x80:("SJMP",2),0x85:("MOV d,d",3),0x90:("MOV DPTR,#",3),0xA3:("INC DPTR",1),
    0xB4:("CJNE A,#,r",3),0xC2:("CLR bit",2),0xC3:("CLR C",1),0xD2:("SETB bit",2),
    0xD3:("SETB C",1),0xE0:("MOVX A,@DPTR",1),0xE4:("CLR A",1),0xE5:("MOV A,d",2),
    0xE8:("MOV A,R0",1),0xE9:("MOV A,R1",1),0xEA:("MOV A,R2",1),0xEB:("MOV A,R3",1),
    0xEC:("MOV A,R4",1),0xED:("MOV A,R5",1),0xEE:("MOV A,R6",1),0xEF:("MOV A,R7",1),
    0xF0:("MOVX @DPTR,A",1),0xF5:("MOV d,A",2),
    0xF8:("MOV R0,A",1),0xF9:("MOV R1,A",1),0xFA:("MOV R2,A",1),0xFB:("MOV R3,A",1),
    0xFC:("MOV R4,A",1),0xFD:("MOV R5,A",1),0xFE:("MOV R6,A",1),0xFF:("MOV R7,A",1),
    0x93:("MOVC A,@A+DPTR",1),0x83:("MOVC A,@A+PC",1),
    0x30:("JNB",3),0x20:("JB",3),0x10:("JBC",3),
}

def disasm(start, n=60):
    pc=start
    for _ in range(n):
        if pc not in mem: return pc
        op=rd(pc)
        mnem,sz=ops.get(op,(f"?{op:02X}",1))
        args=[rd(pc+i+1) for i in range(sz-1)]
        arg_s=""
        if sz==2: arg_s=f" 0x{args[0]:02X}"
        elif sz==3: arg_s=f" 0x{args[0]:02X},0x{args[1]:02X}"
        if op==0x90: arg_s=f" #0x{args[0]:02X}{args[1]:02X}"
        elif op==0x02: arg_s=f" 0x{args[0]:02X}{args[1]:02X}"
        elif op==0x12: arg_s=f" CALL 0x{args[0]:02X}{args[1]:02X}"
        elif op in (0x80,0x60,0x70,0x40,0x50) and args:
            rel=args[0]-256 if args[0]>=128 else args[0]
            arg_s=f" ->0x{(pc+2+rel)&0xFFFF:04X}"
        elif op in (0x20,0x30,0x10,0xB4,0xB5):
            if len(args)>=2:
                rel=args[1]-256 if args[1]>=128 else args[1]
                arg_s=f" {args[0]:02X},->0x{(pc+3+rel)&0xFFFF:04X}"
        print(f"  0x{pc:04X}: {mnem}{arg_s}")
        if op in (0x22,0x32): return pc+1
        pc+=sz
    return pc

print("=== 0x07A8 (main init) ===")
disasm(0x07A8, 30)

print("\n=== 0x07ED (EP6 Buffer Write) ===")
disasm(0x07ED, 60)

print("\n=== 0x094B (hardware config) ===")
disasm(0x094B, 40)
