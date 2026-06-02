"""find_load_id.py - Try each Hardware submenu ID to find Load command"""
import ctypes, ctypes.wintypes as wt, subprocess, time, sys
sys.stdout.reconfigure(line_buffering=True)

user32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32
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

def get_main():
    pids = get_pids()
    wins = []
    def cb(h, l):
        p = wt.DWORD(0); user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value not in pids: return True
        r2 = wt.RECT(); user32.GetWindowRect(h, ctypes.byref(r2))
        a = (r2.right - r2.left) * (r2.bottom - r2.top)
        if a > 400000: wins.append((h, a))
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    wins.sort(key=lambda x: x[1], reverse=True)
    return wins[0][0] if wins else None, pids

def log_has_ep2():
    try:
        h = k32.CreateFileW(
            r'C:\Users\Nates\AppData\Local\Temp\winols_wdapi.log',
            0x80000000, 7, None, 3, 0, None)
        sz = k32.GetFileSize(h, None)
        off = max(0, sz - 3000)
        k32.SetFilePointer(h, off, None, 0)
        buf = ctypes.create_string_buffer(3000)
        rd = wt.DWORD(0)
        k32.ReadFile(h, buf, 3000, ctypes.byref(rd), None)
        k32.CloseHandle(h)
        return b'TX (OLS300 cmd)' in buf.raw[:rd.value]
    except:
        return False

def get_dialogs(pids):
    wins = []
    def cb(h, l):
        p = wt.DWORD(0); user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value not in pids: return True
        if not user32.IsWindowVisible(h): return True
        tb = ctypes.create_unicode_buffer(256); user32.GetWindowTextW(h, tb, 256)
        r2 = wt.RECT(); user32.GetWindowRect(h, ctypes.byref(r2))
        a = (r2.right - r2.left) * (r2.bottom - r2.top)
        if 5000 < a < 600000: wins.append((h, tb.value, a))
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return sorted(wins, key=lambda x: x[2], reverse=True)

def dismiss_dialog(h):
    found = [None]
    def cb(ch, l):
        tb = ctypes.create_unicode_buffer(256); cl = ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(ch, tb, 256); user32.GetClassNameW(ch, cl, 64)
        if 'button' in cl.value.lower() and 'ok' in tb.value.lower():
            found[0] = ch
        return True
    user32.EnumChildWindows(h, WNDENUMPROC(cb), 0)
    if found[0]:
        user32.PostMessageW(found[0], 0x00F5, 0, 0)
        return True
    return False

main_win, pids = get_main()
print(f'Main: 0x{main_win:08X}')

# Candidates: all items found in Hardware submenus
# From menu scan: Hardware[3][0]=33200, Hardware[4][0]=33746,
# Hardware[5][0]=32800, Hardware[6][0]=32807
# Also Hardware direct items: 32891, 32896
candidates = [32891, 32896, 33200, 33746, 32800, 32807, 32808]

for cmd_id in candidates:
    print(f'\nTrying WM_COMMAND id={cmd_id}...')
    user32.PostMessageW(main_win, 0x0111, cmd_id, 0)

    for wait in range(6):
        time.sleep(0.5)
        if log_has_ep2():
            print(f'  *** EP2 TX FOUND! id={cmd_id} = Load! ***')
            sys.exit(0)
        dlgs = get_dialogs(pids)
        if dlgs:
            print(f'  Dialog: {[(hex(h), t[:30], a) for h,t,a in dlgs]}')
            # This might be the producer dialog - dismiss it
            for h, t, a in dlgs:
                dismiss_dialog(h)
            time.sleep(0.3)
            if log_has_ep2():
                print(f'  *** EP2 TX FOUND after dialog dismiss! id={cmd_id} = Load! ***')
                sys.exit(0)
            break
    else:
        print(f'  No reaction to id={cmd_id}')

print('\nLoad ID not found among tested candidates')
