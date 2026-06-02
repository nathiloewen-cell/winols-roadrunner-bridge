import ctypes, ctypes.wintypes as wt, subprocess, time, struct, sys

user32 = ctypes.windll.user32
k32    = ctypes.windll.kernel32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

def get_pids():
    r = subprocess.run(["tasklist","/FI","IMAGENAME eq ols_32on32.exe","/FO","CSV"],
                       capture_output=True, text=True)
    pids = []
    for line in r.stdout.splitlines()[1:]:
        p = line.strip('"').split('","')
        if len(p) >= 2:
            try: pids.append(int(p[1]))
            except: pass
    return pids

def enum_wins(pids, vis=True):
    wins = []
    def cb(h, l):
        p = wt.DWORD(0); user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value not in pids: return True
        if vis and not user32.IsWindowVisible(h): return True
        tb = ctypes.create_unicode_buffer(256); cl = ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(h, tb, 256); user32.GetClassNameW(h, cl, 64)
        r2 = wt.RECT(); user32.GetWindowRect(h, ctypes.byref(r2))
        area = (r2.right - r2.left) * (r2.bottom - r2.top)
        wins.append((h, tb.value, cl.value, area))
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return sorted(wins, key=lambda x: x[3], reverse=True)

def find_child(parent, cls_frag=None, txt_frag=None):
    found = [None]
    def cb(h, l):
        tb = ctypes.create_unicode_buffer(256); cl = ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(h, tb, 256); user32.GetClassNameW(h, cl, 64)
        ok = True
        if cls_frag and cls_frag.lower() not in cl.value.lower(): ok = False
        if txt_frag and txt_frag.lower() not in tb.value.lower(): ok = False
        if ok: found[0] = h
        return True
    user32.EnumChildWindows(parent, WNDENUMPROC(cb), 0)
    return found[0]

def bclick(hwnd):
    user32.SetForegroundWindow(hwnd); time.sleep(0.1)
    user32.SendMessageW(hwnd, 0x00F5, 0, 0)

def treeview_select(tv_hwnd, target_text):
    pid_val = wt.DWORD(0)
    user32.GetWindowThreadProcessId(tv_hwnd, ctypes.byref(pid_val))
    hproc = k32.OpenProcess(0x001F0FFF, False, pid_val.value)
    if not hproc: return False

    BUF_SIZE = 640
    remote = k32.VirtualAllocEx(hproc, None, BUF_SIZE, 0x1000, 0x04)
    if not remote:
        k32.CloseHandle(hproc); return False
    remote_txt = remote + 64

    found_h = [0]

    def walk(hitem, depth=0):
        if not hitem or depth > 20: return False
        # TVITEMW: mask(4), hItem(4), state(4), stateMask(4), pszText(4), cchTextMax(4), ...
        # TVITEMW 32-bit: mask(4) hItem(4) state(4) stateMask(4) pszText(4) cchTextMax(4) ...
        local = struct.pack('<IIIIII', 0x11, hitem & 0xFFFFFFFF, 0, 0,
                            remote_txt & 0xFFFFFFFF, 256)
        local += b'\x00' * (64 - len(local))
        wr = ctypes.c_size_t(0)
        k32.WriteProcessMemory(hproc, remote, ctypes.create_string_buffer(local), 64, ctypes.byref(wr))
        user32.SendMessageW(tv_hwnd, 0x100C, 0, remote)  # TVM_GETITEM
        rbuf = ctypes.create_string_buffer(512)
        rd = ctypes.c_size_t(0)
        k32.ReadProcessMemory(hproc, remote_txt, rbuf, 512, ctypes.byref(rd))
        try: txt = rbuf.raw[:rd.value].decode('utf-16-le').rstrip('\x00')
        except: txt = ''
        if txt: print('  ' + '  ' * depth + repr(txt))
        if target_text.lower() in txt.lower():
            found_h[0] = hitem; return True
        child = user32.SendMessageW(tv_hwnd, 0x110A, 4, hitem)  # TVGN_CHILD
        if child and walk(child, depth + 1): return True
        sib = user32.SendMessageW(tv_hwnd, 0x110A, 1, hitem)    # TVGN_NEXT
        if sib and walk(sib, depth): return True
        return False

    root = user32.SendMessageW(tv_hwnd, 0x110A, 0, 0)  # TVGN_ROOT
    walk(root)
    k32.VirtualFreeEx(hproc, remote, 0, 0x8000)
    k32.CloseHandle(hproc)

    if found_h[0]:
        user32.SendMessageW(tv_hwnd, 0x110B, 9, found_h[0])  # TVM_SELECTITEM CARET
        time.sleep(0.4)
        print(f"Simulator selected (hItem={found_h[0]})")
        return True
    print("Simulator NOT found in tree!")
    return False

