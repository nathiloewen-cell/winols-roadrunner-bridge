"""nav_hw_menu.py - Navigate Hardware menu with mouse to find Simulator→Load"""
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
wins = get_wins(pids, vis=False, min_area=400000)
main_win = wins[0][0] if wins else None
print(f'Main: 0x{main_win:08X}')

menu = user32.GetMenu(main_win)
hw_rect = wt.RECT()
user32.GetMenuItemRect(main_win, menu, 2, ctypes.byref(hw_rect))
hw_cx = (hw_rect.left + hw_rect.right) // 2
hw_cy = (hw_rect.top + hw_rect.bottom) // 2
print(f'Hardware menu at ({hw_cx},{hw_cy})')

user32.SetForegroundWindow(main_win); time.sleep(0.3)

# Navigate using keyboard: Alt to open menu, then arrow keys
# Send Alt+H (or whatever the accelerator is) to open Hardware menu
# Actually, just click, then use keyboard

# Method: use keyboard navigation
# 1. Press F10 to activate menu bar
# 2. Press Right arrows to navigate to Hardware (index 2)
# 3. Press Down to open Hardware dropdown
# 4. Navigate down to submenu items
# 5. Press Right to open submenu
# 6. Check if this opens Simulator submenu

# Try: F10 to activate, then Right x2 to reach Hardware, Down to open
user32.keybd_event(0x79, 0, 0, 0)  # F10 down
user32.keybd_event(0x79, 0, 2, 0)  # F10 up
time.sleep(0.1)
# Navigate to Hardware (index 2 = 2 Rights from Project)
for _ in range(2):
    user32.keybd_event(0x27, 0, 0, 0)  # Right
    user32.keybd_event(0x27, 0, 2, 0)
    time.sleep(0.05)
# Open Hardware dropdown
user32.keybd_event(0x28, 0, 0, 0)  # Down
user32.keybd_event(0x28, 0, 2, 0)
time.sleep(0.3)

# Now get menu item rectangles to understand positions
hw_popup = user32.GetSubMenu(menu, 2)
count = user32.GetMenuItemCount(hw_popup)
print(f'\nHardware popup opened ({count} items). Getting item positions...')
for i in range(count):
    r2 = wt.RECT()
    if user32.GetMenuItemRect(main_win, hw_popup, i, ctypes.byref(r2)):
        # Get item ID
        class MII(ctypes.Structure):
            _fields_ = [('cbSize', wt.UINT), ('fMask', wt.UINT), ('fType', wt.UINT),
                        ('fState', wt.UINT), ('wID', wt.UINT), ('hSubMenu', wt.HMENU),
                        ('hbmpChecked', wt.HBITMAP), ('hbmpUnchecked', wt.HBITMAP),
                        ('dwItemData', ctypes.c_ulong), ('dwTypeData', ctypes.c_wchar_p),
                        ('cch', wt.UINT), ('hbmpItem', wt.HBITMAP)]
        buf = ctypes.create_unicode_buffer(256)
        m = MII(); m.cbSize = ctypes.sizeof(m)
        m.fMask = 0x46; m.dwTypeData = ctypes.cast(buf, ctypes.c_wchar_p); m.cch = 256
        user32.GetMenuItemInfoW(hw_popup, i, True, ctypes.byref(m))
        print(f'  [{i}] id={m.wID} rect=({r2.left},{r2.top},{r2.right},{r2.bottom}) sub={"yes" if m.hSubMenu else "no"}')

# Close menu
user32.keybd_event(0x1B, 0, 0, 0)  # Escape
user32.keybd_event(0x1B, 0, 2, 0)
time.sleep(0.2)

print('\nNow navigating via mouse to click each submenu...')
print('Will try clicking first item of each Hardware submenu that has one')

