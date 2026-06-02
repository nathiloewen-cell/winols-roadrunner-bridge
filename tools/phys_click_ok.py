"""phys_click_ok.py - Physical mouse click on Config OK button"""
import ctypes, ctypes.wintypes as wt, subprocess, time, sys
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

def get_wins(pids, vis=True, min_area=0):
    wins = []
    def cb(h, l):
        p = wt.DWORD(0); user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value not in pids: return True
        if vis and not user32.IsWindowVisible(h): return True
        tb = ctypes.create_unicode_buffer(256); cl = ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(h, tb, 256); user32.GetClassNameW(h, cl, 64)
        r2 = wt.RECT(); user32.GetWindowRect(h, ctypes.byref(r2))
        a = (r2.right - r2.left) * (r2.bottom - r2.top)
        if a >= min_area: wins.append((h, tb.value, cl.value, a))
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return sorted(wins, key=lambda x: x[3], reverse=True)

def find_child(parent, cls_f=None, txt_f=None):
    found = [None]
    def cb(h, l):
        tb = ctypes.create_unicode_buffer(256); cl = ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(h, tb, 256); user32.GetClassNameW(h, cl, 64)
        ok = True
        if cls_f and cls_f.lower() not in cl.value.lower(): ok = False
        if txt_f and txt_f.lower() not in tb.value.lower(): ok = False
        if ok: found[0] = h
        return True
    user32.EnumChildWindows(parent, WNDENUMPROC(cb), 0)
    return found[0]

pids = get_pids()
print(f'PIDs: {pids}')

# Find Config dialog
config_dlg = None
for h, t, c, a in get_wins(pids, vis=True, min_area=50000):
    if 'configuration' in t.lower() or 'konfiguration' in t.lower():
        config_dlg = h
        print(f'Config: 0x{h:08X}')
        break

if not config_dlg:
    print('No Config dialog open - opening...')
    wins = get_wins(pids, vis=False, min_area=400000)
    if wins:
        user32.PostMessageW(wins[0][0], 0x0111, 32827, 0)
        time.sleep(2)
        for h, t, c, a in get_wins(pids, vis=True, min_area=50000):
            if 'configuration' in t.lower():
                config_dlg = h
                print(f'Config opened: 0x{h:08X}')
                break

if not config_dlg:
    print('Cannot open Config!')
    exit(1)

# Find OK button rect
ok_b = find_child(config_dlg, 'button', 'OK')
if ok_b:
    r2 = wt.RECT()
    user32.GetWindowRect(ok_b, ctypes.byref(r2))
    cx = (r2.left + r2.right) // 2
    cy = (r2.top + r2.bottom) // 2
    print(f'OK button at screen ({cx},{cy})')

    # Bring dialog to front
    user32.SetForegroundWindow(config_dlg)
    time.sleep(0.3)

    # Physical mouse click using SetCursorPos + mouse_event
    user32.SetCursorPos(cx, cy)
    time.sleep(0.1)
    # mouse_event: MOUSEEVENTF_LEFTDOWN=0x0002, MOUSEEVENTF_LEFTUP=0x0004
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # Left down
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # Left up
    print('Physical click sent!')
else:
    print('OK button not found! Listing all buttons:')
    def list_btns(parent):
        def cb(h, l):
            tb = ctypes.create_unicode_buffer(256); cl = ctypes.create_unicode_buffer(64)
            user32.GetWindowTextW(h, tb, 256); user32.GetClassNameW(h, cl, 64)
            if 'button' in cl.value.lower():
                r2 = wt.RECT(); user32.GetWindowRect(h, ctypes.byref(r2))
                vis = user32.IsWindowVisible(h)
                print(f'  [{cl.value}] "{tb.value}" vis={vis} rect=({r2.left},{r2.top},{r2.right},{r2.bottom})')
            return True
        user32.EnumChildWindows(parent, WNDENUMPROC(cb), 0)
    list_btns(config_dlg)
