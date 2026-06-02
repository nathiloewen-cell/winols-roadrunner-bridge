"""
click_load_fast.py - After Config OK, immediately click Load/Disconnect
before the crash happens (~5 second window after EP6 polls).

Flow:
1. Monitor log for EP6 polls (identification started)
2. Immediately find and click Hardware → Simulator → Load/Disconnect
3. Handle Select producer dialog (16 Bit → OK)
4. Capture EP2 TX commands in log
"""
import ctypes, ctypes.wintypes as wt, subprocess, time, sys, struct

user32 = ctypes.windll.user32
k32    = ctypes.windll.kernel32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

WINOLS_LOG = r"C:\Users\Nates\AppData\Local\Temp\winols_wdapi.log"
WM_CMD_LOAD_DISC = 0  # Will be found via scan

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

def enum_wins(pids, vis=True):
    wins = []
    def cb(h,l):
        p=wt.DWORD(0); user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value not in pids: return True
        if vis and not user32.IsWindowVisible(h): return True
        tb=ctypes.create_unicode_buffer(256); cl=ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(h,tb,256); user32.GetClassNameW(h,cl,64)
        r2=wt.RECT(); user32.GetWindowRect(h,ctypes.byref(r2))
        area=(r2.right-r2.left)*(r2.bottom-r2.top)
        wins.append((h,tb.value,cl.value,area))
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return sorted(wins, key=lambda x: x[3], reverse=True)

def find_child(parent, cls_f=None, txt_f=None):
    found=[None]
    def cb(h,l):
        tb=ctypes.create_unicode_buffer(256); cl=ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(h,tb,256); user32.GetClassNameW(h,cl,64)
        ok=True
        if cls_f and cls_f.lower() not in cl.value.lower(): ok=False
        if txt_f and txt_f.lower() not in tb.value.lower(): ok=False
        if ok: found[0]=h
        return True
    user32.EnumChildWindows(parent, WNDENUMPROC(cb), 0)
    return found[0]

def bclick(h):
    user32.SetForegroundWindow(h); time.sleep(0.1)
    user32.SendMessageW(h, 0x00F5, 0, 0)

def log_size():
    try:
        h = k32.CreateFileW(WINOLS_LOG, 0x80000000, 7, None, 3, 0, None)
        sz = k32.GetFileSize(h, None); k32.CloseHandle(h); return sz
    except: return 0

def log_has(text, from_offset=0):
    try:
        h = k32.CreateFileW(WINOLS_LOG, 0x80000000, 7, None, 3, 0, None)
        sz = k32.GetFileSize(h, None)
        off = max(0, sz - 3000)
        k32.SetFilePointer(h, off, None, 0)
        buf = ctypes.create_string_buffer(3000); rd = wt.DWORD(0)
        k32.ReadFile(h, buf, 3000, ctypes.byref(rd), None)
        k32.CloseHandle(h)
        return text.encode() in buf.raw[:rd.value]
    except: return False

def find_load_disc_cmd(main_win, pids):
    """Find the WM_COMMAND ID for Hardware → Simulator → Load/Disconnect."""
    menu = user32.GetMenu(main_win)
    if not menu: return 0
    count = user32.GetMenuItemCount(menu)

    class MII(ctypes.Structure):
        _fields_=[("cbSize",wt.UINT),("fMask",wt.UINT),("fType",wt.UINT),
                  ("fState",wt.UINT),("wID",wt.UINT),("hSubMenu",wt.HMENU),
                  ("hbmpChecked",wt.HBITMAP),("hbmpUnchecked",wt.HBITMAP),
                  ("dwItemData",ctypes.c_ulong),("dwTypeData",ctypes.c_wchar_p),
                  ("cch",wt.UINT),("hbmpItem",wt.HBITMAP)]

    for i in range(count):
        buf=ctypes.create_unicode_buffer(256); m=MII(); m.cbSize=ctypes.sizeof(m)
        m.fMask=0x46; m.dwTypeData=ctypes.cast(buf,ctypes.c_wchar_p); m.cch=256
        user32.GetMenuItemInfoW(menu, i, True, ctypes.byref(m))
        if 'hardware' in buf.value.lower() and m.hSubMenu:
            sc = user32.GetMenuItemCount(m.hSubMenu)
            for j in range(sc):
                buf2=ctypes.create_unicode_buffer(256); m2=MII(); m2.cbSize=ctypes.sizeof(m2)
                m2.fMask=0x46; m2.dwTypeData=ctypes.cast(buf2,ctypes.c_wchar_p); m2.cch=256
                user32.GetMenuItemInfoW(m.hSubMenu, j, True, ctypes.byref(m2))
                if 'simulator' in buf2.value.lower() and m2.hSubMenu:
                    sc2 = user32.GetMenuItemCount(m2.hSubMenu)
                    for k in range(sc2):
                        buf3=ctypes.create_unicode_buffer(256); m3=MII(); m3.cbSize=ctypes.sizeof(m3)
                        m3.fMask=0x46; m3.dwTypeData=ctypes.cast(buf3,ctypes.c_wchar_p); m3.cch=256
                        user32.GetMenuItemInfoW(m2.hSubMenu, k, True, ctypes.byref(m3))
                        if 'load' in buf3.value.lower() or 'disconnect' in buf3.value.lower():
                            return m3.wID
                    # If no text match, return first item of simulator submenu
                    buf3=ctypes.create_unicode_buffer(256); m3=MII(); m3.cbSize=ctypes.sizeof(m3)
                    m3.fMask=0x46; m3.dwTypeData=ctypes.cast(buf3,ctypes.c_wchar_p); m3.cch=256
                    user32.GetMenuItemInfoW(m2.hSubMenu, 0, True, ctypes.byref(m3))
                    return m3.wID
    return 0

