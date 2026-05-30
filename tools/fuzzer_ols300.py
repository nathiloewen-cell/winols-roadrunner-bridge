#!/usr/bin/env python3
"""
fuzzer_ols300.py — OLS300 identification packet fuzzer.

Writes different 448-byte patterns to tools/id_packet.bin, restarts WinOLS,
and reads the status bar via Windows UIAutomation to check if WinOLS accepts
the identification.

Target: WinOLS status bar changes from "No OLS-Module" to
        "OLS300-Simulator is loaded and ready."

Usage: python fuzzer_ols300.py [--start PATTERN_INDEX]
"""

import subprocess, time, ctypes, ctypes.wintypes as wt, struct, os, sys, itertools

WINOLS_EXE  = r"C:\Program Files\EVC\WinOLS\ols_32on32.exe"
# Open a project so WinOLS triggers hardware init (WDU_Init)
WINOLS_PROJECT = r"C:\Users\Nates\Documents\Evc\WinOLS\10000.ols"
ID_PACKET   = r"C:\dev\winols-roadrunner-bridge\tools\id_packet.bin"
LOG_FILE    = r"C:\dev\winols-roadrunner-bridge\tools\fuzzer_results.txt"
PACKET_SIZE = 448
WAIT_SEC    = 10  # seconds to wait after WinOLS starts before checking

user32 = ctypes.windll.user32
k32    = ctypes.windll.kernel32

# ── Status bar reading via UIAutomation / SendMessage ────────────────────
def get_winols_status(pid):
    """Read the WinOLS status bar text."""
    found = []
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def enum_cb(hwnd, p):
        p2 = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p2))
        if p2.value == pid:
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            if buf.value:
                found.append((hwnd, buf.value))
        return True
    user32.EnumWindows(CB(enum_cb), 0)

    # Try reading from all windows
    for hwnd, title in found:
        if any(k in title for k in ('OLS-Module', 'OLS300', 'Simulator', 'No CS', 'loaded')):
            return title

    # Try WM_GETTEXT on child windows with status-bar-like content
    WM_GETTEXTLENGTH = 0x000E
    WM_GETTEXT       = 0x000D
    for hwnd, _ in found[:20]:
        child = user32.FindWindowExW(hwnd, None, None, None)
        while child:
            ln = user32.SendMessageW(child, WM_GETTEXTLENGTH, 0, 0)
            if 8 < ln < 200:
                buf = ctypes.create_unicode_buffer(ln + 2)
                user32.SendMessageW(child, WM_GETTEXT, ln + 1, buf)
                txt = buf.value
                if any(k in txt for k in ('OLS', 'No CS', 'loaded', 'Simulator')):
                    return txt
            child = user32.FindWindowExW(hwnd, child, None, None)
    return None


