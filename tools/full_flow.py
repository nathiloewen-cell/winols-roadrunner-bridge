"""full_flow.py - Complete flow: dismiss → wait WDU_Init → Config immediately → OK → Load"""
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

def log_has(text): return text in log_tail()

def phys_click(x, y):
    user32.SetCursorPos(x, y); time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.1)

# Phase 1: Wait for WinOLS
print('Phase 1: Waiting for WinOLS...')
pids = []
for _ in range(20):
    time.sleep(0.5)
    pids = get_pids()
    if pids: break
if not pids: print('WinOLS not found!'); sys.exit(1)
print(f'PIDs: {pids}')

# Phase 2: Dismiss startup dialogs
print('Phase 2: Dismissing startup dialogs...')
DISMISS = ['Nein', 'No', "Don't", 'OK']
for _ in range(20):
    time.sleep(0.5)
    pids = get_pids()
    dismissed = False
    for h, t, c, a in get_wins(pids, vis=True, min_area=100):
        if a > 300000: continue
        for btxt in DISMISS:
            btn = find_child(h, 'button', btxt)
            if btn:
                print(f'  Dismiss {t!r} -> {btxt!r}')
                user32.SetForegroundWindow(btn); time.sleep(0.1)
                user32.SendMessageW(btn, 0x00F5, 0, 0)
                dismissed = True; time.sleep(0.4); break
        if dismissed: break
    if not dismissed:
        # Check if main window is visible (dialogs all dismissed)
        wins = get_wins(pids, vis=True, min_area=400000)
        if wins: break

time.sleep(1)

# Phase 3: Find main window
print('Phase 3: Finding main window...')
main_win = None
for _ in range(15):
    time.sleep(1)
    pids = get_pids()
    wins = get_wins(pids, vis=False, min_area=400000)
    if wins:
        main_win = wins[0][0]
        print(f'Main: 0x{main_win:08X} "{wins[0][1]}"')
        break
if not main_win: print('No main window!'); sys.exit(1)

# Phase 4: Send Config WM_COMMAND (this triggers WDU_Uninit)
print('Phase 4: Opening Config dialog (triggers WDU_Uninit)...')
user32.PostMessageW(main_win, 0x0111, 32827, 0)  # Config
time.sleep(1.5)

# Phase 5: Find Config dialog + navigate to Hardware/Simulator + click OK
print('Phase 5: Navigating Config dialog...')
config_dlg = None
for attempt in range(5):
    for h, t, c, a in get_wins(pids, vis=True, min_area=50000):
        if 'configuration' in t.lower() or 'konfiguration' in t.lower():
            config_dlg = h
            print(f'Config: 0x{h:08X}')
            break
    if config_dlg: break
    time.sleep(0.5)

if not config_dlg:
    print('Config not found!')
    sys.exit(1)

# Get Config + TreeView position
tv = find_child(config_dlg, 'systreeview')
if tv:
    tv_rect = wt.RECT(); user32.GetWindowRect(tv, ctypes.byref(tv_rect))
    print(f'TreeView: ({tv_rect.left},{tv_rect.top},{tv_rect.right},{tv_rect.bottom})')
    user32.SetForegroundWindow(config_dlg); time.sleep(0.3)
    # Click at y positions in the tree to find Hardware
    tv_cx = (tv_rect.left + tv_rect.right) // 2
    for y_off in [15, 35, 55, 75]:
        y = tv_rect.top + y_off
        phys_click(tv_cx, y)
        time.sleep(0.15)
    # Press Right arrow + Down + S for Simulator navigation
    user32.PostMessageW(tv, 0x0100, 0x27, 0)  # Right
    time.sleep(0.2)
    user32.PostMessageW(tv, 0x0100, 0x28, 0)  # Down
    time.sleep(0.2)
    user32.PostMessageW(tv, 0x0100, 0x28, 0)  # Down
    time.sleep(0.3)

# Click USB OLS300 radio (try various text patterns)
for s in ['OLS300', 'USB', 'Simulator']:
    r = find_child(config_dlg, 'button', s)
    if r:
        r_rect = wt.RECT(); user32.GetWindowRect(r, ctypes.byref(r_rect))
        rx = (r_rect.left + r_rect.right) // 2
        ry = (r_rect.top + r_rect.bottom) // 2
        print(f'Clicking radio {s!r} at ({rx},{ry})')
        phys_click(rx, ry)
        break

