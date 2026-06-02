import ctypes, ctypes.wintypes as wt, subprocess, struct

k32 = ctypes.windll.kernel32

r = subprocess.run(["tasklist","/FI","IMAGENAME eq ols_32on32.exe","/FO","CSV"],
                   capture_output=True, text=True)
pids = []
for l in r.stdout.splitlines()[1:]:
    p = l.strip('"').split('","')
    if len(p) >= 2:
        try: pids.append(int(p[1]))
        except: pass

if not pids: print("No WinOLS"); exit()
vpid = sorted(pids, reverse=True)[0]
print("PID:", vpid)

h = k32.OpenProcess(0x001F0FFF, False, vpid)
OBJ = 0x00A7A640

def rb(addr):
    buf = ctypes.create_string_buffer(1); rd = ctypes.c_size_t(0)
    return buf.raw[0] if k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, 1, ctypes.byref(rd)) else None

def rd(addr):
    buf = ctypes.create_string_buffer(4); rdd = ctypes.c_size_t(0)
    return struct.unpack('<I', buf.raw)[0] if k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, 4, ctypes.byref(rdd)) else None

f8   = rb(OBJ + 8)
f71  = rb(OBJ + 0x71)
f897 = rd(OBJ + 0x897)
print(f"obj[8]     = {f8}")
print(f"obj[0x71]  = 0x{f71:02X}" if f71 is not None else "obj[0x71]  = None")
print(f"obj[0x897] = 0x{f897:08X}" if f897 else "obj[0x897] = 0x00000000 (FAIL)")

if f897 and f897 > 0x10000:
    f594 = rd(f897 + 0x594)
    print(f"sub1[0x594]= 0x{f594:08X}" if f594 else "sub1[0x594]= 0 (FAIL)")
    if f594 and f594 > 0x10000:
        f4b = rd(f594 + 4)
        print(f"sub2[4]    = 0x{f4b:08X}" if f4b else "sub2[4]    = 0 (FAIL)")
        if f4b and f4b > 0x10000:
            f4c = rd(f4b + 4)
            print(f"sub3[4]    = 0x{f4c:08X}" if f4c else "sub3[4]    = 0 (FAIL)")
            if f4c and f4c > 0x10000:
                b36 = rb(f4c + 0x36)
                print(f"sub4[0x36] = {b36}" + (" OK" if b36 else " (FAIL)"))

k32.CloseHandle(h)
