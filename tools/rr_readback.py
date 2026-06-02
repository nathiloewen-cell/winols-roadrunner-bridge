"""
Roadrunner EPROM Readback via D2XX (TTL adapter FT232R)
Reads back data that was written by the WinOLS bridge.
"""
import ctypes, os, sys, time

FTDLL = r"C:\Windows\System32\ftd2xx.dll"  # 64-bit for Python 64-bit
RR_BAUD = 921600

def load_ft():
    ft = ctypes.WinDLL(FTDLL)
    return ft

def ft_open_sn(ft, sn=b"BGB9J82D"):
    h = ctypes.c_void_p()
    r = ft.FT_OpenEx(ctypes.c_char_p(sn), 1, ctypes.byref(h))  # FT_OPEN_BY_SERIAL_NUMBER=1
    if r != 0:
        # Try by index
        for i in range(4):
            r = ft.FT_Open(i, ctypes.byref(h))
            if r == 0 and h.value:
                print(f"  Opened by index {i}")
                break
    return h if r == 0 else None

def ft_config(ft, h):
    ft.FT_SetBitMode(h, 0, 0)       # reset to UART
    ft.FT_SetBaudRate(h, RR_BAUD)
    ft.FT_SetDataCharacteristics(h, 8, 0, 0)  # 8N1
    ft.FT_SetFlowControl(h, 0, 0, 0)
    ft.FT_SetLatencyTimer(h, 2)
    ft.FT_SetTimeouts(h, 1500, 1500)
    ft.FT_ClrDtr(h)
    ft.FT_ClrRts(h)
    ft.FT_Purge(h, 3)  # RX+TX

def ft_write(ft, h, data):
    buf = (ctypes.c_ubyte * len(data))(*data)
    written = ctypes.c_ulong(0)
    ft.FT_Write(h, buf, len(data), ctypes.byref(written))
    return written.value

def ft_read(ft, h, n, timeout_ms=2000):
    """Read up to n bytes with timeout."""
    ft.FT_SetTimeouts(h, timeout_ms, timeout_ms)
    buf = (ctypes.c_ubyte * n)()
    got = ctypes.c_ulong(0)
    ft.FT_Read(h, buf, n, ctypes.byref(got))
    return bytes(buf[:got.value])

def rr_init(ft, h):
    """Send 56 56 version request + init."""
    ft.FT_Purge(h, 3)
    ft_write(ft, h, [0x56, 0x56])
    time.sleep(0.3)
    resp = ft_read(ft, h, 16, 1000)
    print(f"  56 56 response ({len(resp)} bytes): {resp.hex()}")
    if not resp or resp[-1] != 0x52:
        return False
    # init6
    ft_write(ft, h, [0x48, 0x52, 0x07, 0x00, 0x01, 0xA2])
    time.sleep(0.1)
    r2 = ft_read(ft, h, 8, 500)
    print(f"  init6 response: {r2.hex()}")
    # chip config x2
    for _ in range(2):
        ft_write(ft, h, [0x4E, 0x53, 0xA1])
        time.sleep(0.1)
        ft_read(ft, h, 10, 500)
    return True

def rr_read_block(ft, h, block_nr):
    """Read 256 bytes from Roadrunner at block_nr*256.
    Try multiple read command formats."""
    addr = block_nr * 256
    addr_hi = (addr >> 8) & 0xFF
    addr_lo = addr & 0xFF

    # Try format 1: R [addr_hi][addr_lo][size_hi][size_lo] (big-endian size)
    formats = [
        ("R+addr+size_BE",    [0x52, addr_hi, addr_lo, 0x01, 0x00]),
        ("R+addr+size_LE",    [0x52, addr_hi, addr_lo, 0x00, 0x01]),
        ("r+addr+size_BE",    [0x72, addr_hi, addr_lo, 0x01, 0x00]),
        ("R+addr_only",       [0x52, addr_hi, addr_lo]),
        ("BF_addr_size",      [0xBF, addr_hi, addr_lo, 0x01, 0x00]),
        ("R+addr+count_100",  [0x52, addr_hi, addr_lo, 0x00, 0x00, 0x01, 0x00]),
    ]
    for name, cmd in formats:
        ft.FT_Purge(h, 3)
        time.sleep(0.05)
        ft_write(ft, h, cmd)
        time.sleep(0.1)
        resp = ft_read(ft, h, 260, 1500)
        print(f"  Format {name}: {resp[:8].hex() if resp else 'empty'} ({len(resp)} bytes)")
        if len(resp) >= 10:
            return resp[:256]
    return None

def main():
    print(f"Roadrunner Readback Tool")
    print(f"Loading {FTDLL}...")
    ft = load_ft()

    # Enumerate
    ndev = ctypes.c_ulong(0)
    ft.FT_CreateDeviceInfoList(ctypes.byref(ndev))
    print(f"D2XX devices: {ndev.value}")
    for i in range(ndev.value):
        flags = ctypes.c_ulong()
        typ = ctypes.c_ulong()
        iid = ctypes.c_ulong()
        loc = ctypes.c_ulong()
        sn = ctypes.create_string_buffer(64)
        desc = ctypes.create_string_buffer(64)
        h_tmp = ctypes.c_void_p()
        ft.FT_GetDeviceInfoDetail(i, ctypes.byref(flags), ctypes.byref(typ),
            ctypes.byref(iid), ctypes.byref(loc), sn, desc, ctypes.byref(h_tmp))
        print(f"  [{i}] SN={sn.value} desc={desc.value} flags=0x{flags.value:X}")

    print("\nOpening TTL adapter (FT232R BGB9J82D)...")
    h = ft_open_sn(ft)
    if not h:
        print("FAILED to open device")
        return

    print("Configuring at 921600 baud...")
    ft_config(ft, h)

    print("Running init (56 56)...")
    if not rr_init(ft, h):
        print("Init FAILED — Roadrunner not responding")
        ft.FT_Close(h)
        return

    print("\nReading block 0 (bytes 0x0000-0x00FF)...")
    data = rr_read_block(ft, h, 0)
    if data:
        print(f"  Read {len(data)} bytes")
        print(f"  [0:16] = {data[:16].hex()}")
        print(f"  [16:32] = {data[16:32].hex()}")
        # Save to file
        out = r"C:\dev\winols-roadrunner-bridge\tools\rr_readback_block0.bin"
        with open(out, 'wb') as f:
            f.write(data)
        print(f"  Saved to {out}")
    else:
        print("  Read FAILED / no data")

    # Read first 4 blocks (1KB)
    print("\nReading blocks 0-3 (first 1KB)...")
    all_data = b""
    for blk in range(4):
        d = rr_read_block(ft, h, blk)
        if d:
            all_data += d
            print(f"  Block {blk}: {len(d)} bytes, first 4: {d[:4].hex()}")
        else:
            print(f"  Block {blk}: no data")
            break

    if all_data:
        out2 = r"C:\dev\winols-roadrunner-bridge\tools\rr_readback_1kb.bin"
        with open(out2, 'wb') as f:
            f.write(all_data)
        print(f"\nSaved {len(all_data)} bytes to {out2}")

    ft.FT_Close(h)
    print("Done.")

if __name__ == "__main__":
    main()
