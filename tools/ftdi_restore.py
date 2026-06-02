"""
ftdi_restore.py - Program FTDI FT232R EEPROM via WinUSB using vendor requests.
Restores original Roadrunner configuration (VID=0x0403, PID=0x6001).

FT232R EEPROM protocol (via USB vendor requests):
- Read:  bmRequestType=0xC0, bRequest=0x90, wValue=0, wIndex=addr → 2 bytes
- Write: bmRequestType=0x40, bRequest=0x91, wValue=word, wIndex=addr
"""

import ctypes, ctypes.wintypes as wt, struct, time, sys

k32 = ctypes.windll.kernel32

# WinUSB API
winusb = ctypes.windll.winusb

DIGCF_PRESENT         = 0x0002
DIGCF_DEVICEINTERFACE = 0x0010

class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("InterfaceClassGuid", ctypes.c_byte * 16),
                ("Flags", wt.DWORD), ("Reserved", ctypes.POINTER(ctypes.c_ulong))]

class SP_DEVICE_INTERFACE_DETAIL_DATA_W(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("DevicePath", ctypes.c_wchar * 512)]

class WINUSB_SETUP_PACKET(ctypes.Structure):
    _fields_ = [("RequestType", ctypes.c_ubyte), ("Request", ctypes.c_ubyte),
                ("Value", wt.USHORT), ("Index", wt.USHORT), ("Length", wt.USHORT)]

# GUID for WinUSB (generic WinUSB interface GUID for FTDI-WinUSB)
# VID_0547&PID_3000 uses this GUID from the wdreg INF
WINUSB_GUID_STR = "{A5DCBF10-6530-11D2-901F-00C04FB951ED}"  # USB device class

def find_device(vid, pid):
    """Find WinUSB device path for VID/PID."""
    import subprocess, json
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Get-PnpDevice | Where-Object {{ $_.DeviceID -match 'VID_{vid:04X}&PID_{pid:04X}' }} | Select-Object -ExpandProperty DeviceID"],
        capture_output=True, text=True)
    device_id = r.stdout.strip()
    if not device_id:
        print(f"Device VID={vid:04X}/PID={pid:04X} not found!")
        return None
    print(f"Found: {device_id}")

    # Get the device path via SetupDi
    setupapi = ctypes.windll.setupapi

    # WinUSB GUID for our device (from wdreg INF)
    GUID_DEVINTERFACE_USB_DEVICE = (ctypes.c_byte * 16)(
        0x10, 0xbf, 0xdc, 0xa5, 0x30, 0x65, 0xd2, 0x11,
        0x90, 0x1f, 0x00, 0xc0, 0x4f, 0xb9, 0x51, 0xed)

    hDevInfo = setupapi.SetupDiGetClassDevsW(
        ctypes.byref(GUID_DEVINTERFACE_USB_DEVICE), None, None,
        DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)

    if hDevInfo == wt.HANDLE(-1).value:
        print("SetupDiGetClassDevs failed")
        return None

    idx = 0
    while True:
        did = SP_DEVICE_INTERFACE_DATA()
        did.cbSize = ctypes.sizeof(did)
        if not setupapi.SetupDiEnumDeviceInterfaces(hDevInfo, None,
            ctypes.byref(GUID_DEVINTERFACE_USB_DEVICE), idx, ctypes.byref(did)):
            break

        # Get path length
        needed = wt.DWORD(0)
        setupapi.SetupDiGetDeviceInterfaceDetailW(hDevInfo, ctypes.byref(did),
            None, 0, ctypes.byref(needed), None)

        detail = SP_DEVICE_INTERFACE_DETAIL_DATA_W()
        detail.cbSize = 8  # 32-bit: 4+4=8 or use 6
        setupapi.SetupDiGetDeviceInterfaceDetailW(hDevInfo, ctypes.byref(did),
            ctypes.byref(detail), ctypes.sizeof(detail), None, None)

        path = detail.DevicePath
        if f"vid_{vid:04x}&pid_{pid:04x}".lower() in path.lower():
            setupapi.SetupDiDestroyDeviceInfoList(hDevInfo)
            return path
        idx += 1

    setupapi.SetupDiDestroyDeviceInfoList(hDevInfo)
    return None

def winusb_control_transfer(handle, req_type, request, value, index, data=None, length=0):
    """Send a USB control transfer via WinUSB."""
    pkt = WINUSB_SETUP_PACKET()
    pkt.RequestType = req_type
    pkt.Request = request
    pkt.Value = value
    pkt.Index = index
    pkt.Length = length if data is None else len(data)

    transferred = wt.ULONG(0)
    if data is None:
        buf = ctypes.create_string_buffer(length or 2)
        ok = winusb.WinUsb_ControlTransfer(handle, pkt, buf, pkt.Length,
                                            ctypes.byref(transferred), None)
        return ok, bytes(buf[:transferred.value])
    else:
        buf = ctypes.create_string_buffer(bytes(data))
        ok = winusb.WinUsb_ControlTransfer(handle, pkt, buf, pkt.Length,
                                            ctypes.byref(transferred), None)
        return ok, transferred.value

