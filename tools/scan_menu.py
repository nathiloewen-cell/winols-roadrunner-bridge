import ctypes, ctypes.wintypes as wt, subprocess
user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

r = subprocess.run(["tasklist","/FI","IMAGENAME eq ols_32on32.exe","/FO","CSV"], capture_output=True, text=True)
pids = []
for line in r.stdout.splitlines()[1:]:
    p = line.strip('"').split('","')
    if len(p)>=2:
        try: pids.append(int(p[1]))
        except: pass

# Find ALL WinOLS windows
wins = []
def cb(h,l):
    p=wt.DWORD(0); user32.GetWindowThreadProcessId(h, ctypes.byref(p))
    if p.value in pids:
        tb=ctypes.create_unicode_buffer(256); cb2=ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(h,tb,256); user32.GetClassNameW(h,cb2,64)
        r2=wt.RECT(); user32.GetWindowRect(h,ctypes.byref(r2))
        area=(r2.right-r2.left)*(r2.bottom-r2.top)
        wins.append((h, tb.value, cb2.value, area))
    return True
user32.EnumWindows(WNDENUMPROC(cb), 0)

# Sort by area descending
wins.sort(key=lambda x: x[3], reverse=True)
print("All WinOLS windows:")
for h,t,c,a in wins[:10]:
    menu = user32.GetMenu(h)
    mc = user32.GetMenuItemCount(menu) if menu else -1
    print(f"  0x{h:08X} area={a:7d} menu_items={mc:3d} vis={bool(user32.IsWindowVisible(h))} cls={c!r} title={t!r}")

class MII(ctypes.Structure):
    _fields_ = [("cbSize",wt.UINT),("fMask",wt.UINT),("fType",wt.UINT),
                ("fState",wt.UINT),("wID",wt.UINT),("hSubMenu",wt.HMENU),
                ("hbmpChecked",wt.HBITMAP),("hbmpUnchecked",wt.HBITMAP),
                ("dwItemData",ctypes.c_ulong),("dwTypeData",ctypes.c_wchar_p),
                ("cch",wt.UINT),("hbmpItem",wt.HBITMAP)]

# Scan menus on all windows
print("\nMenu scan:")
for h,t,c,a in wins:
    menu = user32.GetMenu(h)
    if not menu: continue
    mc = user32.GetMenuItemCount(menu)
    print(f"\n  Window 0x{h:08X} '{t}' has {mc} menu items:")
    for i in range(mc):
        buf=ctypes.create_unicode_buffer(256)
        m=MII(); m.cbSize=ctypes.sizeof(m); m.fMask=0x46
        m.dwTypeData=ctypes.cast(buf,ctypes.c_wchar_p); m.cch=256
        user32.GetMenuItemInfoW(menu, i, True, ctypes.byref(m))
        txt = buf.value
        print(f"    [{i}] id={m.wID} {repr(txt)}")
        if m.hSubMenu:
            sc = user32.GetMenuItemCount(m.hSubMenu)
            for j in range(sc):
                buf2=ctypes.create_unicode_buffer(256)
                m2=MII(); m2.cbSize=ctypes.sizeof(m2); m2.fMask=0x46
                m2.dwTypeData=ctypes.cast(buf2,ctypes.c_wchar_p); m2.cch=256
                user32.GetMenuItemInfoW(m.hSubMenu, j, True, ctypes.byref(m2))
                print(f"      [{j}] id={m2.wID} {repr(buf2.value)}")
