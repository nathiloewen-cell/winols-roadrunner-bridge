"""test_load_ids.py - Run phases 1-6 then test specific IDs for OLS300 Load"""
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

# Phase 1-2: Dismiss dialogs
print('Dismissing dialogs...')
pids = get_pids()
if not pids: print('No WinOLS!'); sys.exit(1)
DISMISS = ['Nein', 'No', "Don't", 'OK']
for _ in range(20):
    time.sleep(0.5)
    pids = get_pids()
    for h, t, c, a in get_wins(pids, vis=True, min_area=100):
        if a > 300000: continue
        for btxt in DISMISS:
            btn = find_child(h, 'button', btxt)
            if btn:
                print(f'  Dismiss {t!r}')
                user32.PostMessageW(btn, 0x00F5, 0, 0); time.sleep(0.3); break

# Phase 3: Find main window
wins = None
for _ in range(15):
    time.sleep(1)
    pids = get_pids()
    wins = get_wins(pids, vis=False, min_area=400000)
    if wins: break
main_win = wins[0][0] if wins else None
print(f'Main: 0x{main_win:08X}')

# Phase 4-5: Config OK
print('Sending Config WM_COMMAND...')
user32.PostMessageW(main_win, 0x0111, 32827, 0)
time.sleep(1.5)
config_dlg = None
for h, t, c, a in get_wins(pids, vis=True, min_area=50000):
    if 'configuration' in t.lower():
        config_dlg = h; print(f'Config: 0x{h:08X}'); break
if config_dlg:
    ok_b = find_child(config_dlg, 'button', 'OK')
    if ok_b:
        r2 = wt.RECT(); user32.GetWindowRect(ok_b, ctypes.byref(r2))
        okx = (r2.left + r2.right) // 2; oky = (r2.top + r2.bottom) // 2
        user32.SetForegroundWindow(config_dlg); time.sleep(0.15)
        phys_click(okx, oky)
        print(f'Config OK clicked at ({okx},{oky})')

# Phase 6: Wait for ID packets
print('Waiting for ID packets...')
for _ in range(20):
    time.sleep(0.5)
    if 'WDU_Transfer ID' in log_tail():
        print('ID packet detected!')
        break

# Phase 7: Test candidate Load IDs (including direct Hardware items)
print('\nTesting candidate Load IDs...')
pids = get_pids()
wins = get_wins(pids, vis=False, min_area=400000)
mw = wins[0][0] if wins else main_win

# Test IDs that might be OLS300-specific Load
# 32891, 32896 = direct Hardware menu items (possibly Load/Disconnect for current hw)
# Also test second items of submenus
candidate_ids = [32891, 32896, 33198, 33747, 32799, 32801, 1545, 33150, 33097, 33098, 33130, 33131]

for cmd_id in candidate_ids:
    print(f'\nTrying id={cmd_id}...')
    user32.PostMessageW(mw, 0x0111, cmd_id, 0)

    for _ in range(6):
        time.sleep(0.5)
        if 'TX (OLS300 cmd)' in log_tail():
            print(f'*** EP2 TX CAPTURED! id={cmd_id} = OLS300 Load! ***')
            lt = log_tail()
            for line in lt.splitlines():
                if 'TX' in line or ('0' in line and ':' in line and len(line) > 15):
                    print(f'  {line}')
            sys.exit(0)
        # Check for dialogs
        dlgs = [(h, t, a) for h, t, c, a in get_wins(pids, vis=True, min_area=5000) if 5000 < a < 600000]
        if dlgs:
            dnames = [t[:25] for h, t, a in dlgs]
            if 'Select producer' not in dnames:  # Not Batronix
                print(f'  Non-Batronix dialog: {dnames}')
            for h, t, a in dlgs:
                ok_b = find_child(h, 'button', 'OK')
                if ok_b: user32.PostMessageW(ok_b, 0x00F5, 0, 0)
            break

    if 'TX (OLS300 cmd)' in log_tail():
        print(f'*** EP2 TX from id={cmd_id}! ***')
        break
    print(f'  No EP2 from id={cmd_id}')

print('\nAll candidates tested. Log tail:')
for line in log_tail().splitlines()[-10:]: print(f'  {line}')
