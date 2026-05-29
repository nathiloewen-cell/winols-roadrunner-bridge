# S2 — MoatesWare Protocol Documentation

Source: `C:\Program Files\EmUtility\EmUtility.exe` (248,832 bytes, 2012-12-07)  
Roadrunner USB device: **VID 0403 / PID B471** (FTDI FT232, custom PID)  
Interface: Windows COM port via `\\.\COM%i` (FTDI virtual serial port)

---

## Protocol Stack (4 layers)

```
┌─────────────────────────────────────────────────────┐
│  Layer 4 — RoadRunner (device identity & mode)      │
│  SetEmulationMode, GetEmulationMode, SetSerial       │
├─────────────────────────────────────────────────────┤
│  Layer 3 — MMAutoProm (high-level operations)        │
│  ReadBlock, WriteBlock, Trace, SetUSBBaud, passthrough│
├─────────────────────────────────────────────────────┤
│  Layer 2 — MoatesWare (bulk transport)              │
│  BulkRead, BulkWrite — 256-byte aligned, checksummed│
├─────────────────────────────────────────────────────┤
│  Layer 1 — MMSerial (COM port)                      │
│  ReadFile/WriteFile on \\.\COM%i                    │
└─────────────────────────────────────────────────────┘
```

---

## Layer 1 — MMSerial

Standard Windows serial port. FTDI D2XX emulates a COM port (FTDI VCP driver).

```
Open:   \\.\COM%i  (0 = autodetect)
        "MMSerial: Successfully opened %s"
        "MMSerial: %s opened at %i baud"

Baud:   Dynamic — starts at detection baud, then SetUSBBaud switches speed
        "MMSerial: Baud changed to %i"

Close:  "MMSerial: Port Closed"
        "MMAutoProm: COM Port closed."

Errors:
  "MMSerial: GetCommState Failed"
  "MMSerial: SetCommState Failed"
  "MMSerial: Open Port %s Failed"
```

---

## Layer 2 — MoatesWare (Bulk Transport)

### Rules
- **Block size and address MUST be divisible by 256**
- Single-byte checksum per packet (XOR or sum — exact algorithm TBD)
- Timeout-based handshake

### BulkRead
```
Request:  [CMD_BULK_READ] [addr_hi] [addr_lo] [size_hi] [size_lo]
Response: [data × N bytes] [checksum]

Errors:
  "MoatesWare: BulkRead failure. Size/Address must be divisible by 256."
  "MoatesWare: BulkRead requested on uninitialized port"
  "MoatesWare: BulkRead: Read timed-out after %i bytes. Expected %i bytes."
  "MoatesWare Bulk Read Error - invalid packet checksum. Expected %.2X, Received %.2X."
  "MoatesWare: Bulk Read Request initiated for %i bytes."
```

### BulkWrite
```
Request:  [CMD_BULK_WRITE] [addr_hi] [addr_lo] [size_hi] [size_lo] [data × N] [checksum]
Response: [ACK]

Alternative write path (bad checksum):
  "AP_E_ALT_WRITE_BAD_CHECKSUM"

Errors:
  "MoatesWare: BulkWrite failure. Size/Address must be divisible by 256."
  "MoatesWare: BulkWrite failure. Uninitialized Port."
  "MoatesWare: BulkWrite - Operation Canceled"
```

---

## Layer 3 — MMAutoProm (High-level Operations)

### Baud rate negotiation
```
"MMAutoProm: SetUSBBaud to %i, Force = %s SUCCEEDED"
"MMAutoProm: SetUSBBaud to %i, Force = %s FAILED with %s"
"MMAutoProm: Software data passthrough mode entry SUCCESS: %i baud"
```
Device starts at a low/default baud and switches to high-speed after handshake.

### ReadBlock / WriteBlock
```
"MMAutoProm ReadBlock Request initiated for %i bytes."
"MMAutoProm: ReadBlock - Operation Canceled"
"MMAutoProm: ReadBlock requested on uninitialized port"
"MMAutoProm: ReadBlock: Read timed-out after %i bytes. Expected %i bytes."
"MMAutoProm Read Error - invalid packet checksum. Expected %.2X, Received %.2X."
"MMAutoProm: WriteBlock - Operation Canceled"
"MMAutoProm: Slow Reading %i bytes"
"MMAutoProm: Slow writing %i bytes"
```

### Bank Management
```
Banks:
  Bank 0 — Primary emulation memory (64 KB)
  Bank 1 — Shadow (backup copy)
  Bank 2 — Verify (read-back verification)
  Bank 8 — Extended / Ostrich 4-MBit (512 KB), enabled with -large flag

Commands:
  "MMAutoProm: Get %s Bank Succeeded: Bank %i"
  "MMAutoProm: Get %s Bank Failed!"
  "MMAutoProm: Set %s Bank Succeeded: Bank %i"
  "MMAutoProm: Set %s Bank Failed!"

Verification messages:
  "MMAutoProm: Roadrunner verification failed in bank 2."
  "MMAutoProm: Shadow verification failed in bank 1."
```

### Verify
```
"MMAutoProm: %i-length Verify requested"
"MMAutoProm: SUCCESS! Verify succeeded with 0 differences"
"MMAutoProm: ERROR! Verify failed with %i differences."
"Verifying 0x%.2X bytes from emulator RAM..."
```

### Trace Mode  ← KEY FEATURE
```
Entry:
  "MMAutoProm: Trace mode entered. Monitoring addresses %X -> %X"
  "MMAutoProm: Trace mode entry failed."

Active:
  "MMAutoProm: Reading raw data from port..."   ← continuous address stream
  "Trace timed out"

Exit:
  "MMAutoProm: Trace mode exited"
  "MMAutoProm: Trace mode exit failed."
```
Trace monitors a range `[start_addr → end_addr]` and streams each address
the ECU reads in real-time.

