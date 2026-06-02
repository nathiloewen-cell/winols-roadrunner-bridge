"""
Phase 1 Fuzzer - vollautomatisch mit gelernter Klick-Sequenz.

Bekannte WinOLS-Dialoge (Reihenfolge laut User):
  Optional: 1. Konfigurationsdatei defekt -> Nein
  Optional: 2. Fehlerbericht senden       -> Nicht senden
  Optional: 3. Willkommen bei WinOLS      -> Weiter (mehrfach) -> Fertig
  Immer:    4. Plugin-Konflikt            -> OK
  Test:     5. Sonstiges -> Konfiguration -> Hardware -> OK
"""
import subprocess, time, os, json, ctypes, ctypes.wintypes
import win32gui, win32con, win32com.client

WINOLS    = r"C:\Users\Nates\WinOLS_Bridge\ols_32on32.exe"
LOG       = r"C:\Users\Nates\AppData\Local\Temp\winols_wdapi.log"
RESP_FILE = os.path.join(os.environ["TEMP"], "ols300_2030_resp.bin")
RESULTS   = r"C:\dev\winols-roadrunner-bridge\tools\phase1_results.json"

# ── Dialog Handler ────────────────────────────────────────────────────────────

DIALOG_RULES = [
    # (partial title, button to click, priority)
    ("Konfigurationsdatei", "Nein",         10),
    ("ols-",                "Nein",         10),  # error codes like ols-02c2
    ("Fehlerbericht",       "Nicht senden", 10),
    ("Willkommen",          "Weiter",        5),  # click Weiter multiple times
    ("Willkommen",          "Fertig",        5),  # then Fertig
    ("Plugin",              "OK",            9),
    ("Konflikt",            "OK",            9),
    ("Tipp des Tages",      "OK",            8),   # Tip of the day
    ("Tipp",                "OK",            8),
    ("update",              "Schlie",        3),  # WinOLS update nag
    ("hasn",                "Schlie",        3),
]

_watcher_active = False
_watcher_thread = None

def _dismiss_one():
    """Scan all windows once and dismiss any known dialogs. Returns count dismissed."""
    count = 0
    try:
        wins = []
        def cb(h, _):
            if win32gui.IsWindowVisible(h):
                wins.append(h)
        win32gui.EnumWindows(cb, None)

        for h in wins:
            try:
                cls   = win32gui.GetClassName(h)
                title = win32gui.GetWindowText(h)
                if not title: continue

                btns = []
                def bc(bh, _):
                    bt = win32gui.GetWindowText(bh)
                    if bt and len(bt) < 80: btns.append((bh, bt))
                try: win32gui.EnumChildWindows(h, bc, None)
                except: pass

                dismissed = False
                # Try rules
                for partial, target, prio in sorted(DIALOG_RULES, key=lambda x: -x[2]):
                    if partial.lower() not in title.lower(): continue
                    for bh, bt in btns:
                        if target.lower() in bt.lower():
                            win32gui.SetForegroundWindow(h)
                            win32gui.PostMessage(bh, win32con.WM_LBUTTONDOWN, 0, 0)
                            win32gui.PostMessage(bh, win32con.WM_LBUTTONUP,   0, 0)
                            print(f"  [dialog] '{title[:35]}' -> '{bt}'")
                            count += 1
                            dismissed = True
                            time.sleep(0.2)
                            break
                    if dismissed: break

                # Generic Nein fallback for any unknown dialog
                if not dismissed and cls == '#32770' and btns:
                    for bh, bt in btns:
                        if any(x in bt.lower() for x in ['nein','nicht senden','cancel']):
                            win32gui.SetForegroundWindow(h)
                            win32gui.PostMessage(bh, win32con.WM_LBUTTONDOWN, 0, 0)
                            win32gui.PostMessage(bh, win32con.WM_LBUTTONUP,   0, 0)
                            print(f"  [dialog-fallback] '{title[:35]}' -> '{bt}'")
                            count += 1
                            time.sleep(0.2)
                            break
            except: pass
    except: pass
    return count

def find_and_dismiss_dialogs():
    return _dismiss_one()

import threading as _threading

def start_dialog_watcher():
    """Background thread that continuously dismisses dialogs every 0.8s."""
    global _watcher_active, _watcher_thread
    _watcher_active = True
    def _loop():
        while _watcher_active:
            try: _dismiss_one()
            except: pass
            time.sleep(0.8)
    _watcher_thread = _threading.Thread(target=_loop, daemon=True)
    _watcher_thread.start()

def stop_dialog_watcher():
    global _watcher_active
    _watcher_active = False

