"""post_ok.py - PostMessage BM_CLICK to OK button (non-blocking, avoids deadlock)"""
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

# Find Config dialog or open it
config_dlg = None
for attempt in range(4):
    for h, t, c, a in get_wins(pids, vis=True, min_area=50000):
        if 'configuration' in t.lower() or 'konfiguration' in t.lower():
            config_dlg = h
            print(f'Config: 0x{h:08X}')
            break
    if config_dlg: break
    if attempt == 0:
        wins = get_wins(pids, vis=False, min_area=400000)
        if wins:
            print(f'Opening Config...')
            user32.PostMessageW(wins[0][0], 0x0111, 32827, 0)
            time.sleep(2)

if not config_dlg:
    print('Cannot find Config!'); exit(1)

# Find OK button
ok_b = find_child(config_dlg, 'button', 'OK')
if not ok_b:
    print('No OK button!'); exit(1)

tb = ctypes.create_unicode_buffer(64)
user32.GetWindowTextW(ok_b, tb, 64)
print(f'OK button: 0x{ok_b:08X} text={tb.value!r}')

# Get button control ID
ctrl_id = user32.GetDlgCtrlID(ok_b)
print(f'Control ID: {ctrl_id}')

# PostMessage BM_CLICK (0x00F5) to OK button - non-blocking
user32.PostMessageW(ok_b, 0x00F5, 0, 0)
print('PostMessage BM_CLICK sent (non-blocking)')

# Also post WM_COMMAND IDOK to dialog
time.sleep(0.1)
user32.PostMessageW(config_dlg, 0x0111, ctrl_id if ctrl_id > 0 else 1, ok_b)
print(f'PostMessage WM_COMMAND id={ctrl_id} sent')

# Wait and check if dialog closed
for i in range(10):
    time.sleep(0.3)
    still_open = user32.IsWindow(config_dlg) and user32.IsWindowVisible(config_dlg)
    print(f't={0.3*(i+1):.1f}s: Config dialog {"still open" if still_open else "CLOSED!"}')
    if not still_open:
        break

print('Done')
