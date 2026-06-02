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

print("Table at 0x0EF3 (init descriptor table, 64 bytes):")
for i in range(0, 64, 8):
    row = [rd(0x0EF3+i+j) for j in range(8)]
    print(f"  {0x0EF3+i:04X}: {' '.join(f'{b:02X}' for b in row)}")

print(f"\ncode[0x4000] = 0x{rd(0x4000):02X}")
print(f"code[0x4001] = 0x{rd(0x4001):02X}")

print("\nAll MOV DPTR,#0x40xx patterns:")
for a in sorted(mem.keys()):
    if rd(a)==0x90 and rd(a+1)==0x40:
        dptr = (0x40<<8)|rd(a+2)
        print(f"  0x{a:04X}: MOV DPTR,#0x{dptr:04X}")

print("\nCode at 0x0EF3 disasm:")
pc = 0x0EF3
for _ in range(20):
    if pc not in mem: break
    b = [rd(pc+i) for i in range(5)]
    print(f"  {pc:04X}: {' '.join(f'{x:02X}' for x in b)}")
    pc += 1