def click_load_disconnect(main_win, pids):
    """Click Hardware → Simulator → Load/Disconnect."""
    cmd_id = find_load_disc_cmd(main_win, pids)
    if cmd_id:
        print(f"  Load/Disconnect cmd_id={cmd_id}, posting...")
        user32.PostMessageW(main_win, 0x0111, cmd_id, 0)
        return True
    print("  Load/Disconnect not found via menu")
    return False

def handle_producer_dialog(pids):
    """Find Select producer dialog and click 16-bit + OK."""
    time.sleep(1.5)
    for attempt in range(20):
        time.sleep(0.5)
        wins = enum_wins(pids)
        for h,t,c,a in wins:
            if a < 5000: continue
            ok_b = find_child(h, 'button', 'OK')
            cancel_b = find_child(h, 'button', 'Cancel') or find_child(h, 'button', 'Abbrechen')
            if ok_b and cancel_b and a > 30000:
                print(f"  Producer dialog: '{t}' area={a}")
                # Select 16 Bit or similar
                for s in ['16 Bit', '16 bit', 'Bit', '8 Bit']:
                    r = find_child(h, None, s)
                    if r:
                        cls_buf = ctypes.create_unicode_buffer(64)
                        user32.GetClassNameW(r, cls_buf, 64)
                        if 'listbox' in cls_buf.value.lower() or 'button' in cls_buf.value.lower():
                            print(f"  Selecting: {s}")
                            user32.SetForegroundWindow(r)
                            time.sleep(0.1)
                            user32.SendMessageW(r, 0x00F5, 0, 0)
                            time.sleep(0.3)
                            break
                print("  Clicking OK")
                bclick(ok_b)
                return True
    print("  No producer dialog found")
    return False

def main():
    pids = get_pids()
    if not pids: print("WinOLS not running!"); sys.exit(1)
    print(f"PIDs: {pids}")

    # Wait for EP6 polls (identification started)
    print("Waiting for EP6 polls...")
    baseline = log_size()
    t0 = time.time()
    ep6_detected = False
    while time.time()-t0 < 30:
        time.sleep(0.3)
        if log_has('ID pipe'):
            ep6_detected = True
            break

    if not ep6_detected:
        print("No EP6 polls detected. Proceeding anyway...")

    print(f"EP6 detected, clicking Load/Disconnect immediately...")
    time.sleep(0.2)  # Brief stabilization

    # Find main window
    main_win = None
    wins = enum_wins(pids, vis=False)
    for h,t,c,a in wins:
        if a > 400000:
            main_win = h; print(f"Main window: 0x{h:08X}"); break

    if not main_win:
        print("No main window!"); sys.exit(1)

    # Click Load/Disconnect
    clicked = click_load_disconnect(main_win, pids)
    if clicked:
        print("Load/Disconnect command sent!")
        result = handle_producer_dialog(pids)
        if result:
            print("SUCCESS: Select producer dialog handled!")
            # Wait for EP2 commands
            print("Waiting for EP2 TX commands...")
            t0 = time.time()
            while time.time()-t0 < 10:
                time.sleep(1)
                if log_has('OLS300 cmd'):
                    print("EP2 LOAD COMMANDS CAPTURED!")
                    break
        else:
            print("No producer dialog appeared")
    else:
        print("Failed to click Load/Disconnect")

if __name__ == '__main__':
    main()
