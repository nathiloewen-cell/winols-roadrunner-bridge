"""nav_and_ok.py - Navigate Config TreeView to Simulator and click OK"""
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

# Find or open Config dialog
config_dlg = None
for h, t, c, a in get_wins(pids, vis=True, min_area=50000):
    if 'configuration' in t.lower() or 'konfiguration' in t.lower():
        config_dlg = h
        print(f'Found Config: 0x{h:08X}')
        break

if not config_dlg:
    wins = get_wins(pids, vis=False, min_area=400000)
    if wins:
        print('Opening Config...')
        user32.PostMessageW(wins[0][0], 0x0111, 32827, 0)
        time.sleep(2)
        for h, t, c, a in get_wins(pids, vis=True, min_area=50000):
            if 'configuration' in t.lower():
                config_dlg = h
                print(f'Config opened: 0x{h:08X}')
                break

if not config_dlg:
    print('No Config dialog!')
    exit(1)

# Find TreeView
tv = find_child(config_dlg, 'systreeview')
print(f'TreeView: 0x{tv:08X}' if tv else 'No TreeView')

if tv:
    # Set focus to TreeView
    user32.SetForegroundWindow(config_dlg)
    time.sleep(0.2)
    user32.SetFocus(tv)
    time.sleep(0.2)

    # Navigate with keyboard
    # Home = go to first tree item (usually "Hardware" or similar)
    user32.SendMessageW(tv, 0x0100, 0x24, 0x00600001)  # WM_KEYDOWN Home
    user32.SendMessageW(tv, 0x0101, 0x24, 0xC0600001)  # WM_KEYUP Home
    time.sleep(0.2)

    # Send 'H' to jump to Hardware
    user32.SendMessageW(tv, 0x0102, ord('H'), 0)  # WM_CHAR
    time.sleep(0.3)

    # Send Right arrow to expand Hardware subtree
    user32.SendMessageW(tv, 0x0100, 0x27, 0x014D0001)  # WM_KEYDOWN RIGHT
    user32.SendMessageW(tv, 0x0101, 0x27, 0xC14D0001)  # WM_KEYUP RIGHT
    time.sleep(0.3)

    # Send Down arrow once to get into Hardware children
    user32.SendMessageW(tv, 0x0100, 0x28, 0x00510001)  # WM_KEYDOWN DOWN
    user32.SendMessageW(tv, 0x0101, 0x28, 0xC0510001)  # WM_KEYUP DOWN
    time.sleep(0.2)

    # Send 'S' to jump to Simulator
    user32.SendMessageW(tv, 0x0102, ord('S'), 0)  # WM_CHAR
    time.sleep(0.5)
    print('TreeView navigation done')

# Try to click USB OLS300 radio button
for s in ['OLS300', 'USB']:
    r = find_child(config_dlg, 'button', s)
    if r:
        print(f'Clicking radio: {s!r}')
        user32.SetForegroundWindow(r)
        time.sleep(0.1)
        user32.SendMessageW(r, 0x00F5, 0, 0)
        time.sleep(0.3)
        break

# Find and click OK button
ok_b = find_child(config_dlg, 'button', 'OK')
if ok_b:
    tb = ctypes.create_unicode_buffer(64)
    user32.GetWindowTextW(ok_b, tb, 64)
    print(f'OK button: {tb.value!r}')
    user32.SetForegroundWindow(config_dlg)
    time.sleep(0.1)
    user32.SetForegroundWindow(ok_b)
    time.sleep(0.15)
    user32.SendMessageW(ok_b, 0x00F5, 0, 0)
    print('OK clicked!')
else:
    print('OK button NOT found!')
    # Try EnterKey on config dialog
    user32.SetForegroundWindow(config_dlg)
    time.sleep(0.1)
    user32.SendMessageW(config_dlg, 0x0100, 0x0D, 0)  # Enter key
    print('Enter key sent')
