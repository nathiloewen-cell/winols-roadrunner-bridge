"""do_load.py - Send Load command and handle Select producer dialog properly"""
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
        off = max(0, sz - 5000)
        k32.SetFilePointer(h, off, None, 0)
        buf = ctypes.create_string_buffer(5000); rd = wt.DWORD(0)
        k32.ReadFile(h, buf, 5000, ctypes.byref(rd), None); k32.CloseHandle(h)
        return buf.raw[:rd.value].decode('utf-8', 'replace')
    except: return ''

pids = get_pids()
print(f'PIDs: {pids}')

wins = get_wins(pids, vis=False, min_area=400000)
main_win = wins[0][0] if wins else None
print(f'Main: 0x{main_win:08X}')

# Send Load (id=32807)
print('Sending Load command (id=32807)...')
user32.PostMessageW(main_win, 0x0111, 32807, 0)

# Watch for Select producer dialog (up to 5 seconds)
producer_dlg = None
print('Waiting for Select producer dialog...')
for i in range(20):
    time.sleep(0.3)
    # Check for any non-main dialog
    pids2 = get_pids()
    for h, t, c, a in get_wins(pids2, vis=True, min_area=5000):
        if 5000 < a < 600000:
            print(f'  Dialog: 0x{h:08X} "{t}" area={a}')
            if 'producer' in t.lower() or 'select' in t.lower() or 'chip' in t.lower():
                producer_dlg = h
                break
            # Also match any dialog with listbox + OK/Cancel
            ok_b = find_child(h, 'button', 'OK')
            cancel_b = find_child(h, 'button', 'Cancel') or find_child(h, 'button', 'Abbrechen')
            if ok_b and cancel_b and a > 30000:
                producer_dlg = h
                print(f'  -> Producer dialog candidate!')
                break
    if producer_dlg:
        break
    # Also check for EP2 commands (Load already sent data without dialog)
    if 'TX (OLS300 cmd)' in log_tail():
        print('EP2 TX already captured!')
        break

if producer_dlg:
    print(f'Producer dialog: 0x{producer_dlg:08X}')

    # Find listbox and select first item (16 Bit EPROM type)
    listbox = find_child(producer_dlg, 'listbox')
    if listbox:
        lb_count = user32.SendMessageW(listbox, 0x018B, 0, 0)  # LB_GETCOUNT
        print(f'  Listbox items: {lb_count}')
        # Read all items and find "16 Bit" or first item
        selected_idx = 0
        for idx in range(min(lb_count, 20)):
            buf = ctypes.create_unicode_buffer(100)
            user32.SendMessageW(listbox, 0x0189, idx, ctypes.cast(buf, ctypes.c_long))
            item_text = buf.value
            print(f'  Item[{idx}]: {item_text!r}')
            if '16' in item_text:
                selected_idx = idx
                break
        # Select the item
        user32.SendMessageW(listbox, 0x0186, selected_idx, 0)  # LB_SETCURSEL
        print(f'  Selected item {selected_idx}')
        time.sleep(0.1)
    else:
        print('  No listbox found in producer dialog')
        # List all children
        def list_children(parent):
            children = []
            def cb(h, l):
                tb = ctypes.create_unicode_buffer(256); cl = ctypes.create_unicode_buffer(64)
                user32.GetWindowTextW(h, tb, 256); user32.GetClassNameW(h, cl, 64)
                children.append((h, cl.value, tb.value))
                return True
            user32.EnumChildWindows(parent, WNDENUMPROC(cb), 0)
            return children
        for h, c, t in list_children(producer_dlg):
            print(f'  Child: {c} "{t[:40]}"')

    # Click OK
    ok_b = find_child(producer_dlg, 'button', 'OK')
    if ok_b:
        print('  Clicking OK...')
        user32.PostMessageW(ok_b, 0x00F5, 0, 0)  # BM_CLICK (non-blocking)
        time.sleep(0.2)
        user32.PostMessageW(producer_dlg, 0x0111, 1, 0)  # WM_COMMAND IDOK
        print('  OK posted')
    else:
        # Try Enter key
        user32.PostMessageW(producer_dlg, 0x0100, 0x0D, 0)  # Enter
        print('  Enter sent')

# Wait for EP2 TX commands (up to 10 seconds)
print('Waiting for EP2 TX commands...')
for i in range(20):
    time.sleep(0.5)
    lt = log_tail()
    if 'TX (OLS300 cmd)' in lt:
        print('*** EP2 TX COMMANDS CAPTURED! ***')
        for line in lt.splitlines():
            if 'TX' in line or '0000:' in line or '0010:' in line:
                print(f'  {line}')
        sys.exit(0)
    # Dismiss any new dialogs
    for h, t, c, a in get_wins(pids, vis=True, min_area=5000):
        if 5000 < a < 600000 and h != producer_dlg:
            ok_b2 = find_child(h, 'button', 'OK')
            if ok_b2:
                print(f'  Dismissing new dialog "{t}"')
                user32.PostMessageW(ok_b2, 0x00F5, 0, 0)

print('No EP2 TX captured')
print('\nLog tail:')
for line in log_tail().splitlines()[-10:]: print(f'  {line}')
