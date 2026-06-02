"""config_navigate.py - Navigate Config TreeView with arrow keys until Hardware page appears"""
import ctypes, ctypes.wintypes as wt, subprocess, time, sys
sys.stdout.reconfigure(line_buffering=True)

user32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
LOG = r'C:\Users\Nates\AppData\Local\Temp\winols_wdapi.log'

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

def log_tail():
    try:
        h = k32.CreateFileW(LOG, 0x80000000, 7, None, 3, 0, None)
        sz = k32.GetFileSize(h, None)
        off = max(0, sz - 4000)
        k32.SetFilePointer(h, off, None, 0)
        buf = ctypes.create_string_buffer(4000); rd = wt.DWORD(0)
        k32.ReadFile(h, buf, 4000, ctypes.byref(rd), None); k32.CloseHandle(h)
        return buf.raw[:rd.value].decode('utf-8', 'replace')
    except: return ''

def phys_click(x, y):
    user32.SetCursorPos(x, y); time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.1)

pids = get_pids()
print(f'PIDs: {pids}')

# Find Config dialog (should already be open) or open it
config_dlg = None
for attempt in range(4):
    for h, t, c, a in get_wins(pids, vis=True, min_area=50000):
        if 'configuration' in t.lower() or 'konfiguration' in t.lower():
            config_dlg = h; print(f'Config: 0x{h:08X}'); break
    if config_dlg: break
    wins = get_wins(pids, vis=False, min_area=400000)
    if wins:
        user32.PostMessageW(wins[0][0], 0x0111, 32827, 0)
        time.sleep(2)

if not config_dlg: print('No Config!'); sys.exit(1)

# Find TreeView
tv = find_child(config_dlg, 'systreeview')
print(f'TV: 0x{tv:08X}' if tv else 'No TV')

def has_usb_ols300():
    """Check if USB OLS300 radio button is visible in the Config dialog."""
    for s in ['OLS300', 'USB']:
        r = find_child(config_dlg, 'button', s)
        if r and user32.IsWindowVisible(r):
            return r
    return None

# Navigate: bring Config to front, set focus on TreeView, use arrow keys
user32.SetForegroundWindow(config_dlg); time.sleep(0.3)
if tv:
    # Click on TreeView to give it focus
    tv_rect = wt.RECT(); user32.GetWindowRect(tv, ctypes.byref(tv_rect))
    phys_click((tv_rect.left + tv_rect.right)//2, tv_rect.top + 10)
    time.sleep(0.2)

    # Home = go to first item
    user32.PostMessageW(tv, 0x0100, 0x24, 0)  # VK_HOME
    time.sleep(0.3)

    # Check if USB OLS300 visible now (maybe Hardware is first item)
    r = has_usb_ols300()
    if r:
        print('Hardware page at first tree item!')
    else:
        # Navigate down through tree items until Hardware page appears
        found_hardware = False
        for step in range(20):
            user32.PostMessageW(tv, 0x0100, 0x27, 0)  # Right = expand
            time.sleep(0.1)
            user32.PostMessageW(tv, 0x0100, 0x28, 0)  # Down
            time.sleep(0.3)
            r = has_usb_ols300()
            if r:
                print(f'Hardware/Simulator page found at step {step+1}!')
                found_hardware = True
                break
            # Also try expanding and going down again
        if not found_hardware:
            print('Hardware page not found via navigation, trying End key...')
            user32.PostMessageW(tv, 0x0100, 0x23, 0)  # End
            time.sleep(0.3)
            r = has_usb_ols300()
            if r:
                print('Found via End key!')

# Click USB OLS300 radio button if found
r = has_usb_ols300()
if r:
    r_rect = wt.RECT(); user32.GetWindowRect(r, ctypes.byref(r_rect))
    rx = (r_rect.left + r_rect.right) // 2
    ry = (r_rect.top + r_rect.bottom) // 2
    print(f'Clicking USB OLS300 at ({rx},{ry})')
    phys_click(rx, ry)
    time.sleep(0.2)

# Click OK via physical click
ok_b = find_child(config_dlg, 'button', 'OK')
if ok_b:
    ok_rect = wt.RECT(); user32.GetWindowRect(ok_b, ctypes.byref(ok_rect))
    okx = (ok_rect.left + ok_rect.right) // 2
    oky = (ok_rect.top + ok_rect.bottom) // 2
    print(f'Clicking OK at ({okx},{oky})')
    user32.SetForegroundWindow(config_dlg); time.sleep(0.1)
    phys_click(okx, oky)
    time.sleep(0.5)
    print(f'Config: {"CLOSED!" if not (user32.IsWindow(config_dlg) and user32.IsWindowVisible(config_dlg)) else "still open"}')
else:
    print('No OK button!')

# Wait for second WDU_Init
print('Waiting for WDU_Init...')
for _ in range(16):
    time.sleep(0.5)
    lt = log_tail()
    if lt.count('WDU_Init') >= 2:
        print('Second WDU_Init detected!')
        break
else:
    print('No second WDU_Init')

# Check final state
wdu_count = log_tail().count('WDU_Init')
ep6_count = log_tail().count('WDU_Transfer ID pipe')
print(f'WDU_Init count: {wdu_count}, EP6 polls: {ep6_count}')
