import ctypes, ctypes.wintypes as wt, subprocess
user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

r = subprocess.run(["tasklist","/FI","IMAGENAME eq ols_32on32.exe","/FO","CSV"],capture_output=True,text=True)
pids = []
for l in r.stdout.splitlines()[1:]:
    p = l.strip('"').split('","')
    if len(p)>=2:
        try: pids.append(int(p[1]))
        except: pass
print("PIDs:", pids)

wins = []
def cb(h,l):
    p=wt.DWORD(0); user32.GetWindowThreadProcessId(h, ctypes.byref(p))
    if p.value not in pids: return True
    tb=ctypes.create_unicode_buffer(256); user32.GetWindowTextW(h,tb,256)
    r2=wt.RECT(); user32.GetWindowRect(h, ctypes.byref(r2))
    area=(r2.right-r2.left)*(r2.bottom-r2.top)
    if user32.IsWindowVisible(h) and area > 100:
        wins.append((h,tb.value,area))
    return True
user32.EnumWindows(WNDENUMPROC(cb), 0)
wins.sort(key=lambda x: x[2], reverse=True)
for h,t,a in wins[:10]:
    print(f"  0x{h:08X} area={a:8d} title={t!r}")
