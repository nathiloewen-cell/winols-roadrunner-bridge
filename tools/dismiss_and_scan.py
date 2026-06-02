import ctypes, ctypes.wintypes as wt, subprocess, time

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

def get_pids():
    r = subprocess.run(["tasklist","/FI","IMAGENAME eq ols_32on32.exe","/FO","CSV"],
                       capture_output=True, text=True)
    pids = []
    for line in r.stdout.splitlines()[1:]:
        p = line.strip('"').split('","')
        if len(p)>=2:
            try: pids.append(int(p[1]))
            except: pass
    return pids

def get_wins(pids):
    wins = []
    def cb(h,l):
        p=wt.DWORD(0); user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value in pids:
            tb=ctypes.create_unicode_buffer(256); cl=ctypes.create_unicode_buffer(64)
            user32.GetWindowTextW(h,tb,256); user32.GetClassNameW(h,cl,64)
            r2=wt.RECT(); user32.GetWindowRect(h,ctypes.byref(r2))
            area=(r2.right-r2.left)*(r2.bottom-r2.top)
            wins.append((h,tb.value,cl.value,area))
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return wins

def find_button(parent, texts):
    found = [None, None]
    def bc(h,l):
        tb=ctypes.create_unicode_buffer(128); cl=ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(h,tb,128); user32.GetClassNameW(h,cl,64)
        for t in texts:
            if t.lower() in tb.value.lower() and "button" in cl.value.lower():
                found[0]=h; found[1]=tb.value
        return True
    user32.EnumChildWindows(parent, WNDENUMPROC(bc), 0)
    return found[0], found[1]

pids = get_pids()
print("PIDs:", pids)

# Phase 1: Dismiss all startup dialogs
print("\nPhase 1: Dismiss startup dialogs...")
DISMISS_MAP = [
    (["Nein","No"], "Crash recovery (Nein)"),
    (["Don't send","Nicht senden"], "Error report (Don't send)"),
    (["OK"], "Any OK dialog"),
]
for attempt in range(15):
    wins = get_wins(pids)
    dismissed_any = False
    for h,t,c,a in wins:
        if a > 300000: continue  # skip main window
        for btns, desc in DISMISS_MAP:
            btn, btxt = find_button(h, btns)
            if btn:
                print(f"  [{attempt}] Dismiss '{t}' -> click '{btxt}' ({desc})")
                user32.SetForegroundWindow(btn); time.sleep(0.1)
                user32.SendMessageW(btn, 0x00F5, 0, 0)
                dismissed_any = True
                time.sleep(0.6)
                break
        if dismissed_any: break
    if not dismissed_any:
        print(f"  No more dialogs after {attempt} dismissals")
        break
    time.sleep(0.3)

time.sleep(2)  # Let WinOLS finish initializing

# Phase 2: Scan menus
print("\nPhase 2: Scan menus...")
pids = get_pids()
wins = get_wins(pids)
wins.sort(key=lambda x: x[3], reverse=True)
print(f"Windows found: {len(wins)}")

class MII(ctypes.Structure):
    _fields_ = [("cbSize",wt.UINT),("fMask",wt.UINT),("fType",wt.UINT),
                ("fState",wt.UINT),("wID",wt.UINT),("hSubMenu",wt.HMENU),
                ("hbmpChecked",wt.HBITMAP),("hbmpUnchecked",wt.HBITMAP),
                ("dwItemData",ctypes.c_ulong),("dwTypeData",ctypes.c_wchar_p),
                ("cch",wt.UINT),("hbmpItem",wt.HBITMAP)]

config_id = None
for h,t,c,a in wins[:5]:
    menu = user32.GetMenu(h)
    if not menu: continue
    mc = user32.GetMenuItemCount(menu)
    print(f"\nWindow 0x{h:08X} area={a} cls={c!r} title={t!r}: {mc} menu items")
    for i in range(mc):
        buf=ctypes.create_unicode_buffer(256)
        m=MII(); m.cbSize=ctypes.sizeof(m); m.fMask=0x46
        m.dwTypeData=ctypes.cast(buf,ctypes.c_wchar_p); m.cch=256
        user32.GetMenuItemInfoW(menu, i, True, ctypes.byref(m))
        txt = buf.value
        print(f"  [{i}] id={m.wID} {repr(txt)}")
        if m.hSubMenu:
            sc = user32.GetMenuItemCount(m.hSubMenu)
            for j in range(sc):
                buf2=ctypes.create_unicode_buffer(256)
                m2=MII(); m2.cbSize=ctypes.sizeof(m2); m2.fMask=0x46
                m2.dwTypeData=ctypes.cast(buf2,ctypes.c_wchar_p); m2.cch=256
                user32.GetMenuItemInfoW(m.hSubMenu, j, True, ctypes.byref(m2))
                s2 = buf2.value
                print(f"    [{j}] id={m2.wID} {repr(s2)}")
                if "config" in s2.lower() or "konfig" in s2.lower():
                    config_id = m2.wID
                    print(f"    *** CONFIG MENU ITEM FOUND: id={m2.wID} ***")

if config_id:
    print(f"\nConfig menu ID: {config_id}")
    print("Use: user32.PostMessageW(hwnd, 0x0111, config_id, 0)")
else:
    print("\nNo config menu item found in any menu.")
