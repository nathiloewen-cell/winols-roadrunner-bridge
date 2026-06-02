#!/usr/bin/env python3
"""
auto_config_ok.py - Vollautomatischer WinOLS Config-OK-Klicker.

Automatisiert: Start → Dialoge wegklicken → Miscellaneous → Configuration →
               Hardware → Simulator → USB (OLS300) → OK → warten → wiederholen

Nutzung: python auto_config_ok.py
"""
import ctypes, ctypes.wintypes as wt, time, subprocess, sys, os

user32 = ctypes.windll.user32
k32    = ctypes.windll.kernel32

VK_MENU  = 0x12  # Alt
VK_RETURN= 0x0D
VK_ESCAPE= 0x1B
VK_F4    = 0x73
VK_TAB   = 0x09
VK_UP    = 0x26
VK_DOWN  = 0x28
VK_LEFT  = 0x25
VK_RIGHT = 0x27
VK_SPACE = 0x20

KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD  = 1

WINOLS_LOG = r"C:\Users\Nates\AppData\Local\Temp\winols_wdapi.log"

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_ulong)]
class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]
class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("_u", _U)]

def send_key(vk, up=False):
    i = INPUT(); i.type = INPUT_KEYBOARD
    i._u.ki.wVk = vk; i._u.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
    user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(i))

def key_tap(vk, ms=60):
    send_key(vk, False); time.sleep(ms/1000)
    send_key(vk, True);  time.sleep(ms/1000)

def alt_key(vk, ms=80):
    send_key(VK_MENU, False); time.sleep(0.03)
    send_key(vk, False); time.sleep(0.03)
    send_key(vk, True);  time.sleep(0.03)
    send_key(VK_MENU, True); time.sleep(ms/1000)

# ── Window helpers ─────────────────────────────────────────────────────────
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

def get_pids():
    r = subprocess.run(['tasklist','/FI','IMAGENAME eq ols_32on32.exe','/FO','CSV'],
                       capture_output=True, text=True)
    pids = []
    for line in r.stdout.splitlines()[1:]:
        parts = line.strip('"').split('","')
        if len(parts) >= 2:
            try: pids.append(int(parts[1]))
            except: pass
    return pids

def enum_winols_wins(pids):
    wins = []
    def cb(hwnd, lp):
        p = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value in pids: wins.append(hwnd)
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return wins

def get_win_info(hwnd):
    tb = ctypes.create_unicode_buffer(256)
    cb = ctypes.create_unicode_buffer(64)
    user32.GetWindowTextW(hwnd, tb, 256)
    user32.GetClassNameW(hwnd, cb, 64)
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    area = (r.right-r.left)*(r.bottom-r.top)
    vis = bool(user32.IsWindowVisible(hwnd))
    return tb.value, cb.value, area, vis

def find_child_button(parent, text_frag):
    found = [None]
    def cb(hwnd, lp):
        tb = ctypes.create_unicode_buffer(128)
        cl = ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(hwnd, tb, 128)
        user32.GetClassNameW(hwnd, cl, 64)
        if text_frag.lower() in tb.value.lower() and 'button' in cl.value.lower():
            found[0] = hwnd
        return True
    user32.EnumChildWindows(parent, WNDENUMPROC(cb), 0)
    return found[0]

def find_child_radio(parent, text_frag):
    """Find radio button or checkbox containing text."""
    found = [None]
    def cb(hwnd, lp):
        tb = ctypes.create_unicode_buffer(128)
        cl = ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(hwnd, tb, 128)
        user32.GetClassNameW(hwnd, cl, 64)
        if text_frag.lower() in tb.value.lower() and 'button' in cl.value.lower():
            found[0] = hwnd
        return True
    user32.EnumChildWindows(parent, WNDENUMPROC(cb), 0)
    return found[0]

def activate(hwnd):
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)

def click_btn(hwnd):
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.1)
    user32.SendMessageW(hwnd, 0x00F5, 0, 0)  # BM_CLICK

# ── Log helpers ────────────────────────────────────────────────────────────
def log_tail(n=20):
    try:
        h = k32.CreateFileW(WINOLS_LOG, 0x80000000, 7, None, 3, 0, None)
        sz = k32.GetFileSize(h, None)
        off = max(0, sz - n*100)
        k32.SetFilePointer(h, off, None, 0)
        buf = ctypes.create_string_buffer(n*100)
        rd = wt.DWORD(0)
        k32.ReadFile(h, buf, n*100, ctypes.byref(rd), None)
        k32.CloseHandle(h)
        return buf.raw[:rd.value].decode('utf-8', 'replace').splitlines()
    except: return []

