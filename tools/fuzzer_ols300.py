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
ID_PACKET   = r"C:\dev\winols-roadrunner-bridge\tools\id_packet.bin"
LOG_FILE    = r"C:\dev\winols-roadrunner-bridge\tools\fuzzer_results.txt"
PACKET_SIZE = 448
WAIT_SEC    = 4   # seconds to wait after WinOLS starts before checking

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

def start_winols():
    kill_winols()
    proc = subprocess.Popen([WINOLS_EXE])
    time.sleep(WAIT_SEC)
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
def run_test(candidate):
    """Write packet, start WinOLS, check status. Returns (status_text, accepted)."""
    p = make_packet_candidate(candidate)
    with open(ID_PACKET, 'wb') as f:
        f.write(p)

    proc = start_winols()
    pid  = proc.pid
    status = read_status_bar(pid, timeout=5.0)
    kill_winols()

    accepted = status and any(k in status for k in (
        'OLS300', 'Simulator', 'loaded', 'online', 'ready'
    )) and 'No OLS' not in status

    return status or "(none)", accepted


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
