"""handle_producer.py - Handle Select producer dialog with SysListView32"""
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

def find_children_cls(parent, cls_f):
    found = []
    def cb(h, l):
        cl = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(h, cl, 64)
        if cls_f.lower() in cl.value.lower():
            found.append(h)
        return True
    user32.EnumChildWindows(parent, WNDENUMPROC(cb), 0)
    return found

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

def phys_dblclick(x, y):
    user32.SetCursorPos(x, y); time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0); time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0); time.sleep(0.08)
    user32.mouse_event(0x0002, 0, 0, 0, 0); time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0); time.sleep(0.1)

pids = get_pids()
print(f'PIDs: {pids}')

# Find producer dialog
producer_dlg = None
for h, t, c, a in get_wins(pids, vis=True, min_area=5000):
    if 5000 < a < 600000 and ('producer' in t.lower() or 'select' in t.lower()):
        producer_dlg = h
        print(f'Producer dialog: 0x{h:08X} "{t}"')
        break

if not producer_dlg:
    # Need to send Load first
    wins = get_wins(pids, vis=False, min_area=400000)
    main_win = wins[0][0] if wins else None
    print(f'Sending Load 32807 to 0x{main_win:08X}')
    user32.PostMessageW(main_win, 0x0111, 32807, 0)
    for _ in range(20):
        time.sleep(0.3)
        for h, t, c, a in get_wins(pids, vis=True, min_area=5000):
            if 5000 < a < 600000 and 'producer' in t.lower():
                producer_dlg = h
                print(f'Producer dialog appeared: 0x{h:08X}')
                break
        if producer_dlg: break

if not producer_dlg:
    print('No producer dialog!')
    sys.exit(1)

# Get all SysListView32 controls
listviews = find_children_cls(producer_dlg, 'syslistview')
print(f'Found {len(listviews)} ListViews')

# Find the largest one (main list)
lv_areas = []
for lv in listviews:
    r2 = wt.RECT(); user32.GetWindowRect(lv, ctypes.byref(r2))
    a = (r2.right - r2.left) * (r2.bottom - r2.top)
    lv_areas.append((lv, a, r2))

lv_areas.sort(key=lambda x: x[1], reverse=True)
print('ListViews by area:')
for lv, a, r2 in lv_areas:
    count = user32.SendMessageW(lv, 0x1004, 0, 0)  # LVM_GETITEMCOUNT
    print(f'  0x{lv:08X} area={a} rect=({r2.left},{r2.top},{r2.right},{r2.bottom}) items={count}')

# Bring dialog to front and interact with it
user32.SetForegroundWindow(producer_dlg)
time.sleep(0.3)

# Strategy: Click first item in the FIRST (smallest, leftmost) non-header ListView
# The first ListView usually contains the EPROM manufacturers
# We want to select the FIRST item in each list to proceed
lv_areas_sorted_by_x = sorted(lv_areas, key=lambda x: x[2].left)

# Simulate the expected flow: click first item in first LV,
# then first item in second LV, etc.
for lv, a, r2 in lv_areas[:4]:  # First 4 list views (skip the large final one)
    count = user32.SendMessageW(lv, 0x1004, 0, 0)  # LVM_GETITEMCOUNT
    if count > 0:
        # Click at first item position (approx 10px from top of listview area)
        cx = (r2.left + r2.right) // 2
        cy = r2.top + 10
        print(f'Clicking LV 0x{lv:08X} at ({cx},{cy}) (items={count})')
        phys_click(cx, cy)
        time.sleep(0.2)
    else:
        print(f'LV 0x{lv:08X} is empty, skipping')

# Now click the large final list view's first item
if lv_areas:
    main_lv, a, r2 = lv_areas[0]  # Largest
    count = user32.SendMessageW(main_lv, 0x1004, 0, 0)
    print(f'Main LV: 0x{main_lv:08X} items={count}')
    if count > 0:
        cx = (r2.left + r2.right) // 2
        cy = r2.top + 10
        print(f'Clicking main LV at ({cx},{cy})')
        phys_click(cx, cy)
        time.sleep(0.3)

# Click OK
ok_b = find_child(producer_dlg, 'button', 'OK')
if ok_b:
    r2 = wt.RECT(); user32.GetWindowRect(ok_b, ctypes.byref(r2))
    okx = (r2.left + r2.right) // 2
    oky = (r2.top + r2.bottom) // 2
    print(f'Clicking OK at ({okx},{oky})')
    user32.SetForegroundWindow(producer_dlg); time.sleep(0.1)
    phys_click(okx, oky)
    time.sleep(0.5)

# Wait for EP2 TX
print('Waiting for EP2 TX...')
for _ in range(20):
    time.sleep(0.5)
    lt = log_tail()
    if 'TX (OLS300 cmd)' in lt:
        print('*** EP2 TX CAPTURED! ***')
        for line in lt.splitlines():
            if 'TX' in line or ('0' in line and ':' in line and len(line) > 20):
                print(f'  {line}')
        sys.exit(0)
    # Dismiss new dialogs
    for h, t, c, a in get_wins(pids, vis=True, min_area=5000):
        if 5000 < a < 600000 and h != producer_dlg:
            ok_b2 = find_child(h, 'button', 'OK')
            if ok_b2: user32.PostMessageW(ok_b2, 0x00F5, 0, 0)

print('No EP2 TX captured')
print('Log tail:')
for line in log_tail().splitlines()[-10:]: print(f'  {line}')