def log_size():
    try:
        h = k32.CreateFileW(WINOLS_LOG, 0x80000000, 7, None, 3, 0, None)
        sz = k32.GetFileSize(h, None); k32.CloseHandle(h); return sz
    except: return 0

# ── Step 1: Dismiss startup / crash dialogs ────────────────────────────────
def dismiss_all_dialogs(pids, timeout=8):
    """Click away any blocking dialogs before main flow."""
    dismissed = 0
    DISMISS_BTNS = ['Nein','No',"Don't send",'Nicht senden','Cancel',
                    'Abbrechen','Close','Schließen','OK']
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = False
        wins = enum_winols_wins(pids)
        for hwnd in wins:
            title, cls, area, vis = get_win_info(hwnd)
            # Skip the main WinOLS window (large area)
            if area > 300000: continue
            for btn_txt in DISMISS_BTNS:
                btn = find_child_button(hwnd, btn_txt)
                if btn:
                    print(f"  [dismiss] '{title}' -> '{btn_txt}'")
                    activate(hwnd)
                    click_btn(btn)
                    dismissed += 1
                    found = True
                    time.sleep(0.6)
                    break
            if found: break
        if not found: break
    return dismissed

# ── Step 2: Find the main WinOLS interaction window ────────────────────────
def find_main_win(pids):
    """Find the main WinOLS window (visible, titled 'WinOLS')."""
    wins = enum_winols_wins(pids)
    # Prefer visible window with 'WinOLS' in title
    for hwnd in wins:
        title, cls, area, vis = get_win_info(hwnd)
        if vis and 'winols' in title.lower():
            return hwnd
    # Fall back to largest window
    best, best_area = None, 0
    for hwnd in wins:
        _, _, area, _ = get_win_info(hwnd)
        if area > best_area: best, best_area = hwnd, area
    return best

# ── Step 3: Open Configuration dialog ─────────────────────────────────────
WM_CMD_CONFIGURATION = 32827  # Discovered via brute-force: Miscellaneous → Configuration

def open_config_dialog(main_win, pids):
    """Open Configuration dialog via known WM_COMMAND ID 32827."""
    print(f"  [config] PostMessage(0x{main_win:08X}, WM_COMMAND, {WM_CMD_CONFIGURATION}, 0)")
    user32.PostMessageW(main_win, 0x0111, WM_CMD_CONFIGURATION, 0)
    time.sleep(1.0)

    # Verify dialog opened
    wins = enum_winols_wins(pids)
    for hwnd in wins:
        title, cls, area, vis = get_win_info(hwnd)
        if vis and 'config' in title.lower() and area > 50000:
            print(f"  [config] Configuration dialog opened: '{title}'")
            return True

    print("  [config] Dialog not found, retrying...")
    time.sleep(0.5)
    user32.PostMessageW(main_win, 0x0111, WM_CMD_CONFIGURATION, 0)
    time.sleep(1.5)
    return True  # proceed anyway

# ── Step 4: Navigate Config dialog and click OK ─────────────────────────────
TVM_GETROOT     = 0x1100
TVM_GETNEXTITEM = 0x110A
TVM_SELECTITEM  = 0x110B
TVM_GETITEM     = 0x100C
TVGN_ROOT       = 0
TVGN_NEXT       = 1
TVGN_CHILD      = 4
TVIF_TEXT       = 0x0001
TVIF_HANDLE     = 0x0010

class TVITEM(ctypes.Structure):
    _fields_ = [("mask",wt.UINT),("hItem",ctypes.c_void_p),
                ("state",wt.UINT),("stateMask",wt.UINT),
                ("pszText",ctypes.c_wchar_p),("cchTextMax",ctypes.c_int),
                ("iImage",ctypes.c_int),("iSelectedImage",ctypes.c_int),
                ("cChildren",ctypes.c_int),("lParam",ctypes.c_long)]

def find_treeview(parent):
    """Find the TreeView control in a dialog."""
    found = [None]
    def cb(h,l):
        cl = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(h, cl, 64)
        if 'treeview' in cl.value.lower() or 'systreeview' in cl.value.lower():
            found[0] = h
        return True
    user32.EnumChildWindows(parent, WNDENUMPROC(cb), 0)
    return found[0]

