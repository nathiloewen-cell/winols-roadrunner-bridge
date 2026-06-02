"""click_simulator_load.py - Navigate Hardware menu with mouse to find OLS300 Load"""
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

def phys_move(x, y):
    user32.SetCursorPos(x, y); time.sleep(0.1)

pids = get_pids()
print(f'PIDs: {pids}')

wins = get_wins(pids, vis=False, min_area=400000)
main_win = wins[0][0] if wins else None
print(f'Main: 0x{main_win:08X}')

# Get menu and Hardware item position
menu = user32.GetMenu(main_win)
print(f'Menu: 0x{menu:08X}')

# Find Hardware menu item position (item 2 = index 2)
hw_rect = wt.RECT()
if user32.GetMenuItemRect(main_win, menu, 2, ctypes.byref(hw_rect)):
    hw_cx = (hw_rect.left + hw_rect.right) // 2
    hw_cy = (hw_rect.top + hw_rect.bottom) // 2
    print(f'Hardware menu item at ({hw_cx},{hw_cy})')
else:
    # Fallback: estimate from window
    r2 = wt.RECT(); user32.GetWindowRect(main_win, ctypes.byref(r2))
    hw_cx = r2.left + 165
    hw_cy = r2.top + 22
    print(f'Hardware menu estimated at ({hw_cx},{hw_cy})')

# Bring WinOLS to front
user32.SetForegroundWindow(main_win); time.sleep(0.3)

# Step 1: Click Hardware menu
print('Clicking Hardware menu...')
phys_click(hw_cx, hw_cy)
time.sleep(0.5)

# Step 2: Check what popup appeared
# Get the popup menu position by checking for new windows
print('Hardware popup should be open. Moving mouse to find Simulator...')
# The dropdown menu items are below the hardware position
# Simulator is typically the 4th or 5th item in the Hardware menu
# Hardware menu items: Connect/Disconnect(2), Sep, ExtProg(sub), Simulator(sub), Batronix(sub), OLS300(sub)
# Let's try clicking at various Y positions below the Hardware menu

# First, move to find the Simulator submenu
# Hardware menu items are about 18-20px tall each
# Items: [0]=32891, [1]=32896, [2]=sep, [3..6]=submenus
# The submenus start at item index 3 → y offset = about 3*20 + separator = ~75px from menu bar

# Try to find "Simulator" submenu by moving down and looking for the OLS300 Load option
# Move mouse down from Hardware menu position
print('Trying to navigate Hardware > Simulator menu with mouse...')

# WinOLS is likely using ~480 width, menu bar at y~22
# Hardware menu item is at hw_cx ~165
# After clicking Hardware, the popup menu appears below
# Submenu positions (approximate):
# Item 0 (32891): y+20
# Item 1 (32896): y+38
# Sep: y+48
# Item 3 (789103): y+62
# Item 4 (592549): y+80
# Item 5 (592543): y+98  <- Simulator (3rd submenu, guessing)
# Item 6 (789159): y+116

# Actually, let's just try clicking at different y offsets from Hardware
base_y = hw_cy  # Y position of Hardware menu bar item

# Send keyboard navigation instead (more reliable than mouse Y estimation)
# After clicking Hardware, use keyboard to navigate:
# Down to reach submenus, then Right to open submenu, then Down to Load

# Actually, after opening the hardware menu with Alt+key, navigate with arrows
# Press Escape first to close any open menus
user32.keybd_event(0x1B, 0, 0, 0); user32.keybd_event(0x1B, 0, 2, 0); time.sleep(0.1)

# Use Alt+H to open Hardware menu (if WinOLS uses standard Alt+letter shortcuts)
# Hardware menu has '&' in "&Hardware" = Alt+H? No, it's '&Hardware' which uses H
# But the menu accelerator might be different in this WinOLS version

# Let's try: post WM_COMMAND 32827 to see Config, then check menu state
# Actually, let's use a different approach: GetMenuString to check text

# Use GetMenuStringW for each submenu item under Hardware
# Even if GetMenuItemInfo returns empty, GetMenuStringW might work
print('\nTrying GetMenuStringW for Hardware submenus...')
hw_menu = user32.GetSubMenu(menu, 2)
if hw_menu:
    count = user32.GetMenuItemCount(hw_menu)
    print(f'Hardware submenu count: {count}')
    for i in range(count):
        buf = ctypes.create_unicode_buffer(256)
        length = user32.GetMenuStringW(hw_menu, i, buf, 256, 0x400)  # MF_BYPOSITION=0x400
        sub = user32.GetSubMenu(hw_menu, i)

        class MII(ctypes.Structure):
            _fields_ = [('cbSize', wt.UINT), ('fMask', wt.UINT), ('fType', wt.UINT),
                        ('fState', wt.UINT), ('wID', wt.UINT), ('hSubMenu', wt.HMENU),
                        ('hbmpChecked', wt.HBITMAP), ('hbmpUnchecked', wt.HBITMAP),
                        ('dwItemData', ctypes.c_ulong), ('dwTypeData', ctypes.c_wchar_p),
                        ('cch', wt.UINT), ('hbmpItem', wt.HBITMAP)]
        m = MII(); m.cbSize = ctypes.sizeof(m)
        m.fMask = 0x46; m.dwTypeData = ctypes.cast(buf, ctypes.c_wchar_p); m.cch = 256
        user32.GetMenuItemInfoW(hw_menu, i, True, ctypes.byref(m))

        print(f'  [{i}] id={m.wID} str={buf.value!r} (len={length}) sub=0x{sub:08X}' if sub else
              f'  [{i}] id={m.wID} str={buf.value!r} (len={length})')

        if sub:
            # Check subsubmenu items
            sc = user32.GetMenuItemCount(sub)
            for j in range(min(sc, 5)):
                buf2 = ctypes.create_unicode_buffer(256)
                l2 = user32.GetMenuStringW(sub, j, buf2, 256, 0x400)
                m2 = MII(); m2.cbSize = ctypes.sizeof(m2)
                m2.fMask = 0x46; m2.dwTypeData = ctypes.cast(buf2, ctypes.c_wchar_p); m2.cch = 256
                user32.GetMenuItemInfoW(sub, j, True, ctypes.byref(m2))
                print(f'    [{j}] id={m2.wID} str={buf2.value!r} (l={l2}) state={m2.fState:#x}')
