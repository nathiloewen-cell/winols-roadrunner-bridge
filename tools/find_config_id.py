"""
Find the WM_COMMAND ID that opens the WinOLS Configuration dialog.
Tests each Miscellaneous submenu item ID.
"""
import ctypes, ctypes.wintypes as wt, subprocess, time

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
WM_COMMAND = 0x0111

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

def get_winols_wins(pids):
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

def find_main_win(pids):
    wins = get_winols_wins(pids)
    wins.sort(key=lambda x: x[3], reverse=True)
    for h,t,c,a in wins:
        if a > 300000 and "winols" in t.lower():
            return h
    return wins[0][0] if wins else None

def count_dialogs(pids, baseline_handles):
    """Count new dialog windows that appeared."""
    wins = get_winols_wins(pids)
    new_dlgs = []
    for h,t,c,a in wins:
        if h not in baseline_handles and 1000 < a < 400000:
            new_dlgs.append((h,t,c,a))
    return new_dlgs

def dismiss_all(pids):
    wins = get_winols_wins(pids)
    for h,t,c,a in wins:
        if a > 300000: continue
        found = [None]
        def bc(bh,l):
            btb=ctypes.create_unicode_buffer(128); bcl=ctypes.create_unicode_buffer(64)
            user32.GetWindowTextW(bh,btb,128); user32.GetClassNameW(bh,bcl,64)
            if "button" in bcl.value.lower():
                txt = btb.value.lower()
                if any(x in txt for x in ["nein","no","cancel","don","close","ok"]):
                    found[0]=bh
            return True
        user32.EnumChildWindows(h, WNDENUMPROC(bc), 0)
        if found[0]:
            user32.SetForegroundWindow(found[0]); time.sleep(0.05)
            user32.SendMessageW(found[0], 0x00F5, 0, 0)
            time.sleep(0.3)

pids = get_pids()
print("PIDs:", pids)

# Get baseline windows
baseline = set(h for h,t,c,a in get_winols_wins(pids))
main_win = find_main_win(pids)
print(f"Main window: 0x{main_win:08X}")

# Miscellaneous submenu IDs (from scan)
misc_ids = [40020, 33125, 32827, 32899, 33124, 33582]
print(f"\nTesting {len(misc_ids)} menu IDs...")

for cmd_id in misc_ids:
    print(f"\nTesting id={cmd_id}...", end=" ", flush=True)

    # Record windows before
    before = set(h for h,t,c,a in get_winols_wins(pids))

    # Post the WM_COMMAND
    user32.PostMessageW(main_win, WM_COMMAND, cmd_id, 0)
    time.sleep(0.8)

    # Check for new windows
    after = get_winols_wins(pids)
    new_wins = [(h,t,c,a) for h,t,c,a in after if h not in before and 1000 < a < 600000]

    if new_wins:
        for h,t,c,a in new_wins:
            print(f"NEW WINDOW: '{t}' cls={c!r} area={a}")
            if "config" in t.lower() or "option" in t.lower() or "konfig" in t.lower():
                print(f"*** CONFIGURATION DIALOG FOUND! id={cmd_id} ***")
            else:
                print(f"  (area={a}, title={t!r})")
        # Dismiss the new window
        for h,t,c,a in new_wins:
            dismiss_all(pids)
        time.sleep(0.5)
    else:
        print("no new window")

print("\nDone. Check output for *** CONFIGURATION DIALOG FOUND ***")