def ftdi_read_eeprom_word(winusb_handle, addr):
    """Read a 16-bit word from FTDI EEPROM at address addr."""
    ok, data = winusb_control_transfer(winusb_handle,
        0xC0,   # bmRequestType: vendor, device, device-to-host
        0x90,   # bRequest: FTDI EEPROM read
        0,      # wValue
        addr,   # wIndex = EEPROM address
        None, 2)
    if ok and len(data) == 2:
        return struct.unpack('<H', data)[0]
    return None

def ftdi_write_eeprom_word(winusb_handle, addr, word):
    """Write a 16-bit word to FTDI EEPROM at address addr."""
    ok, transferred = winusb_control_transfer(winusb_handle,
        0x40,   # bmRequestType: vendor, device, host-to-device
        0x91,   # bRequest: FTDI EEPROM write
        word,   # wValue = data word
        addr,   # wIndex = EEPROM address
        b'')
    return ok

def calculate_checksum(words):
    """FT232R EEPROM checksum: XOR all words with 0xAAAA."""
    chk = 0xAAAA
    for i in range(len(words) - 1):
        chk ^= words[i]
        chk = ((chk << 1) | (chk >> 15)) & 0xFFFF
    return chk

def main():
    VID = 0x0547
    PID = 0x3000

    print(f"FTDI EEPROM Restore Tool")
    print(f"Target: VID=0x0547/PID=0x3000 → VID=0x0403/PID=0x6001")
    print()

    # Find device path
    device_path = find_device(VID, PID)
    if not device_path:
        print("ERROR: Device not found via SetupDi.")
        print("Make sure the Roadrunner is connected and has WinUSB driver.")
        sys.exit(1)
    print(f"Device path: {device_path}")

    # Open device with CreateFile
    h_device = k32.CreateFileW(device_path,
        0xC0000000,  # GENERIC_READ | GENERIC_WRITE
        0x3, None, 3,  # OPEN_EXISTING
        0x00000080, None)  # FILE_ATTRIBUTE_NORMAL

    if h_device == wt.HANDLE(-1).value:
        print(f"CreateFile failed: {k32.GetLastError()}")
        sys.exit(1)
    print(f"Device handle: 0x{h_device:08X}")

    # Initialize WinUSB
    winusb_handle = ctypes.c_void_p()
    if not winusb.WinUsb_Initialize(h_device, ctypes.byref(winusb_handle)):
        print(f"WinUsb_Initialize failed: {k32.GetLastError()}")
        k32.CloseHandle(h_device)
        sys.exit(1)
    print("WinUSB initialized!")

    # Read current EEPROM
    print("\nReading current EEPROM...")
    words = []
    for addr in range(0x40):  # FT232R has 128 bytes = 64 words
        w = ftdi_read_eeprom_word(winusb_handle, addr)
        if w is None:
            print(f"  Read failed at addr {addr}")
            break
        words.append(w)

    print(f"  Read {len(words)} words")
    if len(words) >= 3:
        vid_cur = words[1]
        pid_cur = words[2]
        print(f"  Current VID=0x{vid_cur:04X} PID=0x{pid_cur:04X}")

    # Program new VID/PID
    print("\nProgramming VID=0x0403, PID=0x6001...")

    NEW_VID = 0x0403
    NEW_PID = 0x6001

    # Word 1 = VID, Word 2 = PID (FT232R layout)
    if len(words) < 3:
        print("ERROR: Could not read EEPROM words!")
        winusb.WinUsb_Free(winusb_handle)
        k32.CloseHandle(h_device)
        sys.exit(1)

    # Modify the words array
    words_new = list(words)
    words_new[1] = NEW_VID
    words_new[2] = NEW_PID

    # Recalculate checksum (last word)
    chk = calculate_checksum(words_new[:-1])
    words_new[-1] = chk

    # Write VID
    print(f"  Writing VID=0x{NEW_VID:04X} at addr 1...")
    if not ftdi_write_eeprom_word(winusb_handle, 1, NEW_VID):
        print(f"  Write VID failed: {k32.GetLastError()}")
    else:
        print("  VID written OK")

    # Write PID
    print(f"  Writing PID=0x{NEW_PID:04X} at addr 2...")
    if not ftdi_write_eeprom_word(winusb_handle, 2, NEW_PID):
        print(f"  Write PID failed: {k32.GetLastError()}")
    else:
        print("  PID written OK")

    # Write checksum
    print(f"  Writing checksum 0x{chk:04X} at addr {len(words)-1}...")
    ftdi_write_eeprom_word(winusb_handle, len(words)-1, chk)

    # Verify
    print("\nVerifying...")
    vid_new = ftdi_read_eeprom_word(winusb_handle, 1)
    pid_new = ftdi_read_eeprom_word(winusb_handle, 2)
    print(f"  Verified: VID=0x{vid_new:04X} PID=0x{pid_new:04X}")

    if vid_new == NEW_VID and pid_new == NEW_PID:
        print("\nSUCCESS! EEPROM programmed with original Roadrunner config.")
        print("Please DISCONNECT and RECONNECT the Roadrunner.")
        print("Windows will install FTDI VCP driver and create a COM port.")
    else:
        print("\nERROR: Verification failed!")

    winusb.WinUsb_Free(winusb_handle)
    k32.CloseHandle(h_device)

if __name__ == '__main__':
    main()
