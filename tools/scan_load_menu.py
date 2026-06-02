"""scan_load_menu.py - Scan WinOLS menu to find Load/Disconnect state"""
import ctypes, ctypes.wintypes as wt, subprocess, sys
sys.stdout.reconfigure(line_buffering=True)

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

def get_pids():
    r = subprocess.run(['tasklist','/FI','IMAGENAME eq ols_32on32.exe','/FO','CSV'],
                       capture_output=True, text=True)
    pids = []
    for line in r.stdout.splitlines()[1:]:
        p = line.strip('"').split('","')
        if len(p) >= 2:
            try: pids.append(int(p[1]))
            except: pass
    return pids

def get_wins(pids, vis=False, min_area=0):
    wins = []
    def cb(h, l):
        p = wt.DWORD(0); user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value not in pids: return True
        tb = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(h, tb, 256)
        r2 = wt.RECT(); user32.GetWindowRect(h, ctypes.byref(r2))
        a = (r2.right - r2.left) * (r2.bottom - r2.top)
        if a >= min_area: wins.append((h, tb.value, a))
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return sorted(wins, key=lambda x: x[2], reverse=True)

class MII(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.UINT), ("fMask", wt.UINT), ("fType", wt.UINT),
        ("fState", wt.UINT), ("wID", wt.UINT), ("hSubMenu", wt.HMENU),
        ("hbmpChecked", wt.HBITMAP), ("hbmpUnchecked", wt.HBITMAP),
        ("dwItemData", ctypes.c_ulong), ("dwTypeData", ctypes.c_wchar_p),
        ("cch", wt.UINT), ("hbmpItem", wt.HBITMAP)
    ]

def scan_menu(hmenu, depth=0):
    count = user32.GetMenuItemCount(hmenu)
    for i in range(count):
        buf = ctypes.create_unicode_buffer(256)
        m = MII(); m.cbSize = ctypes.sizeof(m)
        m.fMask = 0x46; m.dwTypeData = ctypes.cast(buf, ctypes.c_wchar_p); m.cch = 256
        user32.GetMenuItemInfoW(hmenu, i, True, ctypes.byref(m))
        grayed = (m.fState & 3) != 0
        sep = m.fType & 0x800
        if not sep:
            print('  ' * depth + f'[{i}] id={m.wID} state={m.fState:#x} {"GRAYED " if grayed else ""}{buf.value!r}')
        if m.hSubMenu:
            scan_menu(m.hSubMenu, depth + 1)

pids = get_pids()
wins = get_wins(pids, min_area=400000)
main_win = wins[0][0] if wins else None
print(f'Main: 0x{main_win:08X}')

menu = user32.GetMenu(main_win)
print(f'Menu: 0x{menu:08X}')
if menu:
    scan_menu(menu)
