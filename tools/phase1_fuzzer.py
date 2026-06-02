"""
Phase 1 Fuzzer: Testet verschiedene 8-Byte-Responses fuer den 20 30 Befehl.
Ziel: Wert finden der WinOLS zu "OLS300 configured" bringt ohne Hang/Schleife.

Methode:
- Schreibt Response-Bytes nach %TEMP%\ols300_2030_resp.bin
- Startet WinOLS, klickt Config -> Hardware -> OK
- Misst CPU nach 8 Sekunden (niedrig = kein Hang = Erfolg)
- Liest Status-Bar-Text per UIAutomation
"""
import subprocess, time, os, struct, ctypes, ctypes.wintypes, sys
import winreg, json
from pathlib import Path

WINOLS = r"C:\Users\Nates\WinOLS_Bridge\ols_32on32.exe"
LOG    = r"C:\Users\Nates\AppData\Local\Temp\winols_wdapi.log"
RESP_FILE = os.path.join(os.environ.get("TEMP","C:\\Temp"), "ols300_2030_resp.bin")
RESULTS_FILE = r"C:\dev\winols-roadrunner-bridge\tools\phase1_results.json"

# WinOLS Config dialog coords (from previous sessions)
# Config -> Hardware -> USB OLS300 Only -> OK
# Use automation to click Config OK

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

def get_winols_cpu():
    """Get total CPU seconds for all ols_32on32 processes."""
    import subprocess
    r = subprocess.run(
        ["wmic","process","where","name='ols_32on32.exe'","get","KernelModeTime,UserModeTime"],
        capture_output=True, text=True, timeout=5
    )
    total = 0
    for line in r.stdout.strip().split('\n')[1:]:
        parts = line.strip().split()
        if len(parts) == 2:
            try: total += int(parts[0]) + int(parts[1])
            except: pass
    return total / 10000000.0  # convert 100ns to seconds

def kill_winols():
    """Graceful shutdown first (WM_CLOSE), then force kill after 3s."""
    try:
        import win32gui, win32con
        wins = []
        def cb(h, _):
            t = win32gui.GetWindowText(h)
            c = win32gui.GetClassName(h)
            if "WinOLS" in t and "Afx" in c:
                wins.append(h)
        win32gui.EnumWindows(cb, None)
        for h in wins:
            win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
        time.sleep(2.0)
    except: pass
    subprocess.run(["taskkill","/F","/IM","ols_32on32.exe"], capture_output=True)
    time.sleep(1.0)

def dismiss_winols_dialogs():
    """Dismiss ALL WinOLS startup dialogs:
    - 'Konfigurationsdatei defekt' -> click 'Nein'
    - 'Fehlerbericht senden' -> click 'Nicht senden'
    - 'WinOLS hasn't been updated' -> close
    """
    try:
        import win32gui, win32con
        # Buttons to click (in priority order): "Nicht senden", "Nein", "No", "Close"
        # "Nein"/"Nicht senden" = don't delete config / don't send report
        # "Weiter"/"Abbrechen" = wizard: click Weiter to proceed through setup wizard
        #   BUT: we want to CANCEL the wizard (Abbrechen), not step through it
        # UPDATE: user says click "Weiter" for welcome wizard
        # Priority: most specific first
        # "OK" for plugin conflict dialog (only if it's a small dialog, not main window)
        # "Nein" for config error (don't delete config)
        # "Nicht senden" for error report
        # "Weiter" for welcome wizard
        DISMISS_BUTTONS = [
            "Nicht senden", "Nicht Senden",          # error report dialog
            "Nein", "&Nein",                           # config delete: NO
            "Weiter >", "&Weiter >", "Weiter",         # welcome wizard: next
            "&OK", "OK",                               # plugin conflict: OK
            "No", "Abbrechen",
        ]
        for _ in range(10):
            time.sleep(0.8)
            clicked = False
            def find_all_windows(h, wins):
                if win32gui.IsWindowVisible(h):
                    wins.append(h)
            all_wins = []
            win32gui.EnumWindows(find_all_windows, all_wins)
            for h in all_wins:
                try:
                    txt = win32gui.GetWindowText(h)
                    # Skip main WinOLS window
                    if not txt or ("WinOLS 2." in txt and len(txt) < 20):
                        continue
                    # Check if it's a dialog (has buttons)
                    btns = []
                    def find_btn(bh, _):
                        bt = win32gui.GetWindowText(bh)
                        if bt: btns.append((bh, bt))
                    try: win32gui.EnumChildWindows(h, find_btn, None)
                    except: pass
                    for bh, bt in btns:
                        for dismiss in DISMISS_BUTTONS:
                            if dismiss.lower() in bt.lower():
                                win32gui.SetForegroundWindow(h)
                                win32gui.PostMessage(bh, win32con.WM_LBUTTONDOWN, 0, 0)
                                win32gui.PostMessage(bh, win32con.WM_LBUTTONUP,  0, 0)
                                clicked = True
                                print(f"  [dismiss] clicked '{bt}' in '{txt}'")
                                time.sleep(0.3)
                                break
                        if clicked: break
                    if clicked: break
                except: pass
    except Exception as e:
        pass  # silent fail

