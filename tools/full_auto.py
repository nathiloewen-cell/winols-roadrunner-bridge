"""
full_auto.py - Complete automation: startup → Config OK → crash dismiss → Load/Disconnect

Flow:
1. Dismiss startup dialogs (Nein, Don't send, no-mulitple-ols)
2. Click Config OK (opens identification sequence)
3. Dismiss crash/error dialogs that appear
4. Click Load/Disconnect
5. Handle Select producer dialog (16 Bit → OK)
6. Capture EP2 commands
"""
import ctypes, ctypes.wintypes as wt, subprocess, time, sys

user32 = ctypes.windll.user32
k32    = ctypes.windll.kernel32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

WINOLS_LOG   = r"C:\Users\Nates\AppData\Local\Temp\winols_wdapi.log"
WM_CMD_CONF  = 32827   # Miscellaneous → Configuration
KEYBDINPUT = type('KEYBDINPUT', (ctypes.Structure,), {'_fields_': [
    ("wVk",wt.WORD),("wScan",wt.WORD),("dwFlags",wt.DWORD),
    ("time",wt.DWORD),("dwExtraInfo",ctypes.c_ulong)]})
INPUT = type('INPUT', (ctypes.Structure,), {'_fields_': [
    ("type",wt.DWORD),("ki",KEYBDINPUT)]})

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

def get_wins(pids, vis=True, min_area=0):
    wins = []
    def cb(h,l):
        p=wt.DWORD(0); user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value not in pids: return True
        if vis and not user32.IsWindowVisible(h): return True
        tb=ctypes.create_unicode_buffer(256); cl=ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(h,tb,256); user32.GetClassNameW(h,cl,64)
        r2=wt.RECT(); user32.GetWindowRect(h,ctypes.byref(r2))
        area=(r2.right-r2.left)*(r2.bottom-r2.top)
        if area >= min_area: wins.append((h,tb.value,cl.value,area))
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
    user32.SetForegroundWindow(h); time.sleep(0.15)
    user32.SendMessageW(h, 0x00F5, 0, 0)

def dismiss_all(pids, timeout=8, exclude_main=True):
    """Click away all blocking dialogs."""
    DISMISS = ['Nein','No',"Don't send",'Nicht senden','OK','Cancel','Close','Schließen','Don\'t']
    dismissed = 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = False
        wins = get_wins(pids, vis=True, min_area=100)
        for h,t,c,a in wins:
            if exclude_main and a > 300000: continue  # skip main window
            for btxt in DISMISS:
                btn = find_child(h, 'button', btxt)
                if btn:
                    print(f"  Dismiss '{t}' -> '{btxt}'")
                    bclick(btn)
                    dismissed += 1
                    found = True
                    time.sleep(0.5)
                    break
            if found: break
        if not found: break
    return dismissed

def find_main_win(pids):
    wins = get_wins(pids, vis=False, min_area=400000)
    for h,t,c,a in wins:
        if 'winols' in t.lower(): return h
    return wins[0][0] if wins else None

def treeview_select_simulator(config_dlg):
    """Find SysTreeView32 and select Simulator (last item = End key)."""
    tv = find_child(config_dlg, 'systreeview')
    if not tv: tv = find_child(config_dlg, 'treeview')
    if tv:
        user32.SetForegroundWindow(tv); time.sleep(0.2)
        user32.SendMessageW(tv, 0x0100, 0x23, 0)  # End key
        time.sleep(0.3)
        return True
    return False

def click_config_ok(pids, main_win):
    """Open Configuration dialog, select Simulator, click OK."""
    print("  Opening Configuration dialog...")
    user32.PostMessageW(main_win, 0x0111, WM_CMD_CONF, 0)
    time.sleep(1.5)
    # Find config dialog by title "Configuration"
    config_dlg = None
    for attempt in range(6):
        wins = get_wins(pids, vis=True, min_area=50000)
        for h,t,c,a in wins:
            if 'configuration' in t.lower() or 'konfiguration' in t.lower():
                config_dlg = h
                print(f"  Config dialog: '{t}' hwnd=0x{h:08X}")
                break
        if config_dlg:
            break
        time.sleep(0.5)
    if not config_dlg:
        # Fallback: look for any dialog with OK + Abbrechen
        for h,t,c,a in get_wins(pids, vis=True, min_area=50000):
            ok_b = find_child(h, 'button', 'OK')
            ab_b = find_child(h, 'button', 'Abbrechen') or find_child(h, 'button', 'Cancel')
            if ok_b and ab_b and a < 700000:
                config_dlg = h
                print(f"  Config dialog (fallback): '{t}' hwnd=0x{h:08X}")
                break
    if not config_dlg:
        print("  Config dialog not found!")
        return False
    # Select Simulator in tree
    treeview_select_simulator(config_dlg)
    # Click USB OLS300 radio
    for s in ['OLS300','USB']:
        r = find_child(config_dlg, 'button', s)
        if r: bclick(r); time.sleep(0.2); break
    # Click OK via physical mouse click (avoids SendMessage deadlock)
    ok_b = find_child(config_dlg, 'button', 'OK')
    if ok_b:
        tb = ctypes.create_unicode_buffer(64); user32.GetWindowTextW(ok_b,tb,64)
        if tb.value.strip().upper() == 'OK':
            r2 = wt.RECT(); user32.GetWindowRect(ok_b, ctypes.byref(r2))
            cx = (r2.left + r2.right) // 2
            cy = (r2.top + r2.bottom) // 2
            print(f"  Clicking OK at ({cx},{cy})")
            user32.SetForegroundWindow(config_dlg); time.sleep(0.15)
            user32.SetCursorPos(cx, cy); time.sleep(0.05)
            user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
            time.sleep(0.05)
            user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
            time.sleep(0.2)
            return True
    return False

