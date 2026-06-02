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

print("=== MOVX @DPTR,A writes to FX2 register/FIFO area (>= 0xE000) ===")
for a in sorted(mem.keys()):
    if mem.get(a) != 0xF0: continue
    for back in range(1,30):
        ba = a-back
        if mem.get(ba) == 0x90:
            dptr = (rd(ba+1)<<8)|rd(ba+2)
            if dptr >= 0xE000:
                aval = "?"
                for ab in range(1,15):
                    if mem.get(a-ab)==0x74:
                        aval = hex(rd(a-ab+1)); break
                    elif mem.get(a-ab)==0xE4:
                        aval = "0x00"; break
                    elif mem.get(a-ab)==0xE5:
                        aval = f"iram[0x{rd(a-ab+1):02X}]"; break
                area = ""
                if 0xF400<=dptr<=0xF5FF: area=" *** EP6 FIFO ***"
                elif 0xF000<=dptr<=0xF1FF: area=" EP2 FIFO"
                elif 0xF800<=dptr<=0xF9FF: area=" EP2IN buf"
                elif 0xE600<=dptr<=0xE7FF: area=" FX2 SFR"
                print(f"  0x{a:04X}: MOVX @0x{dptr:04X},A  A={aval}{area}")
            break

print("\n=== Zeige Code bei 0x0F64 (USB ISR) ===")
pc = 0x0F64
for _ in range(40):
    if pc not in mem: break
    b = [rd(pc+i) for i in range(4)]
    print(f"  0x{pc:04X}: {' '.join(f'{x:02X}' for x in b)}")
    if b[0]==0x02: pc=(b[1]<<8)|b[2]
    elif b[0]==0x32 or b[0]==0x22: break
    else: pc+=1
