"""click_ok_config.py - Find Config dialog and click OK"""
import ctypes, ctypes.wintypes as wt, subprocess, time

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
        area = (r2.right - r2.left) * (r2.bottom - r2.top)
        if area >= min_area: wins.append((h, tb.value, cl.value, area))
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

# Find config dialog or open it
config_dlg = None
for attempt in range(3):
    for h, t, c, a in get_wins(pids, vis=True, min_area=50000):
        if 'configuration' in t.lower() or 'konfiguration' in t.lower():
            config_dlg = h
            print(f'Found Config: 0x{h:08X}')
            break
    if config_dlg: break
    # Open Config dialog
    wins = get_wins(pids, vis=False, min_area=400000)
    if wins:
        print(f'Opening Config (attempt {attempt+1})...')
        user32.PostMessageW(wins[0][0], 0x0111, 32827, 0)
        time.sleep(2)

if not config_dlg:
    print('No Config dialog!'); exit(1)

# Navigate TreeView to select Hardware/Simulator
tv = find_child(config_dlg, 'systreeview')
if tv:
    print(f'TreeView: 0x{tv:08X} - pressing End key')
    user32.SetForegroundWindow(tv)
    time.sleep(0.3)
    # End = last tree item (should be near Simulator)
    user32.SendMessageW(tv, 0x0100, 0x23, 0x00010001)
    time.sleep(0.3)
    user32.SendMessageW(tv, 0x0101, 0x23, 0xC0010001)
    time.sleep(0.5)

# Try to click USB OLS300 radio
for s in ['OLS300', 'USB', 'Simulator']:
    r = find_child(config_dlg, 'button', s)
    if r:
        print(f'Clicking radio: {s!r}')
        user32.SetForegroundWindow(r); time.sleep(0.1)
        user32.SendMessageW(r, 0x00F5, 0, 0)
        time.sleep(0.2)
        break

# Click OK
ok_b = find_child(config_dlg, 'button', 'OK')
if ok_b:
    tb = ctypes.create_unicode_buffer(64)
    user32.GetWindowTextW(ok_b, tb, 64)
    print(f'OK button text: {tb.value!r}')
    if 'ok' in tb.value.lower() and len(tb.value.strip()) <= 3:
        user32.SetForegroundWindow(ok_b)
        time.sleep(0.2)
        user32.SendMessageW(ok_b, 0x00F5, 0, 0)
        print('Clicked OK!')
    else:
        # Direct BM_CLICK via coordinates - OK is always at bottom of dialog
        r2 = wt.RECT(); user32.GetWindowRect(ok_b, ctypes.byref(r2))
        cx = (r2.left + r2.right) // 2
        cy = (r2.top + r2.bottom) // 2
        print(f'Clicking OK at ({cx},{cy})')
        # Use PostMessage with WM_LBUTTONDOWN/UP
        import ctypes.wintypes
        lParam = (cy << 16) | (cx & 0xFFFF)
        user32.PostMessageW(ok_b, 0x0201, 1, lParam)
        time.sleep(0.05)
        user32.PostMessageW(ok_b, 0x0202, 0, lParam)
        print('Posted OK click!')
else:
    print('OK button not found!')
    # List all buttons
    def list_btns(parent):
        def cb(h, l):
            tb = ctypes.create_unicode_buffer(256); cl = ctypes.create_unicode_buffer(64)
            user32.GetWindowTextW(h, tb, 256); user32.GetClassNameW(h, cl, 64)
            if 'button' in cl.value.lower():
                print(f'  Button: 0x{h:08X} text={tb.value!r}')
            return True
        user32.EnumChildWindows(parent, WNDENUMPROC(cb), 0)
    list_btns(config_dlg)