def click_load_disconnect(pids, main_win):
    """Click Hardware → Simulator → Load/Disconnect via menu."""
    # Known Load command ID from empirical testing: 32807
    LOAD_ID = 32807
    menu = user32.GetMenu(main_win)
    if not menu: return False
    count = user32.GetMenuItemCount(menu)

    class MII(ctypes.Structure):
        _fields_=[("cbSize",wt.UINT),("fMask",wt.UINT),("fType",wt.UINT),
                  ("fState",wt.UINT),("wID",wt.UINT),("hSubMenu",wt.HMENU),
                  ("hbmpChecked",wt.HBITMAP),("hbmpUnchecked",wt.HBITMAP),
                  ("dwItemData",ctypes.c_ulong),("dwTypeData",ctypes.c_wchar_p),
                  ("cch",wt.UINT),("hbmpItem",wt.HBITMAP)]

    # Try text-based search first (works if menus not owner-drawn)
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
                    buf3=ctypes.create_unicode_buffer(256); m3=MII(); m3.cbSize=ctypes.sizeof(m3)
                    m3.fMask=0x46; m3.dwTypeData=ctypes.cast(buf3,ctypes.c_wchar_p); m3.cch=256
                    user32.GetMenuItemInfoW(m2.hSubMenu, 0, True, ctypes.byref(m3))
                    state = m3.fState
                    is_grayed = (state & 3) != 0
                    print(f"  Load id={m3.wID} state={state:#x} grayed={is_grayed}")
                    if not is_grayed:
                        user32.PostMessageW(main_win, 0x0111, m3.wID, 0)
                        return True
                    return False

    # Fallback: use known Load ID=32807 directly (WinOLS owner-drawn menus)
    print(f"  Using known Load id={LOAD_ID} (owner-drawn menu fallback)")
    user32.PostMessageW(main_win, 0x0111, LOAD_ID, 0)
    return True

def handle_producer_dialog(pids):
    """Find Select producer dialog and click 16-bit + OK."""
    for attempt in range(15):
        time.sleep(0.8)
        wins = get_wins(pids, vis=True, min_area=30000)
        for h,t,c,a in wins:
            ok_b = find_child(h, 'button', 'OK')
            cancel_b = find_child(h, 'button', 'Cancel') or find_child(h, 'button', 'Abbrechen')
            if ok_b and cancel_b:
                print(f"  Producer dialog: '{t}' area={a}")
                # Click 16 Bit in list
                wins2 = []
                def cb2(ch,l): wins2.append(ch); return True
                user32.EnumChildWindows(h, WNDENUMPROC(cb2), 0)
                for ch in wins2:
                    tb=ctypes.create_unicode_buffer(256); cl=ctypes.create_unicode_buffer(64)
                    user32.GetWindowTextW(ch,tb,256); user32.GetClassNameW(ch,cl,64)
                    if '16' in tb.value and 'listbox' in cl.value.lower():
                        user32.SendMessageW(ch, 0x0186, 0, ctypes.c_long(-1))  # LB_SELECTSTRING
                        # Find "16 Bit eprom"
                        for line_idx in range(user32.SendMessageW(ch, 0x018B, 0, 0)):  # LB_GETCOUNT
                            buf2 = ctypes.create_unicode_buffer(100)
                            user32.SendMessageW(ch, 0x0189, line_idx, ctypes.cast(buf2, ctypes.c_long))
                            if '16' in buf2.value:
                                user32.SendMessageW(ch, 0x0186, line_idx, 0)  # LB_SETCURSEL
                                print(f"  Selected: {buf2.value}")
                                break
                        break
                print("  Clicking OK")
                bclick(ok_b)
                return True
    print("  No producer dialog found")
    return False

def log_tail(n=20):
    try:
        h=k32.CreateFileW(WINOLS_LOG,0x80000000,7,None,3,0,None)
        sz=k32.GetFileSize(h,None); off=max(0,sz-n*100)
        k32.SetFilePointer(h,off,None,0)
        buf=ctypes.create_string_buffer(n*100); rd=wt.DWORD(0)
        k32.ReadFile(h,buf,n*100,ctypes.byref(rd),None); k32.CloseHandle(h)
        return buf.raw[:rd.value].decode('utf-8','replace').splitlines()
    except: return []

