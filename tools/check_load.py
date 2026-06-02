import ctypes, ctypes.wintypes as wt, subprocess
user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

def get_pids():
    r = subprocess.run(["tasklist","/FI","IMAGENAME eq ols_32on32.exe","/FO","CSV"],capture_output=True,text=True)
    pids = []
    for l in r.stdout.splitlines()[1:]:
        p = l.strip('"').split('","')
        if len(p)>=2:
            try: pids.append(int(p[1]))
            except: pass
    return pids

pids = get_pids()
print("PIDs:", pids)

wins = []
def cb(h,l):
    p=wt.DWORD(0); user32.GetWindowThreadProcessId(h,ctypes.byref(p))
    if p.value not in pids: return True
    tb=ctypes.create_unicode_buffer(256); user32.GetWindowTextW(h,tb,256)
    r2=wt.RECT(); user32.GetWindowRect(h,ctypes.byref(r2))
    area=(r2.right-r2.left)*(r2.bottom-r2.top)
    if area > 400000: wins.append((h,tb.value,area))
    return True
user32.EnumWindows(WNDENUMPROC(cb), 0)
wins.sort(key=lambda x: x[2], reverse=True)
main_win = wins[0][0] if wins else None
if not main_win: print("No main!"); exit()

menu = user32.GetMenu(main_win)
count = user32.GetMenuItemCount(menu)

class MII(ctypes.Structure):
    _fields_=[("cbSize",wt.UINT),("fMask",wt.UINT),("fType",wt.UINT),
              ("fState",wt.UINT),("wID",wt.UINT),("hSubMenu",wt.HMENU),
              ("hbmpChecked",wt.HBITMAP),("hbmpUnchecked",wt.HBITMAP),
              ("dwItemData",ctypes.c_ulong),("dwTypeData",ctypes.c_wchar_p),
              ("cch",wt.UINT),("hbmpItem",wt.HBITMAP)]

# Hardware is Menu[2] based on earlier scan
buf=ctypes.create_unicode_buffer(256); m=MII(); m.cbSize=ctypes.sizeof(m)
m.fMask=0x46; m.dwTypeData=ctypes.cast(buf,ctypes.c_wchar_p); m.cch=256
user32.GetMenuItemInfoW(menu, 2, True, ctypes.byref(m))
hw_text = buf.value
print(f"Menu[2]: '{hw_text}' sub={bool(m.hSubMenu)}")

if m.hSubMenu:
    hw_sub = m.hSubMenu
    hw_count = user32.GetMenuItemCount(hw_sub)
    print(f"Hardware submenu: {hw_count} items")
    for j in range(hw_count):
        buf2=ctypes.create_unicode_buffer(256); m2=MII(); m2.cbSize=ctypes.sizeof(m2)
        m2.fMask=0x46; m2.dwTypeData=ctypes.cast(buf2,ctypes.c_wchar_p); m2.cch=256
        user32.GetMenuItemInfoW(hw_sub, j, True, ctypes.byref(m2))
        grayed = (m2.fState & 3) != 0
        print(f"  [{j}] id={m2.wID} state=0x{m2.fState:X} grayed={grayed} text='{buf2.value}'")
        if m2.hSubMenu:
            # Check inside this submenu
            sc = user32.GetMenuItemCount(m2.hSubMenu)
            for k in range(min(sc, 5)):
                buf3=ctypes.create_unicode_buffer(256); m3=MII(); m3.cbSize=ctypes.sizeof(m3)
                m3.fMask=0x46; m3.dwTypeData=ctypes.cast(buf3,ctypes.c_wchar_p); m3.cch=256
                user32.GetMenuItemInfoW(m2.hSubMenu, k, True, ctypes.byref(m3))
                grayed3 = (m3.fState & 3) != 0
                print(f"    [{k}] id={m3.wID} state=0x{m3.fState:X} grayed={grayed3} '{buf3.value}'")
                if k == 0 and not grayed3:
                    print(f"  *** LOAD IS ACTIVE! id={m3.wID} ***")
                    user32.PostMessageW(main_win, 0x0111, m3.wID, 0)
                    print("  CLICKED!")