def wait_for_main_window(timeout=20):
    """Wait until WinOLS main window is visible (not a dialog)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        wins = []
        def cb(h, _):
            if not win32gui.IsWindowVisible(h): return
            t = win32gui.GetWindowText(h)
            c = win32gui.GetClassName(h)
            if "WinOLS" in t and "Afx" in c:
                wins.append(h)
        try: win32gui.EnumWindows(cb, None)
        except: pass
        if wins: return wins[0]
        time.sleep(0.5)
    return None

def open_config_hardware():
    """Open Konfiguration via WM_COMMAND(32827), navigate to Hardware tab, click OK."""
    # Find WinOLS main window
    wins = []
    def cb(h, _):
        if not win32gui.IsWindowVisible(h): return
        t = win32gui.GetWindowText(h)
        c = win32gui.GetClassName(h)
        if "WinOLS" in t and "Afx" in c: wins.append((h, t))
    try: win32gui.EnumWindows(cb, None)
    except: pass
    if not wins: return False

    hwnd, title = wins[0]

    # Direct WM_COMMAND to open Konfiguration (ID 32827 confirmed)
    KONFIGURATION_CMD = 32827
    # Ensure WinOLS has focus before sending command
    win32gui.ShowWindow(hwnd, 9)   # SW_RESTORE
    win32gui.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    win32gui.PostMessage(hwnd, win32con.WM_COMMAND, KONFIGURATION_CMD, 0)
    time.sleep(1.5)  # give dialog time to open

    # Find the Konfiguration dialog (may be called Konfiguration or other name)
    dlg = None
    def find_dlg(h, _):
        nonlocal dlg
        if not win32gui.IsWindowVisible(h): return
        if win32gui.GetClassName(h) not in ('#32770','TForm','TBForm','TCustomForm'): return
        t = win32gui.GetWindowText(h)
        if t and t not in (title, "WinOLS"):
            dlg = h  # take first non-main dialog
    try: win32gui.EnumWindows(find_dlg, None)
    except: pass
    if not dlg:
        # Try again after a bit more wait
        time.sleep(1.0)
        try: win32gui.EnumWindows(find_dlg, None)
        except: pass

    if not dlg:
        print("  Konfiguration dialog not found!")
        return False

    print(f"  Konfiguration dialog open: {win32gui.GetWindowText(dlg)!r}")

    # Navigate to Hardware tab using Ctrl+Tab
    win32gui.SetForegroundWindow(dlg)
    time.sleep(0.3)
    shell = win32com.client.Dispatch("WScript.Shell")
    shell.AppActivate(win32gui.GetWindowText(dlg))
    time.sleep(0.3)

    # Ctrl+Tab to next tab (Hardware is 2nd tab after Colours)
    shell.SendKeys("^{TAB}")
    time.sleep(0.4)

    # Click OK
    btns = []
    def find_ok(bh, _):
        bt = win32gui.GetWindowText(bh)
        if bt in ("OK", "&OK"): btns.append(bh)
    try: win32gui.EnumChildWindows(dlg, find_ok, None)
    except: pass

    if btns:
        win32gui.PostMessage(btns[0], win32con.WM_LBUTTONDOWN, 0, 0)
        win32gui.PostMessage(btns[0], win32con.WM_LBUTTONUP, 0, 0)
        print("  Clicked OK")
    else:
        shell.SendKeys("{ENTER}")
        print("  Sent ENTER for OK")

    time.sleep(0.5)
    return True

# ── Measurement ───────────────────────────────────────────────────────────────

def get_log_size():
    try: return os.path.getsize(LOG)
    except: return 0

def get_cpu():
    r = subprocess.run(
        ["wmic","process","where","name='ols_32on32.exe'","get",
         "KernelModeTime,UserModeTime"],
        capture_output=True, text=True, timeout=5)
    total = 0
    for line in r.stdout.strip().split('\n')[1:]:
        parts = line.strip().split()
        if len(parts) == 2:
            try: total += int(parts[0]) + int(parts[1])
            except: pass
    return total / 10000000.0

def check_2030(log_before):
    try:
        with open(LOG, 'r', errors='replace') as f: c = f.read()
        return "EP2 IN 8b (20 30) FUZZER:" in c[log_before:]
    except: return False

def write_resp(resp):
    with open(RESP_FILE, 'wb') as f: f.write(bytes(resp))

def graceful_kill():
    wins = []
    def cb(h, _):
        t = win32gui.GetWindowText(h)
        c = win32gui.GetClassName(h)
        if "WinOLS" in t and "Afx" in c: wins.append(h)
    try: win32gui.EnumWindows(cb, None)
    except: pass
    for h in wins:
        win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
    time.sleep(2.5)
    subprocess.run(["taskkill","/F","/IM","ols_32on32.exe"], capture_output=True)
    time.sleep(1.0)

# ── Single test run ───────────────────────────────────────────────────────────

def run_one_test(resp_bytes):
    resp_hex = ' '.join(f'{b:02X}' for b in resp_bytes)
    print(f"\n{'='*50}")
    print(f"Test: [{resp_hex}]")
    write_resp(resp_bytes)

    # Start dialog watcher FIRST (handles all popups automatically)
    start_dialog_watcher()

    # Start WinOLS
    subprocess.Popen([WINOLS])
    print("  WinOLS gestartet, Dialog-Watcher aktiv...")

    # Wait for main window (watcher handles all startup dialogs)
    hwnd = wait_for_main_window(timeout=25)
    if not hwnd:
        print("  WinOLS Hauptfenster nicht gefunden!")
        stop_dialog_watcher()
        graceful_kill()
        return None

    print("  Hauptfenster bereit.")
    time.sleep(2.0)  # extra settle time

    # Measure baseline
    log_before = get_log_size()
    cpu_before = get_cpu()

    # STOP watcher before opening Config (it would dismiss Config dialog!)
    stop_dialog_watcher()
    time.sleep(0.5)

    # Open Config -> Hardware -> OK (triggers 20 30)
    print("  Oeffne Config -> Hardware...")
    ok = open_config_hardware()
    if not ok:
        print("  Config konnte nicht geoeffnet werden!")

    # Measure result after 10 seconds (watcher handles any dialogs during measurement)
    print("  Messe 10s...")
    time.sleep(10)

    # Watcher already stopped before Config, no need to stop again
    cpu_after  = get_cpu()
    cpu_delta  = (cpu_after - cpu_before) / 10.0
    got_2030   = check_2030(log_before)
    no_hang    = cpu_delta < 0.35

    r2 = subprocess.run(["tasklist","/FI","IMAGENAME eq ols_32on32.exe"],
                        capture_output=True, text=True)
    running = "ols_32on32.exe" in r2.stdout

    result = {
        "resp":        resp_hex,
        "resp_bytes":  list(resp_bytes),
        "cpu_per_sec": round(cpu_delta, 2),
        "no_hang":     no_hang,
        "got_2030":    got_2030,
        "still_running": running,
        "success":     no_hang and got_2030,
    }
    status = "OK" if no_hang else "HANG"
    print(f"  [{status}] CPU/s={cpu_delta:.2f} | no_hang={no_hang} | 20_30={got_2030}")

    graceful_kill()
    return result

# ── Main ──────────────────────────────────────────────────────────────────────

def load_results():
    try:
        with open(RESULTS) as f: return json.load(f)
    except: return {"results": [], "successes": []}

def save_results(data):
    with open(RESULTS, 'w') as f: json.dump(data, f, indent=2)

CANDIDATES = []
for b0 in [0x00,0x01,0x02,0x03,0x04,0x05,0x06,0x07,0x08,
           0x0A,0x0F,0x10,0x14,0x18,0x1C,0x20,
           0x40,0x42,0x44,0x48,0x4F,0x55,0x80,0xAA,0xFF]:
    CANDIDATES.append([b0,0,0,0,0,0,0,0])
CANDIDATES += [
    [0x01,0x01,0,0,0,0,0,0], [0x01,0x02,0,0,0,0,0,0],
    [0x01,0x04,0,0,0,0,0,0], [0x01,0x08,0,0,0,0,0,0],
    [0x02,0x01,0,0,0,0,0,0], [0x04,0x01,0,0,0,0,0,0],
    [0x52,0x01,0x04,0x55,0x01,0x01,0x0F,0xBD],
    [0x01,0x00,0x08,0,0,0,0,0],
    [0x01,0x00,0,0,0x01,0,0,0],
]

if __name__ == "__main__":
    data = load_results()
    tested = {r['resp'] for r in data['results'] if isinstance(r.get('resp'), str)}
    todo = [c for c in CANDIDATES
            if (' '.join(f'{b:02X}' for b in c)) not in tested]

    print(f"Phase 1 Fuzzer — {len(todo)} Tests ausstehend von {len(CANDIDATES)} gesamt")
    print(f"Ergebnis-Datei: {RESULTS}")
    print()

    for resp in todo:
        result = run_one_test(resp)
        if result is None:
            continue
        data['results'].append(result)
        if result['success'] or (result['no_hang'] and result['got_2030']):
            data['successes'].append(result)
            print(f"\n  *** KANDIDAT GEFUNDEN: [{result['resp']}] ***")
        save_results(data)
        time.sleep(2)

    print(f"\n{'='*50}")
    print(f"FERTIG. {len(data['results'])} Tests, {len(data['successes'])} Erfolge.")
    for s in data['successes']:
        print(f"  [{s['resp']}] cpu={s['cpu_per_sec']}")
    if not data['successes']:
        no_hangs = [r for r in data['results'] if r.get('no_hang') and r.get('got_2030')]
        if no_hangs:
            print("Kandidaten (kein Hang + 20 30 empfangen):")
            for r in no_hangs: print(f"  [{r['resp']}] cpu={r['cpu_per_sec']}")