def main():
    pids = get_pids()
    if not pids: print("WinOLS not running!"); sys.exit(1)
    print(f"PIDs: {pids}")

    # Phase 1: Dismiss startup dialogs
    print("\n[Phase 1] Dismiss startup dialogs...")
    n = dismiss_all(pids, timeout=10)
    print(f"  Dismissed {n} dialogs")
    time.sleep(1)

    pids = get_pids()
    if not pids: print("WinOLS exited!"); sys.exit(1)

    # Phase 2: Find main window — wait until title is set
    print("\n[Phase 2] Find main window...")
    main_win = None
    for attempt in range(15):
        time.sleep(1)
        wins = get_wins(pids, vis=False, min_area=400000)
        for h,t,c,a in wins:
            if 'winols' in t.lower() and a > 400000:
                main_win = h
                print(f"  Main: 0x{h:08X} '{t}' area={a}")
                break
        if main_win: break
        print(f"  Waiting for WinOLS title... (attempt {attempt+1})")
    if not main_win:
        # Use largest window even without title
        wins = get_wins(pids, vis=False, min_area=400000)
        if wins:
            main_win = wins[0][0]
            print(f"  Fallback: 0x{main_win:08X} area={wins[0][3]}")

    # Phase 3: Click Config OK
    print("\n[Phase 3] Config → Simulator → USB OLS300 → OK...")
    ok = click_config_ok(pids, main_win)
    if not ok:
        print("  Config OK failed")

    # Phase 4: Watch for EP6 polls → try Load immediately, dismiss crashes
    print("\n[Phase 4] Watching for EP6 + trying Load immediately...")
    t0 = time.time()
    ep6_seen = False
    load_clicked = False
    while time.time()-t0 < 60:
        time.sleep(0.5)
        # Dismiss crash/error dialogs
        pids = get_pids()
        if not pids:
            print("  WinOLS exited!")
            sys.exit(1)
        dismissed = dismiss_all(pids, timeout=0.3, exclude_main=True)
        if dismissed:
            print(f"  Dismissed {dismissed} crash dialog(s)")
        # Check log for EP6 polls
        lines = log_tail(10)
        if not ep6_seen and any('ID pipe' in l for l in lines[-5:]):
            ep6_seen = True
            print(f"  EP6 polls detected at t={time.time()-t0:.1f}s - trying Load NOW!")
        # Try Load immediately when EP6 detected (Load might be active NOW)
        if ep6_seen and not load_clicked:
            pids = get_pids()
            mw = find_main_win(pids)
            if mw:
                time.sleep(0.3)  # Brief settle
                if click_load_disconnect(pids, mw):
                    load_clicked = True
                    print(f"  Load clicked at t={time.time()-t0:.1f}s!")
                    break
        # Also try after each pfDeviceAttach
        if any('pfDeviceAttach returned 1' in l for l in lines[-3:]) and not load_clicked:
            pids = get_pids()
            mw = find_main_win(pids)
            if mw:
                time.sleep(0.5)
                if click_load_disconnect(pids, mw):
                    load_clicked = True
                    print(f"  Load clicked after pfDeviceAttach!")
                    break
        # Check if WDU_Uninit appeared (cycle complete without Load)
        if any('WDU_Uninit' in l for l in lines[-5:]) and ep6_seen:
            print(f"  WDU_Uninit at t={time.time()-t0:.1f}s")
            break
    if not load_clicked:
        print("  Load was not clicked during identification window")

    # Phase 5: Click Load/Disconnect
    print("\n[Phase 5] Click Load/Disconnect...")
    pids = get_pids()
    if not pids: print("WinOLS exited!"); sys.exit(1)
    main_win = find_main_win(pids)
    time.sleep(1)  # Let UI settle
    loaded = click_load_disconnect(pids, main_win)
    if not loaded:
        print("  Load/Disconnect not available or grayed")
        print("  Final log:")
        for l in log_tail(5)[-3:]: print(f"    {l}")
        sys.exit(1)

    # Phase 6: Handle producer dialog
    print("\n[Phase 6] Handle Select producer dialog...")
    result = handle_producer_dialog(pids)
    if result:
        print("  Producer dialog handled!")
        # Wait for EP2 commands
        print("\n[Phase 7] Waiting for EP2 TX commands...")
        t0 = time.time()
        while time.time()-t0 < 15:
            time.sleep(1)
            lines = log_tail(10)
            if any('OLS300 cmd' in l for l in lines[-5:]):
                print("  EP2 LOAD COMMANDS CAPTURED!")
                for l in lines:
                    if 'OLS300 cmd' in l or 'TX' in l: print(f"    {l}")
                break
    print("\nDone.")

if __name__ == '__main__':
    main()
