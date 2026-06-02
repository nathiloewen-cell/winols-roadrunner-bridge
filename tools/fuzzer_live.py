#!/usr/bin/env python3
"""
fuzzer_live.py — Live-memory OLS300 identification packet fuzzer.

Operates on a RUNNING WinOLS that is already in the EP6 polling loop.
Uses WriteProcessMemory to change g_id_packet between tests.

Detection logic:
- ACCEPTED: no WDU_Uninit appears within 5s after writing candidate
- REJECTED: WDU_Uninit appears in log within 5s (current default behavior)
"""

import ctypes, ctypes.wintypes as wt, time, subprocess, sys

WINOLS_LOG  = r"C:\Users\Nates\AppData\Local\Temp\winols_wdapi.log"
RESULTS_LOG = r"C:\dev\winols-roadrunner-bridge\tools\fuzzer_live_results.txt"
PACKET_SIZE = 448
k32 = ctypes.windll.kernel32

# ── Win32 types for VirtualQueryEx ───────────────────────────────────────
class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress",       ctypes.c_void_p),
        ("AllocationBase",    ctypes.c_void_p),
        ("AllocationProtect", wt.DWORD),
        ("RegionSize",        ctypes.c_size_t),
        ("State",             wt.DWORD),
        ("Protect",           wt.DWORD),
        ("Type",              wt.DWORD),
    ]

MEM_COMMIT  = 0x1000
PAGE_GUARD  = 0x100

# ── Find WinOLS PID ───────────────────────────────────────────────────────
def get_winols_pid():
    r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq ols_32on32.exe', '/FO', 'CSV'],
                       capture_output=True, text=True)
    for line in r.stdout.splitlines()[1:]:
        parts = line.strip('"').split('","')
        if len(parts) >= 2:
            try: return int(parts[1])
            except: pass
    return None

# ── Scan ALL committed memory for pattern ─────────────────────────────────
def scan_memory(pid, pattern):
    """Walk all committed, readable pages for pattern. Return first match addr."""
    h = k32.OpenProcess(0x001F0FFF, False, pid)
    if not h:
        print(f"OpenProcess failed: {k32.GetLastError()}")
        return None

    mbi   = MEMORY_BASIC_INFORMATION()
    addr  = 0
    found = None

    while addr < 0x80000000:
        mbi_size = ctypes.sizeof(mbi)
        ret = k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), mbi_size)
        if not ret:
            addr += 0x1000
            continue

        skip = (mbi.State != MEM_COMMIT) or (mbi.Protect & PAGE_GUARD) or (mbi.Protect == 0)
        rsize = mbi.RegionSize if mbi.RegionSize else 0x1000

        if not skip and rsize > 0:
            chunk_size = min(rsize, 0x40000)  # read up to 256 KB at a time
            off = 0
            while off < rsize and found is None:
                read_sz  = min(chunk_size, rsize - off)
                buf      = ctypes.create_string_buffer(read_sz)
                rd       = ctypes.c_size_t(0)
                base_ptr = ctypes.c_void_p(addr + off)
                if k32.ReadProcessMemory(h, base_ptr, buf, read_sz, ctypes.byref(rd)) and rd.value:
                    data = bytes(buf[:rd.value])
                    idx  = data.find(pattern)
                    if idx != -1:
                        found = (addr + off + idx)
                off += chunk_size

        if found is not None:
            break
        addr += rsize

    k32.CloseHandle(h)
    return found

# ── WriteProcessMemory wrapper ─────────────────────────────────────────────
def write_memory(pid, addr, data):
    h = k32.OpenProcess(0x001F0FFF, False, pid)
    if not h: return False
    buf = ctypes.create_string_buffer(data)
    wr  = ctypes.c_size_t(0)
    ok  = k32.WriteProcessMemory(h, ctypes.c_void_p(addr), buf, len(data), ctypes.byref(wr))
    k32.CloseHandle(h)
    return bool(ok)