# ── main ──────────────────────────────────────────────────────────────────
pids = get_pids()
if not pids:
    print("WinOLS not found"); sys.exit(1)
print("PIDs:", pids)

# Find main WinOLS window
main_win = None
for h, t, c, a in enum_wins(pids, vis=False):
    if a > 400000:
        main_win = h; print(f"Main window: 0x{h:08X} area={a}"); break

if not main_win:
    print("No main window!"); sys.exit(1)

# Open Configuration (WM_COMMAND 32827)
print("Opening Configuration dialog...")
user32.PostMessageW(main_win, 0x0111, 32827, 0)
time.sleep(1.5)

# Find the Configuration dialog
config_dlg = None
for h, t, c, a in enum_wins(pids):
    if a < 50000: continue
    ok_b  = find_child(h, 'button', 'OK')
    ab_b  = find_child(h, 'button', 'Abbrechen') or find_child(h, 'button', 'Cancel')
    if ok_b and ab_b:
        config_dlg = h; print(f"Config dialog: '{t}' area={a}"); break

if not config_dlg:
    print("Config dialog not found!")
    print("Visible:", [(f"0x{h:08X}", t, a) for h, t, c, a in enum_wins(pids) if a > 5000])
    sys.exit(1)

# Find TreeView
tv = find_child(config_dlg, 'systreeview')
if not tv:
    tv = find_child(config_dlg, 'treeview')
print(f"TreeView: 0x{tv:08X}" if tv else "No TreeView!")

if tv:
    # Try cross-process walk first
    found = treeview_select(tv, 'Simulator')
    if not found:
        # Fallback: activate tree + press End (Simulator = last item in tree)
        print("Fallback: keyboard End key in TreeView")
        user32.SetForegroundWindow(tv)
        time.sleep(0.2)
        user32.SendMessageW(tv, 0x0100, 0x23, 0x00010001)  # WM_KEYDOWN End
        time.sleep(0.05)
        user32.SendMessageW(tv, 0x0101, 0x23, 0xC0010001)  # WM_KEYUP End
        time.sleep(0.3)
    time.sleep(0.5)
else:
    # No TreeView found — use keyboard navigation in dialog
    print("No TreeView, using keyboard End")
    user32.SetForegroundWindow(config_dlg)
    time.sleep(0.2)
    # Tab to reach the tree area
    for _ in range(2):
        user32.SendMessageW(config_dlg, 0x0100, 0x09, 0x00010001)
        time.sleep(0.08)
    # End to jump to Simulator (last item)
    user32.SendMessageW(config_dlg, 0x0100, 0x23, 0x00010001)
    time.sleep(0.3)

# Click USB OLS300 radio
for s in ['OLS300', 'USB']:
    radio = find_child(config_dlg, 'button', s)
    if radio:
        print(f"Clicking USB radio: {s}")
        bclick(radio); time.sleep(0.3); break

# Click OK - verify exact text
ok_b = find_child(config_dlg, 'button', 'OK')
if ok_b:
    tb = ctypes.create_unicode_buffer(64)
    user32.GetWindowTextW(ok_b, tb, 64)
    if tb.value.strip().upper() == 'OK':
        print("Clicking OK...")
        bclick(ok_b)
        print("DONE - Config OK clicked!")
    else:
        print(f"Button text: {tb.value!r} - not clicking")
else:
    print("OK button not found!")
