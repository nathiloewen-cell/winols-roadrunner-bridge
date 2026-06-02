"""find_hardware_item.py - Find Hardware/Simulator tree item in Config dialog"""
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

def get_tv(config_dlg):
    found = [None]
    def cb(h, l):
        cl = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(h, cl, 64)
        if 'systreeview' in cl.value.lower():
            found[0] = h
        return True
    user32.EnumChildWindows(config_dlg, WNDENUMPROC(cb), 0)
    return found[0]

def has_usb_ols300(config_dlg):
    """Check if USB OLS300 button is visible (Hardware/Simulator page active)."""
    found = []
    def cb(h, l):
        cl = ctypes.create_unicode_buffer(64); tb = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, cl, 64); user32.GetWindowTextW(h, tb, 256)
        if 'button' in cl.value.lower() and user32.IsWindowVisible(h):
            t = tb.value.lower()
            if 'ols300' in t or 'ols 300' in t:
                found.append((h, tb.value))
        return True
    user32.EnumChildWindows(config_dlg, WNDENUMPROC(cb), 0)
    return found

def phys_click(x, y):
    user32.SetCursorPos(x, y); time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.1)

pids = get_pids()
print(f'PIDs: {pids}')

# Find Config dialog
config_dlg = None
for h, t, c, a in get_wins(pids, vis=True, min_area=50000):
    if 'configuration' in t.lower() or 'konfiguration' in t.lower():
        config_dlg = h
        print(f'Config: 0x{h:08X}')
        break

if not config_dlg:
    print('No Config dialog - opening...')
    wins = get_wins(pids, vis=False, min_area=400000)
    if wins:
        user32.PostMessageW(wins[0][0], 0x0111, 32827, 0)
        time.sleep(2)
        for h, t, c, a in get_wins(pids, vis=True, min_area=50000):
            if 'configuration' in t.lower():
                config_dlg = h
                print(f'Opened: 0x{h:08X}')
                break

if not config_dlg:
    print('Cannot open Config!'); sys.exit(1)

tv = get_tv(config_dlg)
print(f'TreeView: 0x{tv:08X}' if tv else 'No TreeView')
if not tv: sys.exit(1)

# TVM constants
TVGN_ROOT    = 0
TVGN_CHILD   = 4
TVGN_NEXT    = 1
TVGN_CARET   = 9  # for TVM_SELECTITEM
TVM_GETNEXTITEM = 0x110A
TVM_SELECTITEM  = 0x110B
TVM_EXPAND      = 0x1102
TVE_EXPAND      = 2

def get_items(start, direction):
    """Get list of tree items starting from 'start' following 'direction'."""
    items = []
    cur = user32.SendMessageW(tv, TVM_GETNEXTITEM, direction, start)
    while cur:
        items.append(cur)
        cur = user32.SendMessageW(tv, TVM_GETNEXTITEM, TVGN_NEXT, cur)
    return items

def select_and_check(hitem):
    user32.SendMessageW(tv, TVM_SELECTITEM, TVGN_CARET, hitem)
    time.sleep(0.3)
    return has_usb_ols300(config_dlg)

# Get all root items
root = user32.SendMessageW(tv, TVM_GETNEXTITEM, TVGN_ROOT, 0)
print(f'Root item: {root}')

roots = [root]
cur = root
while True:
    nxt = user32.SendMessageW(tv, TVM_GETNEXTITEM, TVGN_NEXT, cur)
    if not nxt: break
    roots.append(nxt)
    cur = nxt
print(f'Root items: {len(roots)} items')

hardware_hitem = None

# Try each root item and its children
for ri, item in enumerate(roots):
    f = select_and_check(item)
    print(f'Root[{ri}] item={item}: {"OLS300 VISIBLE! " + str([x[1] for x in f]) if f else "no match"}')
    if f:
        hardware_hitem = item
        break

    # Expand this root item and check children
    user32.SendMessageW(tv, TVM_EXPAND, TVE_EXPAND, item)
    time.sleep(0.1)
    child = user32.SendMessageW(tv, TVM_GETNEXTITEM, TVGN_CHILD, item)
    ci = 0
    while child and not hardware_hitem:
        f = select_and_check(child)
        print(f'  Child[{ci}] item={child}: {"OLS300! " + str([x[1] for x in f]) if f else "no"}')
        if f:
            hardware_hitem = child
            break
        next_child = user32.SendMessageW(tv, TVM_GETNEXTITEM, TVGN_NEXT, child)
        child = next_child
        ci += 1

    if hardware_hitem:
        break

if hardware_hitem:
    print(f'\nHardware/Simulator page found! hItem={hardware_hitem}')
    # Click USB OLS300 radio button
    f = has_usb_ols300(config_dlg)
    for rh, rt in f:
        r2 = wt.RECT(); user32.GetWindowRect(rh, ctypes.byref(r2))
        rx = (r2.left + r2.right) // 2
        ry = (r2.top + r2.bottom) // 2
        print(f'Clicking USB OLS300 "{rt}" at ({rx},{ry})')
        phys_click(rx, ry)
        break

    # Click OK
    from ctypes import wintypes as wtypes
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

    ok_b = find_child(config_dlg, 'button', 'OK')
    if ok_b:
        r2 = wt.RECT(); user32.GetWindowRect(ok_b, ctypes.byref(r2))
        okx = (r2.left + r2.right) // 2
        oky = (r2.top + r2.bottom) // 2
        print(f'Clicking OK at ({okx},{oky})')
        user32.SetForegroundWindow(config_dlg); time.sleep(0.2)
        phys_click(okx, oky)
        time.sleep(0.5)
        closed = not (user32.IsWindow(config_dlg) and user32.IsWindowVisible(config_dlg))
        print(f'Config: {"CLOSED!" if closed else "still open"}')
else:
    print('\nHardware/Simulator page NOT found in Config tree')
    print('Listing all visible buttons:')
    def list_buttons(parent):
        found = []
        def cb(h, l):
            cl = ctypes.create_unicode_buffer(64); tb = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(h, cl, 64); user32.GetWindowTextW(h, tb, 256)
            if 'button' in cl.value.lower() and user32.IsWindowVisible(h) and tb.value.strip():
                found.append(tb.value)
            return True
        user32.EnumChildWindows(parent, WNDENUMPROC(cb), 0)
        return found
    for b in list_buttons(config_dlg): print(f'  {b!r}')
