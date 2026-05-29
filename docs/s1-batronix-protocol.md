# S1 — Batronix Protocol Analysis (BSL100.dll)

## Source file
`C:\Program Files\EVC\WinOLS\BSL100.dll` — 83,968 bytes  
Vendor: **Frieling-Racing Ltd.**  
Architecture: 32-bit PE (x86)

## PE Structure

| Section   | VirtRVA   | FileOff   | Size   | Notes |
|-----------|-----------|-----------|--------|-------|
| .text     | 0x1000    | 0x600     | 0x4800 | Code |
| .rdata    | 0xa000    | 0x4e00    | 0xe000 | Read-only data, strings |
| .data     | 0x18000   | 0x12e00   | 0x200  | Writable data |
| .xdedat0  | 0x19000   | 0x13000   | 0x200  | **Encrypted/custom data** |
| .reloc    | 0x1a000   | 0x13200   | 0x400  | Relocations |
| frc-tm    | 0x1b000   | 0x13600   | 0x1200 | **Frieling-Racing trademark section** |
| .adata    | 0x1d000   | 0x14800   | 0x0    | Empty (alignment?) |

## Export Table
- **41 functions exported by ordinal only** (ordinal base = 2, ordinals 2–42)
- **0 named exports** — WinOLS calls BSL100.dll entirely by ordinal number
- Ordinal-to-function mapping not yet known (requires dynamic analysis)

## Import Table
BSL100.dll imports from three DLLs:

| DLL           | Notes |
|---------------|-------|
| `kernel32.dll`| Windows API — includes **GetProcAddress** |
| `ftd2xx.dll`  | FTDI D2XX — loaded **dynamically via GetProcAddress** |
| `msvcrt.dll`  | C runtime |

### Critical finding: Dynamic FTDI loading
BSL100 imports `GetProcAddress` from kernel32.dll and uses it to load FTDI functions
at runtime. This means **no static FTDI function names appear in the import table**.

**Implication for the proxy:**  
Our `ftd2xx.dll` proxy placed in the WinOLS app directory will be loaded by
`LoadLibrary("ftd2xx.dll")` (which finds app-dir DLLs first), and all subsequent
`GetProcAddress(hFtd2xx, "FT_xxx")` calls will resolve against our proxy —
giving us full interception without any modification to WinOLS or BSL100.

## FTDI Functions BSL100 likely uses
Based on EPROM programmer use-cases and standard Batronix behaviour:

| Function                  | Purpose |
|---------------------------|---------|
| `FT_CreateDeviceInfoList` | Enumerate connected FTDI devices |
| `FT_GetDeviceInfoDetail`  | Get VID/PID/description of each device |
| `FT_OpenEx`               | Open device by description or serial |
| `FT_Close`                | Close device handle |
| `FT_SetBaudRate`          | Set baud rate (typical: 921600 for Batronix) |
| `FT_SetDataCharacteristics` | 8N1 |
| `FT_SetTimeouts`          | Read/write timeouts |
| `FT_Purge`                | Flush RX/TX buffers |
| `FT_Write`                | Send command bytes to programmer |
| `FT_Read`                 | Receive response bytes |
| `FT_GetQueueStatus`       | Check bytes waiting in RX buffer |

## Next step: Dynamic analysis
To map the 41 ordinals and discover the exact Batronix command bytes,
we build a **logging proxy** (Sprint 3) that records every FT_Read/FT_Write call
with timestamps and hex dumps. Running WinOLS with the logger will reveal
the complete Batronix command protocol empirically.

## Custom sections note
- `.xdedat0` — possibly XOR-encrypted data (firmware blob or licence check)
- `frc-tm` — Frieling-Racing trademark section, contains the import table;
  may hold obfuscated function pointers or the encrypted Batronix command table