def read_status_bar(pid, timeout=5.0):
    """Poll for status bar text for up to timeout seconds."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        txt = get_winols_status(pid)
        if txt:
            return txt
        time.sleep(0.3)
    return "(no status found)"


# ── WinOLS lifecycle ──────────────────────────────────────────────────────
def kill_winols():
    subprocess.run(["taskkill", "/F", "/IM", "ols_32on32.exe"],
                   capture_output=True)
    time.sleep(0.8)

def dismiss_ols11a():
    """Click 'Nein' on the OLS-11a crash recovery dialog if it appears."""
    for _ in range(20):  # poll for 4 seconds
        hwnd = user32.FindWindowW("TForm", None)
        if not hwnd:
            hwnd = user32.FindWindowW(None, None)

        # Find any dialog with "Nein" button from any WinOLS window
        nein_found = [False]
        CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
        def find_nein(h, p):
            buf = ctypes.create_unicode_buffer(32)
            user32.GetWindowTextW(h, buf, 32)
            if buf.value in ('Nein', 'No', '&Nein'):
                user32.SendMessageW(h, 0x0201, 0, 0)  # WM_LBUTTONDOWN
                user32.SendMessageW(h, 0x0202, 0, 0)  # WM_LBUTTONUP
                nein_found[0] = True
            return True
        # Enumerate all top-level windows
        all_wins = []
        def get_all(h, p):
            p2 = wt.DWORD(0)
            if h: all_wins.append(h)
            return True
        user32.EnumWindows(CB(get_all), 0)
        for w in all_wins:
            user32.EnumChildWindows(w, CB(find_nein), 0)
            if nein_found[0]:
                return True
        time.sleep(0.2)
    return False

VK_ALT   = 0x12
VK_MENU  = 0x12

def send_keys(key_sequence):
    """Send keyboard input (list of VK codes to press sequentially)."""
    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk",wt.WORD),("wScan",wt.WORD),("dwFlags",wt.DWORD),
                    ("time",wt.DWORD),("dwExtraInfo",ctypes.c_ulong_p if hasattr(ctypes,'c_ulong_p') else ctypes.c_void_p)]
    class INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("ki",KEYBDINPUT)]
        _anonymous_ = ("u",)
        _fields_ = [("type",wt.DWORD),("u",_U)]
    for vk in key_sequence:
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.ki.wVk = vk
        inp.ki.dwFlags = 0
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        time.sleep(0.05)
        inp.ki.dwFlags = KEYEVENTF_KEYUP
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        time.sleep(0.05)

def trigger_hardware_init():
    """Open Configuration dialog via keyboard to trigger WDU_Init.
    WinOLS: Miscellaneous → Configuration → Hardware → Simulator → USB → OK
    The USB (OLS300) port must already be selected from previous manual setup."""
    # Find WinOLS window to give it focus
    pid_list = []
    def ecb(hwnd, p):
        p2 = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p2))
        for pid in pid_list:
            if p2.value == pid:
                user32.SetForegroundWindow(hwnd)
                return False
        return True
    # Get WinOLS PIDs
    import subprocess as sp
    r = sp.run(['tasklist', '/FI', 'IMAGENAME eq ols_32on32.exe', '/FO', 'CSV'],
               capture_output=True, text=True)
    for line in r.stdout.splitlines()[1:]:
        parts = line.strip('"').split('","')
        if len(parts) >= 2:
            try: pid_list.append(int(parts[1]))
            except: pass
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    user32.EnumWindows(CB(ecb), 0)
    time.sleep(0.3)

    # Alt+M (Miscellaneous), then C (Configuration), then Enter
    # This opens the Configuration dialog in WinOLS
    # VK codes: Alt=0x12, M=0x4D, C=0x43, Enter=0x0D
    user32.keybd_event(0x12, 0, 0, 0)      # Alt down
    user32.keybd_event(0x4D, 0, 0, 0)      # M down
    user32.keybd_event(0x4D, 0, 2, 0)      # M up
    user32.keybd_event(0x12, 0, 2, 0)      # Alt up
    time.sleep(0.5)
    user32.keybd_event(0x43, 0, 0, 0)      # C down
    user32.keybd_event(0x43, 0, 2, 0)      # C up
    time.sleep(1.0)
    # Config dialog should be open, navigate to OK button
    user32.keybd_event(0x0D, 0, 0, 0)      # Enter (OK)
    user32.keybd_event(0x0D, 0, 2, 0)

def start_winols():
    kill_winols()
    cmd = [WINOLS_EXE]
    if os.path.exists(WINOLS_PROJECT):
        cmd.append(WINOLS_PROJECT)
    proc = subprocess.Popen(cmd)
    # Handle OLS-11a recovery dialog
    time.sleep(1.5)
    dismiss_ols11a()
    time.sleep(3)  # Wait for WinOLS to load
    # Trigger WDU_Init by simulating Config dialog OK
    trigger_hardware_init()
    time.sleep(WAIT_SEC)  # Wait for polling to start and ID packet to be served
    return proc

# ── Packet generators ─────────────────────────────────────────────────────
def make_packet_zeros():
    return bytearray(PACKET_SIZE)

def make_packet_sync_start(b0=0x55, b1=0xAA, rest=0x00):
    p = bytearray([rest] * PACKET_SIZE)
    p[0] = b0; p[1] = b1
    return p

def make_packet_with_string_at(offset, s="OLS821", fill=0x00):
    p = bytearray([fill] * PACKET_SIZE)
    for i, c in enumerate(s.encode('ascii')):
        if offset + i < PACKET_SIZE:
            p[offset + i] = c
    return p

def make_packet_candidate(cfg):
    """Build a packet from a config dict."""
    p = bytearray([cfg.get('fill', 0)] * PACKET_SIZE)
    for offset, value in cfg.get('bytes', {}).items():
        if offset < PACKET_SIZE:
            p[offset] = value
    for offset, s in cfg.get('strings', {}).items():
        for i, c in enumerate(s.encode('ascii')):
            if offset + i < PACKET_SIZE:
                p[offset + i] = c
    return p

# ── Test candidates ───────────────────────────────────────────────────────
CANDIDATES = [
    # 0: All zeros
    {"name": "all_zeros", "bytes": {}},
    # 1: 0x55 0xAA sync (from firmware 0x7C00)
    {"name": "sync_55AA", "bytes": {0: 0x55, 1: 0xAA}},
    # 2: OLS821 at offset 0
    {"name": "OLS821_off0", "strings": {0: "OLS821"}},
    # 3: OLS821 at offset 80 (0x50)
    {"name": "OLS821_off80", "strings": {0x50: "OLS821"}},
    # 4: 0x55 0xAA + OLS821 at offset 2
    {"name": "sync+OLS821_off2", "bytes": {0: 0x55, 1: 0xAA}, "strings": {2: "OLS821"}},
    # 5: 0x55 0xAA + OLS821 at offset 10
    {"name": "sync+OLS821_off10", "bytes": {0: 0x55, 1: 0xAA}, "strings": {10: "OLS821"}},
    # 6: version=1 at byte 0, OLS821 at 4
    {"name": "v1+OLS821_off4", "bytes": {0: 0x01, 1: 0x00}, "strings": {4: "OLS821"}},
    # 7: length byte at 0 = 0x1C (28), type byte = 0x30
    {"name": "len28_type30", "bytes": {0: 0x1C, 1: 0x30}},
    # 8: 0x30 prefix (Cypress FX2 common)
    {"name": "0x30_prefix", "bytes": {0: 0x30}},
    # 9: 0xAA 0x55 reverse sync
    {"name": "sync_AA55", "bytes": {0: 0xAA, 1: 0x55}},
    # 10: byte 0 = 0x0F (matches EP2 IN response for command 3 in firmware)
    {"name": "type_0F", "bytes": {0: 0x0F}},
    # 11: 0x55 0xAA + 0x0F at 2 (sync + type)
    {"name": "sync+type0F", "bytes": {0: 0x55, 1: 0xAA, 2: 0x0F}},
    # 12: All 0xFF
    {"name": "all_FF", "fill": 0xFF, "bytes": {}},
    # 13: 0x55 0xAA + length byte = 0x40 (64) at offset 3
    {"name": "sync+len64", "bytes": {0: 0x55, 1: 0xAA, 3: 0x40}},
    # 14: Repeating sync pattern (64 copies of 0x55 0xAA)
    {"name": "repeating_sync", "bytes": {i*2: 0x55 for i in range(32)} | {i*2+1: 0xAA for i in range(32)}},
    # 15: OLS300 at offset 0 (full product name)
    {"name": "OLS300_off0", "strings": {0: "OLS300"}},
    # 16: OLS300 at offset 2 with sync
    {"name": "sync+OLS300_off2", "bytes": {0: 0x55, 1: 0xAA}, "strings": {2: "OLS300"}},
]


# ── Main fuzzer loop ──────────────────────────────────────────────────────
WDAPI_LOG = r"C:\Users\Nates\AppData\Local\Temp\winols_wdapi.log"

def get_log_tail(n=30):
    """Read last n lines from wdapi log with shared access."""
    try:
        h = k32.CreateFileW(WDAPI_LOG, 0x80000000, 7, None, 3, 0, None)
        if h == -1: return []
        sz = k32.GetFileSize(h, None)
        if sz == 0: k32.CloseHandle(h); return []
        # Read last 4KB
        off = max(0, sz - 4096)
        k32.SetFilePointer(h, off, None, 0)
        buf = ctypes.create_string_buffer(4096)
        rd = wt.DWORD(0)
        k32.ReadFile(h, buf, 4096, ctypes.byref(rd), None)
        k32.CloseHandle(h)
        return buf.raw[:rd.value].decode('utf-8', 'replace').splitlines()[-n:]
    except:
        return []

def get_ols_struct_status(pid):
    """Read OLS module struct status field at 0x04E022D0."""
    try:
        h = k32.OpenProcess(0x0010, False, pid)
        if not h: return None
        buf = ctypes.create_string_buffer(4)
        rd = ctypes.c_size_t(0)
        k32.ReadProcessMemory(h, ctypes.c_void_p(0x04E022D0), buf, 4, ctypes.byref(rd))
        k32.CloseHandle(h)
        return struct.unpack_from('<I', buf, 0)[0] if rd.value >= 4 else None
    except:
        return None

def run_test(candidate):
    """Write packet, start WinOLS, check indicators. Returns (info_str, accepted)."""
    p = make_packet_candidate(candidate)
    with open(ID_PACKET, 'wb') as f:
        f.write(p)

    # Get log size before
    log_lines_before = len(get_log_tail(200))

    proc = start_winols()
    pid  = proc.pid
    time.sleep(WAIT_SEC + 1)  # extra wait for communication

    # Check indicators:
    # 1. Any TX writes on EP2 OUT (pipe=0x02) → WinOLS sent a command back
    new_log = get_log_tail(200)
    has_tx = any('TX' in l and 'Transfer' in l for l in new_log)
    has_ep2_write = any('pipe=2' in l or 'pipe=0x02' in l for l in new_log)

    # 2. OLS module struct status changed from 0
    struct_status = get_ols_struct_status(pid)

    # 3. Status bar attempt
    status_txt = get_winols_status(pid)

    kill_winols()

    # Acceptance criteria (strict - no false positives from proxy startup messages):
    # WinOLS sent a WRITE on EP2 OUT (pipe=2) → started command exchange
    # This means WinOLS advanced past identification phase
    accepted = has_ep2_write

    info = (f"TX={has_tx} EP2OUT={has_ep2_write} struct=0x{struct_status or 0:08X} "
            f"status={status_txt or '?'} log_lines={len(new_log)}")
    return info, accepted


def main():
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    print(f"OLS300 Identification Packet Fuzzer")
    print(f"ID packet file: {ID_PACKET}")
    print(f"Starting at candidate {start}")
    print()

    with open(LOG_FILE, 'a') as log:
        log.write(f"\n=== Fuzzer run started ===\n")

        for i, cand in enumerate(CANDIDATES[start:], start):
            name  = cand.get('name', f'candidate_{i}')
            print(f"[{i:3d}/{len(CANDIDATES)-1}] Testing: {name}")

            status, accepted = run_test(cand)
            result = "*** ACCEPTED ***" if accepted else "rejected"
            print(f"         Status: {status[:60]}")
            print(f"         Result: {result}")
            print()

            log.write(f"[{i}] {name}: {result} | status={status}\n")
            log.flush()

            if accepted:
                print(f"\n{'='*60}")
                print(f"SUCCESS! Candidate {i} ({name}) was accepted!")
                print(f"ID packet saved to: {ID_PACKET}")
                print(f"{'='*60}")
                return

    print("All candidates tested. None accepted.")
    print(f"Results saved to: {LOG_FILE}")


if __name__ == '__main__':
    main()