def treeview_find_and_click(tv_hwnd, target_text):
    """Walk tree items looking for target_text and click it."""
    k32loc = ctypes.windll.kernel32

    def walk(hitem, depth=0):
        if not hitem or depth > 10: return False
        # Get item text
        buf = ctypes.create_unicode_buffer(256)
        tvi = TVITEM()
        tvi.mask = TVIF_TEXT | TVIF_HANDLE
        tvi.hItem = hitem
        tvi.pszText = ctypes.cast(buf, ctypes.c_wchar_p)
        tvi.cchTextMax = 256
        user32.SendMessageW(tv_hwnd, TVM_GETITEM, 0, ctypes.byref(tvi))
        txt = buf.value

        if target_text.lower() in txt.lower():
            print(f"  [tree] Found '{txt}' -> selecting")
            user32.SendMessageW(tv_hwnd, TVM_SELECTITEM, 3, hitem)  # TVGN_CARET=9
            time.sleep(0.3)
            # Double-click to select
            r = wt.RECT(); user32.GetWindowRect(tv_hwnd, ctypes.byref(r))
            # Just send a click at the item position via LButtonDown
            user32.SendMessageW(tv_hwnd, 0x0203, 0, 0)  # WM_LBUTTONDBLCLK
            time.sleep(0.3)
            return True

        # Check children
        child = user32.SendMessageW(tv_hwnd, TVM_GETNEXTITEM, TVGN_CHILD, hitem)
        if child and walk(child, depth+1):
            return True

        # Check siblings
        sibling = user32.SendMessageW(tv_hwnd, TVM_GETNEXTITEM, TVGN_NEXT, hitem)
        if sibling and walk(sibling, depth):
            return True

        return False

    root = user32.SendMessageW(tv_hwnd, TVM_GETROOT, 0, 0)
    return walk(root)

def config_select_usb_ok(pids):
    """In Config dialog: click Simulator in tree, select USB OLS300, click OK."""
    # Find the Configuration dialog
    config_dlg = None
    wins = enum_winols_wins(pids)
    for hwnd in wins:
        title, cls, area, vis = get_win_info(hwnd)
        if not vis or area < 50000: continue
        ok_btn = find_child_button(hwnd, 'OK')
        cancel = find_child_button(hwnd, 'Abbrechen') or find_child_button(hwnd, 'Cancel')
        if ok_btn and cancel:
            config_dlg = hwnd
            print(f"  [config-ok] Dialog: '{title}' area={area}")
            break
    if not config_dlg:
        for hwnd in wins:
            title, cls, area, vis = get_win_info(hwnd)
            if vis and area > 50000:
                ok_btn = find_child_button(hwnd, 'OK')
                if ok_btn:
                    config_dlg = hwnd; print(f"  [config-ok] Fallback: '{title}'"); break

    if not config_dlg:
        print("  [config-ok] No config dialog found!")
        return False

    # Step 1: Click "Simulator" in the TreeView on the left
    tv = find_treeview(config_dlg)
    if tv:
        print(f"  [config-ok] TreeView found: 0x{tv:08X}")
        clicked = treeview_find_and_click(tv, 'Simulator')
        if clicked:
            print("  [config-ok] Simulator clicked in tree")
            time.sleep(0.5)
        else:
            print("  [config-ok] Simulator not found in tree, trying keyboard nav...")
            # Use keyboard to navigate to Simulator
            activate(config_dlg)
            # Hardware → Simulator is near the bottom of the tree
            # Tab to tree, then use end+up to find Simulator
            key_tap(VK_TAB); time.sleep(0.1)
            key_tap(0x23);   time.sleep(0.1)  # End key
            for _ in range(3):
                key_tap(VK_UP); time.sleep(0.1)
            key_tap(VK_RETURN); time.sleep(0.3)
    else:
        print("  [config-ok] No TreeView found")

    # Step 2: Select USB (OLS300 only) radio button
    time.sleep(0.3)
    for search_text in ['OLS300', 'USB (OLS', 'USB']:
        usb_radio = find_child_radio(config_dlg, search_text)
        if usb_radio:
            print(f"  [config-ok] Found '{search_text}' radio, clicking")
            click_btn(usb_radio)
            time.sleep(0.3)
            break
    else:
        print("  [config-ok] No USB radio found, using current selection")

    # Step 3: Click OK
    ok_btn = find_child_button(config_dlg, 'OK')
    if ok_btn:
        print("  [config-ok] Clicking OK")
        click_btn(ok_btn)
        return True

    activate(config_dlg); key_tap(VK_RETURN)
    return True