def start_winols():
    subprocess.Popen([WINOLS])
    # Multiple rounds of dialog dismissal during startup
    for _ in range(6):
        time.sleep(2.0)
        dismiss_winols_dialogs()
    time.sleep(3.0)  # extra wait for EP6 polling to start

def click_config_hardware_ok():
    """Click Miscellaneous -> Configuration -> Hardware tab -> OK via SendKeys."""
    import win32gui, win32con, win32api

    # Find WinOLS main window
    hwnd = win32gui.FindWindow(None, None)
    wins = []
    def enum_cb(h, _):
        t = win32gui.GetWindowText(h)
        if "WinOLS" in t and win32gui.IsWindowVisible(h):
            wins.append(h)
    win32gui.EnumWindows(enum_cb, None)

    if not wins:
        print("  WinOLS window not found")
        return False

    hwnd = wins[0]
    win32gui.SetForegroundWindow(hwnd)
    time.sleep(0.3)

    # Send Alt+M for Miscellaneous menu
    import win32com.client
    shell = win32com.client.Dispatch("WScript.Shell")
    shell.AppActivate("WinOLS")
    time.sleep(0.3)
    shell.SendKeys("%s")  # Alt+S = Sonstiges (German menu name for Miscellaneous)
    time.sleep(0.5)

    # Look for Configuration menu item
    shell.SendKeys("k")  # Konfiguration
    time.sleep(0.5)

    return True

def click_config_ok_via_mouse():
    """Click the Config OK button via physical mouse (known coordinates)."""
    import win32api, win32con
    # The Config dialog OK button was at approximately (737, 738) from previous sessions
    # But this might vary. We'll use a simpler approach: find the dialog and press Enter
    import win32gui

    # Find the config dialog
    config_hwnd = None
    def find_dialog(h, _):
        nonlocal config_hwnd
        t = win32gui.GetWindowText(h)
        if "Konfiguration" in t or "Configuration" in t or "Einstellung" in t:
            config_hwnd = h
    win32gui.EnumWindows(find_dialog, None)

    if config_hwnd:
        # Click OK button (usually the default button, Enter works)
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        shell.AppActivate(win32gui.GetWindowText(config_hwnd))
        time.sleep(0.2)
        shell.SendKeys("{ENTER}")
        return True
    return False

def get_status_bar_text():
    """Read WinOLS status bar text via accessibility."""
    try:
        import win32gui, win32con
        # Find status bar in WinOLS
        status_texts = []
        def find_status(h, _):
            cls = win32gui.GetClassName(h)
            if "StatusBar" in cls or "msctls_statusbar" in cls.lower():
                t = win32gui.GetWindowText(h)
                if t: status_texts.append(t)
        win32gui.EnumChildWindows(
            win32gui.FindWindow(None, None), find_status, None
        )
        return " | ".join(status_texts) if status_texts else ""
    except:
        return ""

def read_log_tail(n=20):
    """Read last n non-VEH lines from proxy log."""
    try:
        with open(LOG, 'r', errors='replace') as f:
            lines = f.readlines()
        result = [l.strip() for l in lines[-200:] if "VEH: bad write" not in l]
        return result[-n:]
    except:
        return []

def check_20_30_logged(before_size):
    """Check if 20 30 command was processed after before_size."""
    try:
        with open(LOG, 'r', errors='replace') as f:
            content = f.read()
        relevant = content[before_size:]
        if "EP2 IN 8b (20 30) FUZZER:" in relevant:
            return True
        return False
    except:
        return False

def get_log_size():
    try:
        return os.path.getsize(LOG)
    except:
        return 0

def write_response(resp_bytes):
    """Write 8-byte response to config file."""
    with open(RESP_FILE, 'wb') as f:
        f.write(bytes(resp_bytes))