# Click OK via physical click (non-blocking)
ok_b = find_child(config_dlg, 'button', 'OK')
if ok_b:
    ok_rect = wt.RECT(); user32.GetWindowRect(ok_b, ctypes.byref(ok_rect))
    okx = (ok_rect.left + ok_rect.right) // 2
    oky = (ok_rect.top + ok_rect.bottom) // 2
    print(f'Clicking OK at ({okx},{oky})')
    user32.SetForegroundWindow(config_dlg); time.sleep(0.15)
    phys_click(okx, oky)
    time.sleep(0.5)
    still_open = user32.IsWindow(config_dlg) and user32.IsWindowVisible(config_dlg)
    print(f'Config: {"still open" if still_open else "CLOSED!"}')

# Phase 6: Wait for second WDU_Init + pfDeviceAttach
print('Phase 6: Waiting for second WDU_Init...')
for _ in range(20):
    time.sleep(0.5)
    if log_has('WDU_Transfer ID') and log_tail().count('WDU_Init') >= 2:
        print('Second WDU_Init + ID packet detected!')
        break
else:
    print('No second WDU_Init detected')

# Phase 7: Load with proper producer dialog handling
print('Phase 7: Sending Load (id=32807)...')
time.sleep(0.5)
pids = get_pids()
wins = get_wins(pids, vis=False, min_area=400000)
main_win2 = wins[0][0] if wins else main_win

user32.PostMessageW(main_win2, 0x0111, 32807, 0)

# Wait for Select producer dialog
print('Waiting for Select producer dialog...')
producer_dlg = None
for _ in range(20):
    time.sleep(0.3)
    for h, t, c, a in get_wins(get_pids(), vis=True, min_area=5000):
        if 5000 < a < 600000:
            if 'producer' in t.lower() or 'select' in t.lower():
                producer_dlg = h
                print(f'  Producer dialog: "{t}" 0x{h:08X}')
                break
            ok_b2 = find_child(h, 'button', 'OK')
            cancel_b2 = find_child(h, 'button', 'Cancel') or find_child(h, 'button', 'Abbrechen')
            if ok_b2 and cancel_b2 and a > 30000 and 'configuration' not in t.lower():
                producer_dlg = h
                print(f'  Producer dialog (fallback): "{t}" 0x{h:08X}')
                break
    if producer_dlg or log_has('TX (OLS300 cmd)'):
        break

if producer_dlg:
    # Handle producer dialog: find listbox, select 16-bit, click OK
    listbox = find_child(producer_dlg, 'listbox')
    if listbox:
        lb_count = user32.SendMessageW(listbox, 0x018B, 0, 0)  # LB_GETCOUNT
        print(f'  Listbox: {lb_count} items')
        selected = 0
        for idx in range(min(lb_count, 30)):
            buf = ctypes.create_unicode_buffer(100)
            user32.SendMessageW(listbox, 0x0189, idx, ctypes.cast(buf, ctypes.c_long))
            text = buf.value
            if text: print(f'    [{idx}] {text!r}')
            if '16' in text:
                selected = idx
                break
        user32.SendMessageW(listbox, 0x0186, selected, 0)  # LB_SETCURSEL
        print(f'  Selected item {selected}')
    # Click OK
    ok_b = find_child(producer_dlg, 'button', 'OK')
    if ok_b:
        user32.PostMessageW(ok_b, 0x00F5, 0, 0)
        user32.PostMessageW(producer_dlg, 0x0111, 1, 0)
        print('  OK posted')

# Wait for EP2 TX commands (extended: 120s for full protocol capture)
print('Waiting for EP2 TX (120s)...')
for _ in range(240):
    time.sleep(0.5)
    lt = log_tail()
    if 'TX (OLS300 cmd)' in lt and 'EP2 CAPTURED' not in locals():
        print('*** EP2 TX COMMANDS CAPTURED - continuing to monitor... ***')
        EP2_CAPTURED = True
    # Dismiss unexpected dialogs (but NOT producer dialog)
    for h, t, c, a in get_wins(get_pids(), vis=True, min_area=5000):
        if 5000 < a < 600000 and h != producer_dlg:
            ok_b3 = find_child(h, 'button', 'OK')
            if ok_b3: user32.PostMessageW(ok_b3, 0x00F5, 0, 0)

# Show final log
print('\nFinal log:')
for line in log_tail().splitlines()[-15:]:
    print(f'  {line}')