# ── Wait for identification cycle ──────────────────────────────────────────
def wait_for_cycle_end(timeout=60):
    """Wait for WDU_Uninit (end of identification) or EP2 commands (success)."""
    baseline = log_size()
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(1)
        lines = log_tail(10)
        if any('WDU_Uninit' in l for l in lines[-5:]):
            return 'uninit'
        if any('OLS300 cmd' in l for l in lines[-5:]):
            return 'success'
        if any('ID pipe' in l for l in lines[-5:]):
            continue  # still running
    return 'timeout'

# ── Check WinOLS responsiveness ─────────────────────────────────────────────
def is_winols_responding(pids):
    for p in pids:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             f'(Get-Process -Id {p} -ErrorAction SilentlyContinue).Responding'],
            capture_output=True, text=True, timeout=5)
        if 'True' in result.stdout: return True
    return False

# ── Main loop ──────────────────────────────────────────────────────────────
def main():
    print("=== WinOLS Config-OK Auto-Loop ===")
    print("Ziel: Miscellaneous → Configuration → USB (OLS300) → OK automatisieren")
    print("Drücke Ctrl+C zum Beenden.\n")

    cycle = 0
    while True:
        cycle += 1
        print(f"\n{'='*50}")
        print(f"CYCLE {cycle}")
        print(f"{'='*50}")

        # Get WinOLS PIDs
        pids = get_pids()
        if not pids:
            print("WinOLS nicht gefunden. Starte WinOLS...")
            os.startfile(r"C:\Program Files\EVC\WinOLS\ols_32on32.exe")
            time.sleep(7)
            pids = get_pids()
            if not pids:
                print("WinOLS konnte nicht gestartet werden!")
                time.sleep(5)
                continue

        print(f"WinOLS PIDs: {pids}")

        # Step 1: Dismiss startup dialogs
        print("Schritt 1: Startup-Dialoge wegklicken...")
        n = dismiss_all_dialogs(pids, timeout=8)
        if n: print(f"  {n} Dialog(e) dismissed")
        time.sleep(1)

        # Check WinOLS state
        pids = get_pids()
        if not pids:
            print("WinOLS beendet sich! Warte...")
            time.sleep(5)
            continue

        # Step 2: Find main window
        print("Schritt 2: WinOLS Hauptfenster suchen...")
        main_win = find_main_win(pids)
        if not main_win:
            print("Kein WinOLS-Fenster gefunden!")
            time.sleep(3)
            continue
        title, cls, area, vis = get_win_info(main_win)
        print(f"  Gefunden: 0x{main_win:08X} '{title}' area={area}")

        # Step 3: Open Configuration dialog
        print("Schritt 3: Miscellaneous → Configuration öffnen...")
        opened = open_config_dialog(main_win, pids)
        if not opened:
            print("  FEHLER: Config-Dialog konnte nicht geöffnet werden")
            # Try waiting for it to appear (maybe already opening)
            time.sleep(2)

        # Step 4: Navigate dialog and click OK
        print("Schritt 4: USB OLS300 auswählen und OK klicken...")
        clicked = config_select_usb_ok(pids)
        if not clicked:
            print("  FEHLER: OK konnte nicht geklickt werden")
            # Dismiss and retry
            dismiss_all_dialogs(pids, timeout=3)
            time.sleep(2)
            continue

        # Step 5: Wait for identification cycle
        print("Schritt 5: Warte auf Identifikations-Zyklus (~15s)...")
        t0 = time.time()
        result = wait_for_cycle_end(timeout=60)
        elapsed = time.time() - t0
        print(f"  Ergebnis: {result} (nach {elapsed:.1f}s)")

        # Step 6: Check WinOLS state
        print("Schritt 6: WinOLS Status prüfen...")
        time.sleep(2)
        responding = is_winols_responding(pids)
        lines = log_tail(5)
        print(f"  Responding: {responding}")
        for l in lines[-3:]:
            print(f"  Log: {l}")

        if result == 'success':
            print("\n✓ ERFOLG: EP2 Commands erkannt! Load/Disconnect aktiv!")
            print("  Bitte prüfe WinOLS - Load sollte jetzt funktionieren.")
            input("  Drücke Enter für nächsten Cycle oder Ctrl+C zum Beenden...")
        elif result == 'uninit':
            print(f"\n  Zyklus komplett nach {elapsed:.1f}s. Nächster Cycle...")
            time.sleep(3)
        else:
            print(f"\n  Timeout nach {elapsed:.1f}s. Retry...")
            time.sleep(3)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nBeendet.")