def automate_config_hardware_ok():
    """Full automation: open Config dialog, select Hardware tab, click OK."""
    try:
        import win32gui, win32con, win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")

        # Activate WinOLS
        wins = []
        def enum(h, _):
            if "WinOLS" in win32gui.GetWindowText(h) and win32gui.IsWindowVisible(h):
                wins.append(h)
        win32gui.EnumWindows(enum, None)
        if not wins: return False

        win32gui.SetForegroundWindow(wins[0])
        time.sleep(0.5)

        # Open Miscellaneous -> Configuration
        shell.AppActivate("WinOLS")
        time.sleep(0.3)
        # Use menu: Miscellaneous (Alt+M or try German shortcut)
        # From previous work: the shortcut was specific
        shell.SendKeys("%s")  # Alt+S = Sonstiges menu
        time.sleep(0.4)
        shell.SendKeys("k")  # Konfiguration
        time.sleep(1.0)

        # In config dialog: select Hardware tab and click OK
        # Hardware tab shortcut or just press OK from current tab (Colours)
        shell.SendKeys("{ENTER}")
        time.sleep(0.5)
        return True
    except Exception as e:
        print(f"  Automation error: {e}")
        return False

def open_config_hardware():
    """Open Config and navigate to Hardware tab."""
    try:
        import win32gui, win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        wins = []
        def enum(h, _):
            if "WinOLS" in win32gui.GetWindowText(h) and win32gui.IsWindowVisible(h):
                wins.append(h)
        win32gui.EnumWindows(enum, None)
        if not wins: return False
        win32gui.SetForegroundWindow(wins[0])
        time.sleep(0.5)
        shell.AppActivate("WinOLS")
        time.sleep(0.3)
        # Menu navigation using known keyboard shortcuts
        shell.SendKeys("%e")  # Alt+E Miscellaneous
        time.sleep(0.5)
        shell.SendKeys("k")   # Konfiguration
        time.sleep(1.0)
        # Dialog open - now switch to Hardware tab
        # Tab index for Hardware: press Ctrl+Tab or click directly
        # From previous: the dialog has tabs, Hardware is accessible
        # Use Ctrl+Tab to cycle tabs until we find Hardware
        for _ in range(4):  # try up to 4 tabs
            # Check if "Hardware" tab visible
            shell.SendKeys("^{TAB}")
            time.sleep(0.2)
        # Actually, go back and use specific tab order
        # Reset: Shift+Tab multiple times, then Tab to Hardware
        shell.SendKeys("+^{TAB}")  # go to first tab
        time.sleep(0.3)
        shell.SendKeys("+^{TAB}")
        time.sleep(0.3)
        # Hardware tab is index 1 (0=Colours, 1=Hardware, ...)
        # Just click OK from Colours tab (don't navigate to Hardware)
        # Actually for Phase 1 we NEED the Hardware tab to trigger 20 30
        # Navigate using Alt+H if that's the shortcut, or just Ctrl+Tab once
        shell.SendKeys("^{TAB}")  # go to tab 2 (maybe Hardware)
        time.sleep(0.3)
        return True
    except Exception as e:
        print(f"  Config open error: {e}")
        return False

# ── Test candidates ──────────────────────────────────────────────────────────

