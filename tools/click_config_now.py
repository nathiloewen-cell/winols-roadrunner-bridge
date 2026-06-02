"""click_config_now.py - Click OK on currently-open Config dialog"""
import ctypes, ctypes.wintypes as wt, time, struct, subprocess

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

# Find existing Config dialog (don't open a new one)
config_dlg = None
for h, t, c, a in get_wins(pids, vis=True, min_area=50000):
    if 'configuration' in t.lower() or 'konfiguration' in t.lower():
        config_dlg = h
        print(f'Config: 0x{h:08X} "{t}"')
        break

if not config_dlg:
    # Open it
    print('Config not open, opening...')
    wins = get_wins(pids, vis=False, min_area=400000)
    main_win = wins[0][0] if wins else None
    if main_win:
        user32.PostMessageW(main_win, 0x0111, 32827, 0)
        time.sleep(2)
        for h, t, c, a in get_wins(pids, vis=True, min_area=50000):
            if 'configuration' in t.lower():
                config_dlg = h
                print(f'Config opened: 0x{h:08X}')
                break

if not config_dlg:
    print('Cannot find Config dialog!'); exit(1)

# Find TreeView and navigate to Simulator
tv = find_child(config_dlg, 'systreeview')
print(f'TreeView: 0x{tv:08X}' if tv else 'No TreeView')

if tv:
    pid_val = wt.DWORD(0); user32.GetWindowThreadProcessId(tv, ctypes.byref(pid_val))
    hproc = k32.OpenProcess(0x001F0FFF, False, pid_val.value)
    BUF_SIZE = 640
    remote = k32.VirtualAllocEx(hproc, None, BUF_SIZE, 0x1000, 0x04)
    remote_txt = remote + 64
    found_h = [0]

    def walk(hitem, depth=0):
        if not hitem or depth > 20: return False
        local = struct.pack('<IIIIII', 0x11, hitem & 0xFFFFFFFF, 0, 0, remote_txt & 0xFFFFFFFF, 256)
        local += b'\x00' * (64 - len(local))
        wr = ctypes.c_size_t(0)
        k32.WriteProcessMemory(hproc, remote, ctypes.create_string_buffer(local), 64, ctypes.byref(wr))
        user32.SendMessageW(tv, 0x100C, 0, remote)
        rbuf = ctypes.create_string_buffer(512); rd = ctypes.c_size_t(0)
        k32.ReadProcessMemory(hproc, remote_txt, rbuf, 512, ctypes.byref(rd))
        try: txt = rbuf.raw[:rd.value].decode('utf-16-le').rstrip('\x00')
        except: txt = ''
        if txt: print('  ' * depth + repr(txt))
        if 'simulator' in txt.lower():
            found_h[0] = hitem; return True
        child = user32.SendMessageW(tv, 0x110A, 4, hitem)
        if child and walk(child, depth + 1): return True
        sib = user32.SendMessageW(tv, 0x110A, 1, hitem)
        if sib and walk(sib, depth): return True
        return False

    root = user32.SendMessageW(tv, 0x110A, 0, 0)
    print(f'Walking tree from root={root}...')
    walk(root)
    k32.VirtualFreeEx(hproc, remote, 0, 0x8000); k32.CloseHandle(hproc)

    if found_h[0]:
        user32.SendMessageW(tv, 0x110B, 9, found_h[0])
        time.sleep(0.5)
        print(f'Simulator selected (hItem={found_h[0]})')
    else:
        print('Simulator not found, using End key fallback')
        user32.SetForegroundWindow(tv); time.sleep(0.2)
        user32.SendMessageW(tv, 0x0100, 0x23, 0x00010001)
        time.sleep(0.4)

# Click USB OLS300 radio button
for s in ['OLS300', 'USB']:
    r = find_child(config_dlg, 'button', s)
    if r:
        print(f'Clicking {s!r} radio')
        user32.SetForegroundWindow(r); time.sleep(0.15)
        user32.SendMessageW(r, 0x00F5, 0, 0)
        time.sleep(0.3)
        break

# Click OK
ok_b = find_child(config_dlg, 'button', 'OK')
if ok_b:
    tb = ctypes.create_unicode_buffer(64)
    user32.GetWindowTextW(ok_b, tb, 64)
    if tb.value.strip().upper() == 'OK':
        print('Clicking OK...')
        user32.SetForegroundWindow(ok_b); time.sleep(0.15)
        user32.SendMessageW(ok_b, 0x00F5, 0, 0)
        print('Config OK clicked!')
    else:
        print(f'Wrong button text: {tb.value!r}')
else:
    print('OK button not found!')
