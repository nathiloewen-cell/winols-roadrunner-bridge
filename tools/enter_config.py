"""enter_config.py - Bring Config to front and press Enter"""
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

pids = get_pids()
print(f'PIDs: {pids}')

config_dlg = None
for h, t, c, a in get_wins(pids, vis=True, min_area=50000):
    if 'configuration' in t.lower() or 'konfiguration' in t.lower():
        config_dlg = h
        print(f'Config: 0x{h:08X}')
        break

if not config_dlg:
    print('Config not found - opening...')
    wins = get_wins(pids, vis=False, min_area=400000)
    if wins:
        user32.PostMessageW(wins[0][0], 0x0111, 32827, 0)
        time.sleep(2)
        for h, t, c, a in get_wins(pids, vis=True, min_area=50000):
            if 'configuration' in t.lower():
                config_dlg = h
                print(f'Config opened: 0x{h:08X}')
                break

if not config_dlg:
    print('Cannot open Config!')
    exit(1)

# Use AllowSetForegroundWindow + BringWindowToTop
user32.AllowSetForegroundWindow(0xFFFFFFFF)  # ASFW_ANY
user32.ShowWindow(config_dlg, 9)  # SW_RESTORE
user32.BringWindowToTop(config_dlg)
user32.SetForegroundWindow(config_dlg)
time.sleep(0.5)

# Navigate tree to Hardware via keyboard if needed
# Use keybd_event for real keyboard input
print('Sending keyboard: H (Hardware), Right, S (Simulator), Enter')

# keybd_event flags: 0=keydown, 2=keyup
def key_down(vk): user32.keybd_event(vk, 0, 0, 0)
def key_up(vk):   user32.keybd_event(vk, 0, 2, 0)
def key_press(vk):
    key_down(vk); time.sleep(0.05); key_up(vk); time.sleep(0.1)

# Navigate tree - tree should have focus when dialog opens
# Press Home to go to first item
key_press(0x24)  # VK_HOME
time.sleep(0.2)

# Type H for Hardware
key_down(0x48); key_up(0x48)  # H
time.sleep(0.3)

# Right to expand
key_press(0x27)  # VK_RIGHT
time.sleep(0.2)

# Down to enter subtree
key_press(0x28)  # VK_DOWN
time.sleep(0.2)

# S for Simulator
key_down(0x53); key_up(0x53)  # S
time.sleep(0.3)

# Now press Enter = OK
print('Pressing Enter (OK)...')
key_press(0x0D)  # VK_RETURN
time.sleep(0.5)

print('Done!')