# ── Log helpers ──────────────────────────────────────────────────────────
def log_tail(n=50):
    try:
        h = k32.CreateFileW(WINOLS_LOG, 0x80000000, 7, None, 3, 0, None)
        if h == wt.HANDLE(-1).value: return []
        sz = k32.GetFileSize(h, None)
        off = max(0, sz - n * 80)
        k32.SetFilePointer(h, off, None, 0)
        buf = ctypes.create_string_buffer(n * 80)
        rd  = wt.DWORD(0)
        k32.ReadFile(h, buf, n * 80, ctypes.byref(rd), None)
        k32.CloseHandle(h)
        return buf.raw[:rd.value].decode('utf-8', 'replace').splitlines()
    except:
        return []

def log_size():
    try:
        h = k32.CreateFileW(WINOLS_LOG, 0x80000000, 7, None, 3, 0, None)
        sz = k32.GetFileSize(h, None)
        k32.CloseHandle(h)
        return sz
    except: return 0

def wait_for_polling(timeout=25):
    """Wait until new WDU_Transfer (ID packet) entries appear in log."""
    deadline = time.time() + timeout
    prev_sz = log_size()
    while time.time() < deadline:
        time.sleep(0.5)
        lines = log_tail(10)
        if any('ID packet' in l for l in lines[-5:]):
            return True
    return False

def test_acceptance(timeout=5.0):
    """
    After writing a candidate, watch the log for 'timeout' seconds.
    Returns:
      'accepted' — no WDU_Uninit appeared, polling continued
      'rejected' — WDU_Uninit appeared
      'timeout'  — no activity at all (lost contact)
    """
    t0 = time.time()
    baseline_lines = set(log_tail(30))
    saw_transfer = False
    while time.time() - t0 < timeout:
        time.sleep(0.3)
        lines = log_tail(30)
        new = [l for l in lines if l not in baseline_lines]
        for l in new:
            if 'ID packet' in l: saw_transfer = True
            if 'WDU_Uninit' in l:
                return 'rejected'
        # Check EP2 OUT (command from WinOLS — definitive acceptance)
        if any('TX' in l and 'pipe=2' in l for l in new):
            return 'accepted'
    if not saw_transfer:
        return 'timeout'
    return 'accepted'

# ── Packet candidates ─────────────────────────────────────────────────────
def build_candidates():
    c = []

    def add(name, p):
        arr = bytearray(PACKET_SIZE)
        arr[:len(p)] = p[:PACKET_SIZE]
        c.append((name, arr))

    # --- Group 1: plain magic bytes ---
    add("all_zeros",  b'\x00' * PACKET_SIZE)
    add("all_FF",     b'\xFF' * PACKET_SIZE)
    add("55AA_zeros", b'\x55\xaa' + b'\x00' * (PACKET_SIZE-2))
    add("AAFF_zeros", b'\xaa\xff' + b'\x00' * (PACKET_SIZE-2))
    add("A55A_zeros", b'\xa5\x5a' + b'\x00' * (PACKET_SIZE-2))

    # --- Group 2: OLS string at offset 0, 2, 4, 8 ---
    for off in [0, 2, 4, 8, 0x10, 0x20, 0x40]:
        p = bytearray(PACKET_SIZE)
        p[0]=0x55; p[1]=0xAA
        s = b"OLS821"
        for i,b_ in enumerate(s):
            if off+i < PACKET_SIZE: p[off+i] = b_
        add(f"55AA+OLS821@{off}", bytes(p))

    # --- Group 3: version word at [0:4] ---
    for v in [0x00000001, 0x00000003, 0x00000008, 0x08210000, 0x00210800,
              0x0001FFFF, 0x55AA0003, 0x55AA0008, 0x55AA0821]:
        p = bytearray(PACKET_SIZE)
        p[0:4] = v.to_bytes(4, 'big')
        add(f"dword={v:08X}", bytes(p))

    # --- Group 4: fill whole packet with repeating byte ---
    for v in [0x01, 0x02, 0x55, 0xAA]:
        add(f"fill_{v:02X}", bytes([v]*PACKET_SIZE))

    # --- Group 5: packet starts with chip ID / JEDEC byte ---
    # Common EPROM JEDEC IDs: AM27C256=0x01, M27C512=0x20, 27C040=0xAD
    for jedec in [0x01, 0x04, 0x20, 0xAD, 0xC2, 0x89]:
        p = bytearray(PACKET_SIZE)
        p[0]=0x55; p[1]=0xAA; p[2]=jedec
        add(f"JEDEC_{jedec:02X}", bytes(p))

    # --- Group 6: status byte patterns ---
    # Bit 0 = connected, Bit 1 = chip present, etc.
    for st in [0x01, 0x03, 0x07, 0x0F, 0x1F, 0x3F, 0x7F, 0xFF]:
        p = bytearray(PACKET_SIZE)
        p[0] = st
        add(f"status={st:02X}", bytes(p))

    # --- Group 7: try first byte = 1..16 ---
    for v in range(1, 17):
        p = bytearray(PACKET_SIZE)
        p[0] = v
        add(f"byte0={v}", bytes(p))

    return c

