"""
eeprom_program.py - Program FT232R EEPROM via WinDriver wdapi1660_32.dll
Changes VID=0547/PID=3000 → VID=0403/PID=6001 (original Roadrunner)
"""
import ctypes, ctypes.wintypes as wt, time, sys, struct

k32 = ctypes.windll.kernel32

# Load wdapi1660_32.dll
wdapi = ctypes.WinDLL(r"C:\Windows\SysWOW64\wdapi1660_32.dll")

# Function signatures
class WDU_MATCH_TABLE(ctypes.Structure):
    _fields_ = [
        ("wVendorId",        wt.WORD),
        ("wProductId",       wt.WORD),
        ("bDeviceClass",     wt.BYTE),
        ("bDeviceSubClass",  wt.BYTE),
        ("bInterfaceClass",  wt.BYTE),
        ("bInterfaceSubClass",wt.BYTE),
        ("bInterfaceProtocol",wt.BYTE),
    ]

g_device_handle = ctypes.c_void_p(None)

# Callback: called when device is found
@ctypes.CFUNCTYPE(wt.BOOL, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
def attach_cb(hDev, pDevInfo, pUserData):
    global g_device_handle
    g_device_handle = ctypes.c_void_p(hDev)
    print(f"  Device attached! handle=0x{hDev:08X}")
    return True

class WDU_EVENT_TABLE(ctypes.Structure):
    _fields_ = [
        ("pfDeviceAttach",  ctypes.c_void_p),
        ("pfDeviceDetach",  ctypes.c_void_p),
        ("pUserData",       ctypes.c_void_p),
    ]

def ftdi_control(hDev, req_type, request, value, index, buf=None, length=0):
    """Send USB control transfer via wdapi WDU_TransferDefaultPipe."""
    # Setup packet: [bmRequestType, bRequest, wValue_lo, wValue_hi, wIndex_lo, wIndex_hi, wLength_lo, wLength_hi]
    setup = (ctypes.c_ubyte * 8)(
        req_type, request,
        value & 0xFF, (value >> 8) & 0xFF,
        index & 0xFF, (index >> 8) & 0xFF,
        (length) & 0xFF, ((length) >> 8) & 0xFF
    )
    is_read = 1 if (req_type & 0x80) else 0
    data_buf = (ctypes.c_ubyte * max(length, 1))()
    transferred = wt.ULONG(0)

    wdapi.WDU_TransferDefaultPipe.restype = wt.DWORD
    wdapi.WDU_TransferDefaultPipe.argtypes = [
        ctypes.c_void_p,  # hDevice
        wt.DWORD,          # fRead
        wt.DWORD,          # dwOptions
        ctypes.c_void_p,   # pBuffer
        wt.DWORD,          # dwBufferSize
        ctypes.POINTER(wt.DWORD),  # pdwBytesTransferred
        ctypes.POINTER(ctypes.c_ubyte),  # pSetupPacket
        wt.DWORD,          # dwTimeout
    ]

    r = wdapi.WDU_TransferDefaultPipe(
        hDev.value, is_read, 0,
        data_buf, length,
        ctypes.byref(transferred),
        setup,
        3000)

    return r, bytes(data_buf[:transferred.value])

def eeprom_read(hDev, addr):
    r, data = ftdi_control(hDev, 0xC0, 0x90, 0, addr, length=2)
    if r == 0 and len(data) == 2:
        return struct.unpack('<H', data)[0]
    return None

def eeprom_write(hDev, addr, word):
    r, _ = ftdi_control(hDev, 0x40, 0x91, word, addr)
    return r == 0

def main():
    print("=== FTDI EEPROM Programmer via WinDriver ===")
    print("VID=0547/PID=3000 → VID=0403/PID=6001")
    print()

    # Open WinDriver
    wdapi.WDC_DriverOpen.restype = wt.DWORD
    wdapi.WDC_DriverOpen.argtypes = [wt.DWORD, ctypes.c_char_p]
    r = wdapi.WDC_DriverOpen(0, b"12345abcde1234.license")
    print(f"WDC_DriverOpen: 0x{r:08X}", "OK" if r==0 else "FAILED")
    if r != 0: sys.exit(1)

    # Register for VID=0547/PID=3000
    match = WDU_MATCH_TABLE()
    match.wVendorId = 0x0547
    match.wProductId = 0x3000

    events = WDU_EVENT_TABLE()
    events.pfDeviceAttach = ctypes.cast(attach_cb, ctypes.c_void_p).value

    hDriver = ctypes.c_void_p(None)
    wdapi.WDU_Init.restype = wt.DWORD
    wdapi.WDU_Init.argtypes = [
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(WDU_MATCH_TABLE),
        wt.DWORD,
        ctypes.POINTER(WDU_EVENT_TABLE),
        ctypes.c_char_p,
        wt.DWORD
    ]
    r = wdapi.WDU_Init(
        ctypes.byref(hDriver),
        ctypes.byref(match), 1,
        ctypes.byref(events),
        b"12345abcde1234.license", 0)
    print(f"WDU_Init: 0x{r:08X}", "OK" if r==0 else "FAILED")
    if r != 0: sys.exit(1)

    # Wait for device
    print("Waiting for device...")
    for _ in range(30):
        if g_device_handle.value: break
        time.sleep(0.1)

    if not g_device_handle.value:
        print("ERROR: Device not found!")
        sys.exit(1)

    print(f"Device: 0x{g_device_handle.value:08X}")

    # Read current EEPROM
    print("\nReading EEPROM...")
    words = []
    for i in range(64):
        w = eeprom_read(g_device_handle, i)
        if w is None:
            print(f"  Read failed at {i}, stopping")
            break
        words.append(w)

    print(f"  Read {len(words)} words")
    if len(words) >= 3:
        print(f"  Current: VID=0x{words[1]:04X} PID=0x{words[2]:04X}")

    if len(words) < 3:
        print("ERROR: Cannot read enough EEPROM words")
        sys.exit(1)

    # Calculate new checksum
    NEW_VID, NEW_PID = 0x0403, 0x6001
    new_words = list(words)
    new_words[1] = NEW_VID
    new_words[2] = NEW_PID

    chk = 0xAAAA
    for i in range(len(new_words)-1):
        chk ^= new_words[i]
        chk = ((chk << 1) | (chk >> 15)) & 0xFFFF
    new_words[-1] = chk

    print(f"\nProgramming VID=0x{NEW_VID:04X} PID=0x{NEW_PID:04X}")
    print(f"  Writing word[1]=0x{NEW_VID:04X}...", end=" ")
    print("OK" if eeprom_write(g_device_handle, 1, NEW_VID) else "FAIL")

    print(f"  Writing word[2]=0x{NEW_PID:04X}...", end=" ")
    print("OK" if eeprom_write(g_device_handle, 2, NEW_PID) else "FAIL")

    print(f"  Writing checksum 0x{chk:04X}...", end=" ")
    print("OK" if eeprom_write(g_device_handle, len(words)-1, chk) else "FAIL")

    # Verify
    print("\nVerifying...")
    v1 = eeprom_read(g_device_handle, 1)
    v2 = eeprom_read(g_device_handle, 2)
    print(f"  VID=0x{v1:04X} PID=0x{v2:04X}")

    if v1 == NEW_VID and v2 == NEW_PID:
        print("\nSUCCESS! Now disconnect and reconnect the TTL adapter.")
        print("Windows will install FTDI VCP driver → COM port appears.")
    else:
        print(f"\nERROR: Got VID=0x{v1:04X} PID=0x{v2:04X}")

    wdapi.WDU_Uninit(hDriver)

if __name__ == "__main__":
    main()
