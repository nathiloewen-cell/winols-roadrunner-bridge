"""
crash_loop.py — Automated WinOLS crash detection loop.

Starts WinOLS, waits for crash dialog, reads the error address,
dismisses the dialog, reads the wdapi log, then reports.
Run from an admin terminal.
"""

import subprocess, time, ctypes, ctypes.wintypes as wt, os, re, sys

WINOLS  = r"C:\Program Files\EVC\WinOLS\ols_32on32.exe"
LOG     = os.path.expandvars(r"%TEMP%\winols_wdapi.log")
TIMEOUT = 20  # seconds to wait for crash dialog

user32   = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# ── Windows helpers ──────────────────────────────────────────────────────
def find_window(title_substr, timeout=TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnd = user32.FindWindowW(None, "Fehler")
        if hwnd:
            return hwnd
        time.sleep(0.2)
    return None

def get_window_text_all(hwnd):
    """Get text from all child static controls (labels) in a dialog."""
    texts = []
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    buf = ctypes.create_unicode_buffer(512)

    def enum_cb(child_hwnd, _):
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(child_hwnd, cls, 64)
        if cls.value in ("Static", "Button"):
            user32.GetWindowTextW(child_hwnd, buf, 512)
            if buf.value.strip():
                texts.append(buf.value.strip())
        return True

    user32.EnumChildWindows(hwnd, CB(enum_cb), 0)
    return texts

def click_ok(hwnd):
    """Find and click the OK button in a dialog."""
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    ok_hwnd = ctypes.c_void_p(0)

    def enum_cb(child, _):
        buf = ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(child, buf, 64)
        if buf.value.strip() in ("OK", "Ok"):
            ok_hwnd.value = child
            return False
        return True

    user32.EnumChildWindows(hwnd, CB(enum_cb), 0)
    if ok_hwnd.value:
        user32.SendMessageW(ok_hwnd.value, 0x0201, 0, 0)  # WM_LBUTTONDOWN
        user32.SendMessageW(ok_hwnd.value, 0x0202, 0, 0)  # WM_LBUTTONUP
        return True
    # Fallback: press Enter
    user32.SendMessageW(hwnd, 0x0100, 0x0D, 0)  # WM_KEYDOWN Enter
    return True

def read_log_tail(n=30):
    """Read last n lines from wdapi log."""
    try:
        with open(LOG, "r", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-n:])
    except Exception as e:
        return f"(log read error: {e})"

# ── Main loop ────────────────────────────────────────────────────────────
def run_once():
    print(f"\n{'='*60}")
    print("Starting WinOLS...")
    proc = subprocess.Popen([WINOLS])
    print(f"  PID: {proc.pid}")

    # Wait for crash dialog OR clean exit
    hwnd = find_window("Fehler", TIMEOUT)

    if not hwnd:
        # Check if process already exited
        rc = proc.poll()
        if rc is not None:
            print(f"  WinOLS exited (code {rc}) without crash dialog")
        else:
            print("  No crash dialog — WinOLS running OK")
            proc.terminate()
        return None

    # Read dialog text
    texts = get_window_text_all(hwnd)
    full_text = " | ".join(texts)
    print(f"\nCRASH DIALOG: {full_text}")

    # Extract crash address
    m = re.search(r"0x([0-9A-Fa-f]+)", full_text)
    crash_addr = m.group(1) if m else "unknown"

    # Also look for "read from" / "write to" address
    m2 = re.search(r"(?:read|write)\s+from\s+0x([0-9A-Fa-f]+)", full_text, re.IGNORECASE)
    access_addr = m2.group(1) if m2 else "?"
    print(f"  Code addr:   0x{crash_addr}")
    print(f"  Access addr: 0x{access_addr}  (= NULL + {int(access_addr,16) if access_addr!='?' else '?'})")

    # Dismiss dialog
    click_ok(hwnd)
    time.sleep(0.5)

    # Wait for process
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.terminate()

    # Read log
    print("\nLast log entries:")
    print(read_log_tail(20))

    return access_addr

# ── Entry point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    max_runs = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    print(f"WinOLS crash loop — up to {max_runs} runs")
    print(f"WinOLS: {WINOLS}")
    print(f"Log:    {LOG}")

    results = []
    for i in range(max_runs):
        print(f"\nRun {i+1}/{max_runs}")
        addr = run_once()
        results.append(addr)
        if addr is None:
            print("No crash — stopping loop")
            break
        time.sleep(1)

    print(f"\n{'='*60}")
    print("Summary of access addresses:")
    for j, a in enumerate(results, 1):
        if a:
            print(f"  Run {j}: 0x{a}  (offset {int(a,16)})")