# ── Main ──────────────────────────────────────────────────────────────────
def main():
    pid = get_winols_pid()
    if not pid:
        print("WinOLS nicht gefunden. Bitte zuerst starten und Config-Dialog OK klicken.")
        sys.exit(1)

    print(f"WinOLS PID={pid}")

    # --- Find g_id_packet in process memory ---
    # Log shows first bytes are 55 AA 4F 4C (55 AA + "OL")
    print("Suche g_id_packet im Prozessspeicher ...")
    search_patterns = [
        bytes([0x55,0xAA,0x4F,0x4C,0x53,0x38,0x32,0x31,0,0,0,0,0,0,0,0]),  # 55 AA OLS821\0\0...
        bytes([0x55,0xAA,0x4F,0x4C,0x53,0x38,0x32,0x31]),                    # shorter
        bytes([0x55,0xAA] + [0]*14),                                           # 55 AA + zeros
    ]

    id_addr = None
    for pat in search_patterns:
        id_addr = scan_memory(pid, pat)
        if id_addr:
            print(f"g_id_packet gefunden: 0x{id_addr:08X} (pattern={pat[:4].hex()})")
            break

    if not id_addr:
        print("g_id_packet NICHT gefunden. Fuzzer funktioniert nur wenn WinOLS gerade EP6 liest.")
        sys.exit(1)

    # Verify we found the right location
    h = k32.OpenProcess(0x001F0FFF, False, pid)
    verify_buf = ctypes.create_string_buffer(16)
    rd = ctypes.c_size_t(0)
    k32.ReadProcessMemory(h, ctypes.c_void_p(id_addr), verify_buf, 16, ctypes.byref(rd))
    k32.CloseHandle(h)
    print(f"Verifikation: {bytes(verify_buf[:rd.value]).hex()}")

    candidates = build_candidates()
    print(f"\nTeste {len(candidates)} Kandidaten ...")
    print("Erkennnung: kein WDU_Uninit in 5s = AKZEPTIERT | WDU_Uninit erscheint = ABGELEHNT\n")

    with open(RESULTS_LOG, 'a') as log_f:
        log_f.write(f"\n=== Live-Fuzzer {time.strftime('%H:%M:%S')} ===\n")

        for i, (name, packet) in enumerate(candidates):
            print(f"[{i:3d}/{len(candidates)}] {name:<35}", end=" ", flush=True)

            # Wait for next polling window
            if not wait_for_polling(timeout=25):
                print("TIMEOUT - WinOLS hat aufgehört zu pollen!")
                break

            # Write candidate to process memory
            ok = write_memory(pid, id_addr, bytes(packet))
            if not ok:
                print("WriteMemory FEHLER")
                continue

            # Watch what happens
            result = test_acceptance(timeout=5.0)

            sym = "*** AKZEPTIERT ***" if result == 'accepted' else result
            print(sym)
            log_f.write(f"[{i}] {name}: {result}\n")
            log_f.flush()

            if result == 'accepted':
                print(f"\nErfolgreich! Paket '{name}' wird gespeichert.")
                with open(r"C:\dev\winols-roadrunner-bridge\tools\id_packet.bin", 'wb') as f:
                    f.write(bytes(packet))
                # Restore to accepted packet in memory too
                write_memory(pid, id_addr, bytes(packet))
                print("id_packet.bin aktualisiert.")
                return

    print(f"\nAlle Kandidaten getestet. Ergebnisse: {RESULTS_LOG}")

if __name__ == '__main__':
    main()