for submenu_idx in range(3, count):  # Start from index 3 (first submenu)
    r2 = wt.RECT()
    if not user32.GetMenuItemRect(main_win, hw_popup, submenu_idx, ctypes.byref(r2)):
        continue
    class MII2(ctypes.Structure):
        _fields_ = [('cbSize', wt.UINT), ('fMask', wt.UINT), ('fType', wt.UINT),
                    ('fState', wt.UINT), ('wID', wt.UINT), ('hSubMenu', wt.HMENU),
                    ('hbmpChecked', wt.HBITMAP), ('hbmpUnchecked', wt.HBITMAP),
                    ('dwItemData', ctypes.c_ulong), ('dwTypeData', ctypes.c_wchar_p),
                    ('cch', wt.UINT), ('hbmpItem', wt.HBITMAP)]
    m2 = MII2(); m2.cbSize = ctypes.sizeof(m2)
    m2.fMask = 0x46
    buf2 = ctypes.create_unicode_buffer(256); m2.dwTypeData = ctypes.cast(buf2, ctypes.c_wchar_p); m2.cch = 256
    user32.GetMenuItemInfoW(hw_popup, submenu_idx, True, ctypes.byref(m2))
    if not m2.hSubMenu: continue  # Skip non-submenu items

    print(f'\n--- Trying Hardware[{submenu_idx}] id={m2.wID} (submenu) ---')
    sub_first_item = user32.GetSubMenu(user32.GetSubMenu(menu, 2), submenu_idx)

    # Get first item of this submenu
    class MII3(ctypes.Structure):
        _fields_ = [('cbSize', wt.UINT), ('fMask', wt.UINT), ('fType', wt.UINT),
                    ('fState', wt.UINT), ('wID', wt.UINT), ('hSubMenu', wt.HMENU),
                    ('hbmpChecked', wt.HBITMAP), ('hbmpUnchecked', wt.HBITMAP),
                    ('dwItemData', ctypes.c_ulong), ('dwTypeData', ctypes.c_wchar_p),
                    ('cch', wt.UINT), ('hbmpItem', wt.HBITMAP)]
    buf3 = ctypes.create_unicode_buffer(256)
    m3 = MII3(); m3.cbSize = ctypes.sizeof(m3)
    m3.fMask = 0x46; m3.dwTypeData = ctypes.cast(buf3, ctypes.c_wchar_p); m3.cch = 256
    user32.GetMenuItemInfoW(m2.hSubMenu, 0, True, ctypes.byref(m3))
    print(f'  First item id={m3.wID} state={m3.fState:#x}')

    # Send WM_COMMAND for this first item
    user32.SetForegroundWindow(main_win); time.sleep(0.1)
    user32.PostMessageW(main_win, 0x0111, m3.wID, 0)
    time.sleep(1.5)

    # Check for dialogs
    dlgs = [(h, t, a) for h, t, c, a in get_wins(pids, vis=True, min_area=5000) if a < 600000]
    if dlgs:
        print(f'  Dialogs: {[(hex(h), t[:25], a) for h, t, a in dlgs]}')
        # Dismiss them
        for h, t, a in dlgs:
            ok_b = find_child(h, 'button', 'OK')
            if ok_b: user32.PostMessageW(ok_b, 0x00F5, 0, 0)
        time.sleep(0.5)
    else:
        print(f'  No dialog')

    # Check for EP2
    if 'TX (OLS300 cmd)' in log_tail():
        print(f'  *** EP2 TX CAPTURED! Hardware[{submenu_idx}] first item={m3.wID} is Load! ***')
        for line in log_tail().splitlines():
            if 'TX' in line: print(f'    {line}')
        sys.exit(0)

print('\nAll submenus tried. OLS300 Load not found yet.')
print('Checking all submenu items (not just first)...')

# Try ALL items of each submenu
for submenu_idx in range(3, count):
    r2 = wt.RECT()
    if not user32.GetMenuItemRect(main_win, hw_popup, submenu_idx, ctypes.byref(r2)):
        continue
    class MII4(ctypes.Structure):
        _fields_ = [('cbSize', wt.UINT), ('fMask', wt.UINT), ('fType', wt.UINT),
                    ('fState', wt.UINT), ('wID', wt.UINT), ('hSubMenu', wt.HMENU),
                    ('hbmpChecked', wt.HBITMAP), ('hbmpUnchecked', wt.HBITMAP),
                    ('dwItemData', ctypes.c_ulong), ('dwTypeData', ctypes.c_wchar_p),
                    ('cch', wt.UINT), ('hbmpItem', wt.HBITMAP)]
    m4 = MII4(); m4.cbSize = ctypes.sizeof(m4); m4.fMask = 0x46
    user32.GetMenuItemInfoW(hw_popup, submenu_idx, True, ctypes.byref(m4))
    if not m4.hSubMenu: continue

    sc = user32.GetMenuItemCount(m4.hSubMenu)
    for j in range(sc):
        class MII5(ctypes.Structure):
            _fields_ = [('cbSize', wt.UINT), ('fMask', wt.UINT), ('fType', wt.UINT),
                        ('fState', wt.UINT), ('wID', wt.UINT), ('hSubMenu', wt.HMENU),
                        ('hbmpChecked', wt.HBITMAP), ('hbmpUnchecked', wt.HBITMAP),
                        ('dwItemData', ctypes.c_ulong), ('dwTypeData', ctypes.c_wchar_p),
                        ('cch', wt.UINT), ('hbmpItem', wt.HBITMAP)]
        m5 = MII5(); m5.cbSize = ctypes.sizeof(m5); m5.fMask = 0x46
        user32.GetMenuItemInfoW(m4.hSubMenu, j, True, ctypes.byref(m5))
        if m5.wID == 0: continue  # separator

        user32.SetForegroundWindow(main_win); time.sleep(0.1)
        user32.PostMessageW(main_win, 0x0111, m5.wID, 0)
        time.sleep(0.8)

        dlgs = [(h, t, a) for h, t, c, a in get_wins(pids, vis=True, min_area=5000) if a < 600000]
        if dlgs:
            dlg_names = [t[:20] for h, t, a in dlgs]
            if 'Select producer' not in dlg_names:  # Batronix dialog = skip
                print(f'  HW[{submenu_idx}][{j}] id={m5.wID}: dialogs={dlg_names}')
            for h, t, a in dlgs:
                ok_b = find_child(h, 'button', 'OK')
                if ok_b: user32.PostMessageW(ok_b, 0x00F5, 0, 0)
            time.sleep(0.3)

        if 'TX (OLS300 cmd)' in log_tail():
            print(f'  *** EP2 at HW[{submenu_idx}][{j}] id={m5.wID}! ***')
            sys.exit(0)
