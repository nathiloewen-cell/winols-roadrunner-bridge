"""config_hardware_ok.py - Open Config, click Hardware in tree, select USB OLS300, click OK"""
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

def phys_click(x, y):
    user32.SetCursorPos(x, y)
    time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
    time.sleep(0.1)

pids = get_pids()
print(f'PIDs: {pids}')

# Open Config dialog
wins = get_wins(pids, vis=False, min_area=400000)
main_win = wins[0][0] if wins else None
print(f'Main: 0x{main_win:08X}')
print('Opening Config...')
user32.PostMessageW(main_win, 0x0111, 32827, 0)
time.sleep(1.5)

# Find Config dialog
config_dlg = None
for h, t, c, a in get_wins(pids, vis=True, min_area=50000):
    if 'configuration' in t.lower() or 'konfiguration' in t.lower():
        config_dlg = h
        print(f'Config: 0x{h:08X}')
        break

if not config_dlg:
    print('No Config!'); exit(1)

# Get Config dialog position + TreeView position
r2 = wt.RECT(); user32.GetWindowRect(config_dlg, ctypes.byref(r2))
print(f'Config rect: ({r2.left},{r2.top},{r2.right},{r2.bottom})')

tv = find_child(config_dlg, 'systreeview')
if tv:
    tv_rect = wt.RECT(); user32.GetWindowRect(tv, ctypes.byref(tv_rect))
    print(f'TreeView rect: ({tv_rect.left},{tv_rect.top},{tv_rect.right},{tv_rect.bottom})')
    tv_cx = (tv_rect.left + tv_rect.right) // 2
    tv_y_start = tv_rect.top + 10  # Near top of tree

    # Bring Config to front
    user32.SetForegroundWindow(config_dlg)
    time.sleep(0.3)

    # Click in tree at various y-positions to find/select items
    # Try y offsets from top of tree: 15, 35, 55... (each item ~20px tall)
    print(f'Clicking in TreeView at x={tv_cx}...')
    for y_offset in [15, 35, 55]:
        y = tv_rect.top + y_offset
        print(f'  Clicking at ({tv_cx},{y})')
        phys_click(tv_cx, y)
        time.sleep(0.2)
        # Check what page is now showing (by looking at child windows title)
        active_page = find_child(config_dlg, None, 'Hardware')
        if active_page:
            print(f'  Hardware page found! hwnd=0x{active_page:08X}')
            break

    # Press Right arrow to expand Hardware in tree
    user32.PostMessageW(tv, 0x0100, 0x27, 0)  # VK_RIGHT
    time.sleep(0.2)

    # Press Down to navigate to child items
    user32.PostMessageW(tv, 0x0100, 0x28, 0)  # VK_DOWN
    time.sleep(0.2)
    user32.PostMessageW(tv, 0x0100, 0x28, 0)  # VK_DOWN again
    time.sleep(0.3)

# Now try to find and click USB OLS300 radio button
for s in ['OLS300', 'USB']:
    r = find_child(config_dlg, 'button', s)
    if r:
        r_rect = wt.RECT(); user32.GetWindowRect(r, ctypes.byref(r_rect))
        rx = (r_rect.left + r_rect.right) // 2
        ry = (r_rect.top + r_rect.bottom) // 2
        print(f'Clicking radio {s!r} at ({rx},{ry})')
        user32.SetForegroundWindow(config_dlg)
        time.sleep(0.1)
        phys_click(rx, ry)
        time.sleep(0.3)
        break

# Click OK via PostMessage (non-blocking to avoid deadlock)
ok_b = find_child(config_dlg, 'button', 'OK')
if ok_b:
    ok_rect = wt.RECT(); user32.GetWindowRect(ok_b, ctypes.byref(ok_rect))
    okx = (ok_rect.left + ok_rect.right) // 2
    oky = (ok_rect.top + ok_rect.bottom) // 2
    print(f'Clicking OK at ({okx},{oky})')
    user32.SetForegroundWindow(config_dlg)
    time.sleep(0.1)
    phys_click(okx, oky)
    time.sleep(0.5)

# Check if closed
open_still = user32.IsWindow(config_dlg) and user32.IsWindowVisible(config_dlg)
print(f'Config dialog: {"still open" if open_still else "CLOSED!"}')
print('Done')