def make_candidates():
    """Generate candidate 8-byte responses for 20 30."""
    candidates = []

    # Byte[0] variations (most important)
    for b0 in [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
               0x0A, 0x0C, 0x0F, 0x10, 0x14, 0x18, 0x1C, 0x1F, 0x20,
               0x40, 0x42, 0x44, 0x48, 0x4F, 0x55, 0x80, 0xAA, 0xFF]:
        candidates.append([b0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

    # Byte[0..1] variations
    for b0 in [0x01, 0x02, 0x04]:
        for b1 in [0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x40, 0xFF]:
            c = [b0, b1, 0, 0, 0, 0, 0, 0]
            if c not in candidates:
                candidates.append(c)

    # Full 8-byte patterns (from OLS300 protocol knowledge)
    candidates.extend([
        [0x01, 0x00, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00],  # byte[2]=chip type?
        [0x01, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00],  # byte[4]=1
        [0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
        [0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
        [0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
        [0x04, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
        [0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF],
        [0x52, 0x01, 0x04, 0x55, 0x01, 0x01, 0x0F, 0xBD],  # from UART init response!
    ])

    return candidates

# ── Main fuzzer loop ─────────────────────────────────────────────────────────

def run_test(resp_bytes, test_id):
    """Run one test iteration. Returns dict with results."""
    resp_hex = ' '.join(f'{b:02X}' for b in resp_bytes)
    print(f"\n[{test_id:3d}] Testing: {resp_hex}")

    # Write response config
    write_response(resp_bytes)

    # Start WinOLS
    kill_winols()
    log_size_before = get_log_size()
    start_winols()

    # CPU before Config OK
    cpu_before = get_winols_cpu()

    # Check if WinOLS is running
    r = subprocess.run(["tasklist","/FI","IMAGENAME eq ols_32on32.exe"],
                       capture_output=True, text=True)
    if "ols_32on32.exe" not in r.stdout:
        print("  WinOLS not running!")
        return {"resp": resp_bytes, "status": "not_running", "success": False}

    # Read log size before Config OK
    log_before = get_log_size()

    # Automate: open Config dialog and click OK from Hardware tab
    print("  Opening Config -> Hardware...")
    opened = open_config_hardware()
    if not opened:
        print("  Could not open config dialog")
        kill_winols()
        return {"resp": resp_bytes, "status": "automation_fail", "success": False}

    # Click OK
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        shell.AppActivate("WinOLS")
        time.sleep(0.3)
        shell.SendKeys("{ENTER}")
        print("  Clicked OK")
    except:
        pass

    # Wait and measure
    time.sleep(2)

    # Check if 20 30 was processed
    got_2030 = check_20_30_logged(log_before)

    # Measure CPU after 5 more seconds
    time.sleep(5)
    cpu_after = get_winols_cpu()
    cpu_delta = cpu_after - cpu_before
    cpu_per_sec = cpu_delta / 7.0  # 7 total seconds measured

    # Check WinOLS still running
    r2 = subprocess.run(["tasklist","/FI","IMAGENAME eq ols_32on32.exe"],
                        capture_output=True, text=True)
    still_running = "ols_32on32.exe" in r2.stdout

    # Read status bar
    status_text = get_status_bar_text()

    # Read log
    log_tail = read_log_tail(5)

    # Determine success:
    # - cpu_per_sec < 0.3 = no hang (good)
    # - "configured" or "loaded" in status = best
    # - 20 30 was processed
    no_hang = cpu_per_sec < 0.3
    configured = any(kw in status_text.lower()
                     for kw in ["geladen", "loaded", "konfiguriert", "configured", "ready"])

    result = {
        "resp": resp_hex,
        "resp_bytes": list(resp_bytes),
        "cpu_per_sec": round(cpu_per_sec, 2),
        "no_hang": no_hang,
        "got_2030": got_2030,
        "status_text": status_text,
        "configured": configured,
        "still_running": still_running,
        "success": no_hang and got_2030,
        "log_tail": log_tail,
    }

    print(f"  CPU/s={cpu_per_sec:.2f} | no_hang={no_hang} | 20_30={got_2030} | "
          f"status='{status_text[:40]}' | configured={configured}")

    kill_winols()
    time.sleep(1)

    return result

def main():
    print("=== Phase 1 Fuzzer: OLS300 20 30 Response ===")
    print(f"Proxy: {r'C:\\Users\\Nates\\WinOLS_Bridge\\wdapi1100.dll'}")
    print(f"Response file: {RESP_FILE}")

    candidates = make_candidates()
    print(f"Testing {len(candidates)} candidate responses\n")

    results = []
    successes = []

    try:
        for i, resp in enumerate(candidates):
            result = run_test(resp, i+1)
            results.append(result)

            if result.get("success") or result.get("configured"):
                successes.append(result)
                print(f"  *** POSSIBLE SUCCESS: {result['resp']} ***")

            # Save intermediate results
            with open(RESULTS_FILE, 'w') as f:
                json.dump({"results": results, "successes": successes}, f, indent=2)

    except KeyboardInterrupt:
        print("\nFuzzer interrupted by user")
    finally:
        kill_winols()

    # Summary
    print(f"\n=== RESULTS ({len(results)} tests) ===")
    print(f"Successes: {len(successes)}")
    for s in successes:
        print(f"  RESP=[{s['resp']}] cpu={s['cpu_per_sec']} status='{s['status_text'][:50]}'")

    if not successes:
        print("\nKein Erfolg — no_hang tests:")
        no_hangs = [r for r in results if r.get("no_hang") and r.get("got_2030")]
        for r in no_hangs[:5]:
            print(f"  RESP=[{r['resp']}] cpu={r['cpu_per_sec']}")

    print(f"\nResultate gespeichert: {RESULTS_FILE}")

if __name__ == "__main__":
    main()