### EEPROM / DataFlash (extended memory)
```
"MMAutoProm: ReadDataFlash requested, %i bytes from address 0x%X (Page 0x%X)"
"MMAutoProm: WriteDataFlash requested, %i bytes to address %X"
"MMAutoProm: EraseDataFlash requested"
"MMAutoProm: ReadEEPROM requested, %i bytes from address %X"
"MMAutoProm: WriteEEPROM requested, %i bytes to address %X"
"MMAutoProm: GetFlashInfo requested"
"ReadDataFlash: %i bytes requested from %.6X."
Page-based: "PageSize: %.2X, StartPage: %.2X, EndPage: %.2X, PageCount: %.2X"
```

---

## Layer 4 — RoadRunner (Device Identity)

### Emulation Modes
```
Mode character (single byte 'A'/'P'/'N'/'S'):
  Active Emulation        — live, ECU reads updated in real-time
  Persistent Emulation    — survives power cycle (written to flash)
  Non-persistent Emulation— RAM only, lost on power cycle
  Static Emulation        — fixed, no updates while running

Commands:
  "RoadRunner: Get Emulation Mode Succeeded: Mode %c"
  "RoadRunner: Set Emulation Mode Succeeded: Mode %c"
  "Roadrunner: Get Emulation Mode Failed!"
  "Roadrunner: Set Emulation Mode Failed!"
```

### Device Identity
```
"RoadRunner: Serial requested"
"RoadRunner: Setting Device Serial"
"RoadRunner: Setting Device Vendor ID"
```

### Quarterhorse (related Moates device, NOT Roadrunner)
```
"MMAutoProm: Quarterhorse mode retrieved: %i"
"MMAutoProm: Quarterhorse mode set: %i"
"MMAutoProm: Quarterhorse mode retrieval FAILED"
"MMAutoProm: Quarterhorse mode set FAILED"
```

---

## Error Codes (AP_E_* enum)

| Code                          | Meaning |
|-------------------------------|---------|
| `AP_E_OK`                     | Success |
| `AP_E_GENERAL_ERROR`          | Generic failure |
| `AP_E_DEVICE_NOT_FOUND`       | No emulator on COM port |
| `AP_E_PORT_NOT_INITIALIZED`   | Port not opened |
| `AP_E_PORT_BUSY`              | Port in use |
| `AP_E_COMM_READ_FAILURE`      | Serial read error |
| `AP_E_COMM_WRITE_FAILURE`     | Serial write error |
| `AP_E_COMM_READ_TIMEOUT`      | No response within timeout |
| `AP_E_INVALID_RESPONSE`       | Unexpected response byte |
| `AP_E_BAD_CHECKSUM`           | Checksum mismatch |
| `AP_E_ALT_WRITE_BAD_CHECKSUM` | Alt-write path checksum fail |
| `AP_E_INTERNAL_CS_INVALID`    | Internal checksum invalid |
| `AP_E_EXTERNAL_CS_INVALID`    | External checksum invalid |
| `AP_E_UNKNOWN_COMMAND`        | Device rejected command |
| `AP_E_REQUEST_NOT_SUPPORTED`  | Feature not in firmware |
| `AP_E_INVALID_FUNC_PARAM`     | Bad parameter |
| `AP_E_INVALID_REQUEST_PARAM`  | Bad request parameter |
| `AP_E_THREAD_TIMEOUT`         | Worker thread timed out |
| `AP_E_INVALID_HARDWARE_ID`    | Wrong device type |
| `AP_E_INVALID_VERSION`        | Firmware version mismatch |
| `AP_E_OPERATION_CANCELED`     | User or timeout cancel |
| `AP_E_FIRMWARE_FLASH_FAILED`  | Firmware update failed |
| `AP_E_LARGE_BIN_BANK_FAILED`  | Bank 8 extended mode failed |
| `AP_E_NVRAM_BUFFERING_FAILED` | NVRAM buffer error |
| `AP_E_INVALID_TUNE_REG`       | Invalid tuning register |
| `AP_E_TRIALS_EXPIRED`         | Trial licence expired |
| `AP_E_TUNEDB_FULL`            | Tuning DB at capacity |
| `AP_E_INVALID_FIRMWARE_IMAGE` | Bad firmware binary |

---

## EmUtility CLI Reference

```
EmUtility.exe [options] -read|-write|-verify

-comport <N>        COM port (0 = autodetect)
-emuaddress <0xXX>  Start address in emulator RAM
-fileaddress <0xXX> Start address in file
-infile <file>      Source file (for write/verify)
-outfile <file>     Destination file (for read)
-size <0xXX>        Byte count to transfer
-nobackbuf          Use emuaddress directly (skip internal buffer)
-monitor            Watch -infile for changes, auto-upload on change
-large              Use bank 8 (Ostrich 4-MBit, 512 KB)
-noquitprompt       No pause on exit (batch/scripted use)
```

---

## Key constraints for the proxy bridge

1. Address and size must be **256-byte aligned** (both BulkRead and BulkWrite)
2. Single-byte checksum per packet — exact algorithm needs empirical verification
3. The device communicates via a **virtual COM port** (FTDI VCP), not raw D2XX bulk
4. Baud rate is negotiated dynamically — proxy must handle `SetUSBBaud` sequence
5. Trace mode streams a continuous address byte-stream — requires async read loop
