"""inspect_producer.py - Inspect the Select producer dialog structure"""
import ctypes, ctypes.wintypes as wt, subprocess, time, sys, os
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

def log_tail():
    try:
        h = k32.CreateFileW(LOG, 0x80000000, 7, None, 3, 0, None)
        sz = k32.GetFileSize(h, None)
        off = max(0, sz - 3000)
        k32.SetFilePointer(h, off, None, 0)
        buf = ctypes.create_string_buffer(3000); rd = wt.DWORD(0)
        k32.ReadFile(h, buf, 3000, ctypes.byref(rd), None); k32.CloseHandle(h)
        return buf.raw[:rd.value].decode('utf-8', 'replace')
    except: return ''

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

# Find main window
wins = get_wins(pids, vis=False, min_area=400000)
main_win = wins[0][0] if wins else None
print(f'Main: 0x{main_win:08X}')

# Send Load directly (assumes WinOLS already has 2nd WDU_Init done from previous run)
print('Sending Load 32807...')
user32.PostMessageW(main_win, 0x0111, 32807, 0)
time.sleep(2)

# Find and inspect any dialog
print('Looking for producer dialog...')
for h, t, c, a in get_wins(pids, vis=True, min_area=5000):
    if 5000 < a < 600000:
        print(f'\nDialog: 0x{h:08X} "{t}" area={a}')
        print('Children:')
        def cb_list(ch, l):
            tb = ctypes.create_unicode_buffer(256); cl = ctypes.create_unicode_buffer(64)
            user32.GetWindowTextW(ch, tb, 256); user32.GetClassNameW(ch, cl, 64)
            vis = user32.IsWindowVisible(ch)
            r2 = wt.RECT(); user32.GetWindowRect(ch, ctypes.byref(r2))
            a2 = (r2.right - r2.left) * (r2.bottom - r2.top)
            text_str = tb.value[:60]
            print(f'  [{cl.value}] vis={vis} a={a2} text={text_str!r}')
            return True
        user32.EnumChildWindows(h, WNDENUMPROC(cb_list), 0)
