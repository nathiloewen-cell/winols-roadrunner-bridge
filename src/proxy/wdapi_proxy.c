/*
 * wdapi_proxy.c — wdapi1100.dll logging proxy
 *
 * WinOLS loads hardware DLLs dynamically. This proxy intercepts
 * WinDriver USB calls (WDU_*) to discover:
 *  1. The OLS300 USB VID/PID (from WDU_Init match tables)
 *  2. The OLS300 protocol bytes (from WDU_Transfer / WDU_Stream*)
 *
 * Build (32-bit):
 *   i686-w64-mingw32-gcc -shared -o wdapi1100.dll wdapi_proxy.c \
 *       -Wl,--kill-at -DWINVER=0x0601 -D_WIN32_WINNT=0x0601 \
 *       -lkernel32 -luser32
 *
 * Install:
 *   Rename C:\Program Files\EVC\WinOLS\wdapi1100.dll
 *       to C:\Program Files\EVC\WinOLS\wdapi1100_real.dll
 *   Copy wdapi_proxy.dll as wdapi1100.dll
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdarg.h>
#include <time.h>

/* Forward declaration for wlog (defined later in this file) */
static void wlog(const char* fmt, ...);

/* Sprint 3: include crypto constants (BASE_KEY, SHIFTS, TOKENS, EXTRA0) */
#include "rr_crypto.h"

/* ═══════════════════════════════════════════════════════════════════════
 * SPRINT 3: MoatesWare Load Bridge
 * Intercepts OLS300 DMA pointer commands, reads ECU data from WinOLS
 * memory (we are IN-PROCESS in WinOLS), writes to Roadrunner via COM.
 * ═══════════════════════════════════════════════════════════════════════ */

/* MoatesWare protocol */
#define RR_CMD_WRITE      0x57   /* 'W' BulkWrite */
#define RR_ACK            0x06   /* ACK byte */
/* RR_BAUD defined in rr_crypto.h as 921600 */
#define RR_TIMEOUT_MS     5000
#define RR_DEFAULT_PORT   "COM13"  /* TTL adapter (fixed after EEPROM repair) */

static HANDLE g_rr_com = INVALID_HANDLE_VALUE;

static BYTE rr_checksum(const BYTE* data, DWORD len) {
    BYTE cs = 0;
    for (DWORD i = 0; i < len; i++) cs ^= data[i];
    return cs;
}

static BOOL rr_open(const char* portname) {
    /* Try D2XX first — VCP may be disabled on this FTDI device */
    if (rr_open_d2xx()) {
        g_rr_com = (HANDLE)(uintptr_t)0xD2FFFACE;  /* sentinel: D2XX active */
        return TRUE;
    }
    /* Fall back to COM port */
    char path[32];
    _snprintf(path, sizeof(path), "\\\\.\\%s", portname);
    HANDLE h = CreateFileA(path, GENERIC_READ|GENERIC_WRITE, 0, NULL,
                           OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        wlog("RR: COM open %s failed: %lu", portname, GetLastError());
        return FALSE;
    }
    DCB dcb = {0}; dcb.DCBlength = sizeof(dcb);
    GetCommState(h, &dcb);
    dcb.BaudRate = 9600; dcb.ByteSize = 8;
    dcb.Parity = NOPARITY; dcb.StopBits = ONESTOPBIT;
    dcb.fBinary = TRUE; dcb.fDtrControl = DTR_CONTROL_DISABLE;
    dcb.fRtsControl = RTS_CONTROL_DISABLE;
    dcb.fOutxCtsFlow = FALSE; dcb.fOutxDsrFlow = FALSE; dcb.fDsrSensitivity = FALSE;
    SetCommState(h, &dcb);
    EscapeCommFunction(h, CLRDTR); EscapeCommFunction(h, CLRRTS);
    COMMTIMEOUTS to = {50, 2, 1500, 2, 1500};
    SetCommTimeouts(h, &to);
    PurgeComm(h, PURGE_RXCLEAR|PURGE_TXCLEAR);
    g_rr_com = h;
    wlog("RR: COM opened %s at 9600 (DTR disabled)", portname);
    return TRUE;
}

static void rr_close(void) {
    if (g_rr_com != INVALID_HANDLE_VALUE) {
        CloseHandle(g_rr_com); g_rr_com = INVALID_HANDLE_VALUE;
        wlog("RR: closed");
    }
}

/* MoatesWare BulkWrite: [CMD_W][addr_hi][addr_lo][size_hi][size_lo][data...][checksum] → ACK */
static BOOL rr_bulk_write(WORD addr, WORD size, const BYTE* data) {
    if (g_rr_com == INVALID_HANDLE_VALUE) return FALSE;
    if ((addr & 0xFF) || (size & 0xFF)) {
        wlog("RR: BulkWrite alignment error addr=0x%04X size=0x%04X", addr, size);
        return FALSE;
    }
    BYTE hdr[5] = {RR_CMD_WRITE, (BYTE)(addr>>8), (BYTE)(addr&0xFF),
                   (BYTE)(size>>8), (BYTE)(size&0xFF)};
    BYTE cs = rr_checksum(data, size);
    DWORD written = 0;
    WriteFile(g_rr_com, hdr, 5, &written, NULL);
    WriteFile(g_rr_com, data, size, &written, NULL);
    WriteFile(g_rr_com, &cs, 1, &written, NULL);
    /* Wait for ACK */
    BYTE ack = 0; DWORD got = 0;
    ReadFile(g_rr_com, &ack, 1, &got, NULL);
    if (got != 1 || ack != RR_ACK) {
        wlog("RR: BulkWrite addr=0x%04X size=0x%04X NAK/timeout got=%lu byte=0x%02X",
             addr, size, (unsigned long)got, ack);
        return FALSE;
    }
    wlog("RR: BulkWrite addr=0x%04X size=0x%04X OK", addr, size);
    return TRUE;
}

/* Autodetect Roadrunner: try known ports first */
static BOOL rr_autodetect(void) {
    const char* ports[] = {"COM13","COM11","COM12","COM14","COM15",NULL};
    for (int i = 0; ports[i]; i++) {
        if (rr_open(ports[i])) return TRUE;
    }
    /* Try COM1-COM20 */
    for (int n = 1; n <= 20; n++) {
        char name[16]; _snprintf(name, sizeof(name), "COM%d", n);
        if (rr_open(name)) return TRUE;
    }
    wlog("RR: autodetect failed");
    return FALSE;
}

/* Sprint 3 bridge state */
static DWORD g_dma_start_addr = 0;   /* ROM file offset (from cmd 1E 28) */
static DWORD g_dma_size = 0x8000;    /* default 32KB; updated from project */
static volatile BOOL g_bridge_done = FALSE;
static DWORD g_rom_base = 0;         /* actual Windows VA of ROM start (scan result) */
static volatile BOOL g_dma_ready = FALSE;  /* set by 1E 2C — data is confirmed ready */
static volatile int  g_scan_done = 0;      /* memory scan completed flag */

/* ── Logger (reuse pattern from ftd2xx proxy) ────────────────────────── */
static FILE* g_log = NULL;
static CRITICAL_SECTION g_cs;

static void log_init(void) {
    char path[MAX_PATH];
    GetTempPathA(MAX_PATH, path);
    strcat_s(path, MAX_PATH, "winols_wdapi.log");
    /* _SH_DENYNO (0x40) = share all — allows reading while we write */
    g_log = _fsopen(path, "a", 0x40 /* _SH_DENYNO */);
    InitializeCriticalSection(&g_cs);
    if (g_log) {
        fprintf(g_log, "\n=== wdapi1100 proxy loaded ===\n\n");
        fflush(g_log);
    }
}

static void log_close(void) {
    if (g_log) { fclose(g_log); g_log = NULL; }
    DeleteCriticalSection(&g_cs);
}

static void wlog(const char* fmt, ...) {
    if (!g_log) return;
    EnterCriticalSection(&g_cs);
    SYSTEMTIME st; GetLocalTime(&st);
    fprintf(g_log, "[%02d:%02d:%02d.%03d] ",
            st.wHour, st.wMinute, st.wSecond, st.wMilliseconds);
    va_list ap; va_start(ap, fmt);
    vfprintf(g_log, fmt, ap);
    va_end(ap);
    fprintf(g_log, "\n"); fflush(g_log);
    LeaveCriticalSection(&g_cs);
}

static void log_hex(const char* label, const void* buf, DWORD len) {
    if (!g_log || !buf || len == 0) return;
    EnterCriticalSection(&g_cs);
    const unsigned char* p = (const unsigned char*)buf;
    DWORD lim = len > 128 ? 128 : len;
    fprintf(g_log, "  %s [%lu bytes]%s:\n", label, (unsigned long)len,
            len > 128 ? " (truncated)" : "");
    for (DWORD i = 0; i < lim; i++) {
        if ((i & 15) == 0) fprintf(g_log, "  %04lX: ", (unsigned long)i);
        fprintf(g_log, "%02X ", p[i]);
        if ((i & 15) == 15 || i == lim-1) fprintf(g_log, "\n");
    }
    fflush(g_log);
    LeaveCriticalSection(&g_cs);
}

/* ── Self-referencing fake handles (prevent NULL-dereference crashes) ── */
static DWORD g_fake_driver_data[64];
static DWORD g_fake_device_data[64];
static DWORD g_fake_stream_data[64];

static void init_self_referencing(DWORD* arr, DWORD sz) {
    for (DWORD i = 0; i < sz; i++)
        arr[i] = (DWORD)(uintptr_t)arr;
}

/* ── Real DLL loader ─────────────────────────────────────────────────── */
static HMODULE g_real = NULL;

static FARPROC get_real(const char* name) {
    if (!g_real) return NULL;
    return GetProcAddress(g_real, name);
}

#define REAL(name) ((PFN_##name)get_real(#name))
#define DECL_PFN(ret, name, ...) typedef ret (__cdecl *PFN_##name)(__VA_ARGS__);

/* ── OLS300 identification packet (448 bytes) ────────────────────────── */
/* Loaded from C:\dev\winols-roadrunner-bridge\tools\id_packet.bin at startup.
   If the file doesn't exist, uses the built-in placeholder.
   The fuzzer writes different test patterns to id_packet.bin and restarts
   WinOLS to test whether WinOLS accepts the identification.               */
#define ID_PACKET_SIZE 448
static BYTE g_id_packet[ID_PACKET_SIZE];

static DWORD g_id_packet_mtime_lo = 0;  /* ftLastWriteTime.dwLowDateTime */

static void load_id_packet(void) {
    /* Initialize with built-in placeholder */
    memset(g_id_packet, 0, ID_PACKET_SIZE);
    g_id_packet[0x00] = 0x55;  /* sync byte 1 (from firmware 0x7C00) */
    g_id_packet[0x01] = 0xAA;  /* sync byte 2 (from firmware 0x7C01) */
    g_id_packet[0x08] = 0x01;  /* status = OK */
    /* Try putting version string at offset 80 (0x50) */
    if (ID_PACKET_SIZE > 86) {
        g_id_packet[0x50] = 0x4F; g_id_packet[0x51] = 0x4C; g_id_packet[0x52] = 0x53;
        g_id_packet[0x53] = 0x38; g_id_packet[0x54] = 0x32; g_id_packet[0x55] = 0x31;
    }

    /* Try to load from file (fuzzer writes here) */
    static const char ID_FILE[] = "C:\\dev\\winols-roadrunner-bridge\\tools\\id_packet.bin";
    WIN32_FILE_ATTRIBUTE_DATA fa;
    if (GetFileAttributesExA(ID_FILE, GetFileExInfoStandard, &fa)) {
        g_id_packet_mtime_lo = fa.ftLastWriteTime.dwLowDateTime;
        FILE* f = NULL;
        fopen_s(&f, ID_FILE, "rb");
        if (f) {
            size_t n = fread(g_id_packet, 1, ID_PACKET_SIZE, f);
            fclose(f);
            wlog("ID packet loaded from file (%zu bytes) first=[%02X %02X %02X %02X]",
                 n, g_id_packet[0], g_id_packet[1], g_id_packet[2], g_id_packet[3]);
        }
    }
}

/* Reload id_packet.bin if the file changed since last load. Called before each EP6 serve. */
static void reload_id_packet_if_changed(void) {
    static const char ID_FILE[] = "C:\\dev\\winols-roadrunner-bridge\\tools\\id_packet.bin";
    WIN32_FILE_ATTRIBUTE_DATA fa;
    if (!GetFileAttributesExA(ID_FILE, GetFileExInfoStandard, &fa)) return;
    if (fa.ftLastWriteTime.dwLowDateTime == g_id_packet_mtime_lo) return;
    /* File changed — reload */
    g_id_packet_mtime_lo = fa.ftLastWriteTime.dwLowDateTime;
    FILE* f = NULL;
    fopen_s(&f, ID_FILE, "rb");
    if (f) {
        size_t n = fread(g_id_packet, 1, ID_PACKET_SIZE, f);
        fclose(f);
        wlog("ID packet RELOADED from file (%zu bytes) first=[%02X %02X %02X %02X]",
             n, g_id_packet[0], g_id_packet[1], g_id_packet[2], g_id_packet[3]);
    }
}

/* ── WinDriver type definitions (minimal, for logging) ───────────────── */

/* WDU_MATCH_TABLE — what WinOLS registers to find OLS300 */
typedef struct {
    WORD wVendorId;
    WORD wProductId;
    WORD bDeviceClass;
    WORD bDeviceSubClass;
    WORD bInterfaceClass;
    WORD bInterfaceSubClass;
    WORD bInterfaceProtocol;
} WDU_MATCH_TABLE;

typedef void* WDU_DRIVER_HANDLE;
typedef void* WDU_DEVICE_HANDLE;

/* Simplified transfer struct */
typedef struct {
    DWORD dwPipeNum;
    DWORD fRead;
    DWORD dwOptions;
    union { void* pBuffer; } Data;
    DWORD dwBytes;
    DWORD dwTimeout;
    DWORD dwError;
    DWORD fOK;
} WD_TRANSFER;

/* ── Vectored Exception Handler ──────────────────────────────────────── */
static BYTE  g_safe_write_buf[4096];
static DWORD g_veh_depth = 0;   /* re-entry guard */

static LONG WINAPI veh_handler(EXCEPTION_POINTERS* pEx) {
    /* Re-entry guard: VirtualQuery or wlog can trigger exceptions */
    if (InterlockedIncrement((LONG*)&g_veh_depth) > 1) {
        InterlockedDecrement((LONG*)&g_veh_depth);
        return EXCEPTION_CONTINUE_SEARCH;
    }

    LONG ret = EXCEPTION_CONTINUE_SEARCH;
    if (pEx && pEx->ExceptionRecord && pEx->ContextRecord &&
        pEx->ExceptionRecord->ExceptionCode == EXCEPTION_ACCESS_VIOLATION) {

        DWORD op    = (DWORD)pEx->ExceptionRecord->ExceptionInformation[0];
        DWORD fault = (DWORD)pEx->ExceptionRecord->ExceptionInformation[1];

        /* Catch READ and WRITE violations ONLY in the null-guard and kernel ranges.
           Do NOT catch uncommitted pages — WinDriver legitimately allocates those.
           Native WinDriver pfDeviceAttach reads from low addresses due to WD16/WD11
           struct mismatch — the null guard catch handles this. */
        /* Catch bad reads AND writes in null-guard and kernel ranges.
           op=0: read violation, op=1: write violation. Both need handling for
           WinLicense code that dereferences NULL after our XOR EAX,EAX patch. */
        BOOL is_bad = (fault < 0x10000 || fault >= 0x80000000);

        if (is_bad) {
            CONTEXT* ctx = pEx->ContextRecord;
            DWORD safe   = (DWORD)(uintptr_t)g_safe_write_buf;
            /* Only log if log is already initialized to avoid recursion */
            if (g_log)
                wlog("VEH: bad write EIP=0x%08lX fault=0x%08lX",
                     (unsigned long)pEx->ExceptionRecord->ExceptionAddress,
                     (unsigned long)fault);
            if (ctx->Eax == fault || ctx->Eax < 0x10000 || ctx->Eax >= 0x80000000) ctx->Eax = safe;
            if (ctx->Ebx == fault || ctx->Ebx < 0x10000 || ctx->Ebx >= 0x80000000) ctx->Ebx = safe;
            if (ctx->Ecx == fault || ctx->Ecx < 0x10000 || ctx->Ecx >= 0x80000000) ctx->Ecx = safe;
            if (ctx->Edx == fault || ctx->Edx < 0x10000 || ctx->Edx >= 0x80000000) ctx->Edx = safe;
            if (ctx->Esi == fault || ctx->Esi < 0x10000 || ctx->Esi >= 0x80000000) ctx->Esi = safe;
            if (ctx->Edi == fault || ctx->Edi < 0x10000 || ctx->Edi >= 0x80000000) ctx->Edi = safe;
            ret = EXCEPTION_CONTINUE_EXECUTION;
        }
    }
    InterlockedDecrement((LONG*)&g_veh_depth);
    return ret;
}

static void schedule_startup_attach(void);  /* fwd decl — defined after WDU types */

/* ── DLL Entry ───────────────────────────────────────────────────────── */
BOOL WINAPI DllMain(HINSTANCE hInst, DWORD reason, LPVOID res) {
    (void)hInst; (void)res;
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hInst);
        memset(g_safe_write_buf, 0, sizeof(g_safe_write_buf));
        /* Pre-fill fake handles so pointer-chasing doesn't hit NULL */
        init_self_referencing(g_fake_driver_data, 64);
        init_self_referencing(g_fake_device_data, 64);
        init_self_referencing(g_fake_stream_data,  64);
        AddVectoredExceptionHandler(1, veh_handler);
        load_id_packet();
        log_init();
        /* NOTE: Startup-attach removed — it caused a 37-second UI freeze.
           pfDeviceAttach is now only fired from WDU_Init (Config OK click).
           User flow: Miscellaneous → Configuration → USB (OLS300) → OK → connected. */
        /* Load real wdapi1100_real.dll — Roadrunner now has WinUSB driver
           so wdapi can find it natively. VEH handles any windrvr.sys init failures. */
        char path[MAX_PATH];
        GetModuleFileNameA(NULL, path, MAX_PATH);
        char* last = strrchr(path, '\\');
        if (last)
            strcpy_s(last+1, MAX_PATH-(last-path)-1, "wdapi1100_real.dll");
        g_real = LoadLibraryA(path);
        if (g_real) {
            wlog("wdapi proxy loaded (REAL DLL mode — WinUSB device active)");
        } else {
            wlog("wdapi proxy loaded (standalone fallback — real DLL not found)");
        }
        /* Sprint 3: COM port opened LAZILY at Load-time (not at startup).
           Opening at startup disrupts the Roadrunner during OLS300 operation.
           The port will be opened when the DMA pointer command is received. */
        wlog("S3: Load Bridge bereit — COM13 wird bei Load geoeffnet");
        /* Schedule startup pfDeviceAttach using fixed ols_32on32.exe addresses.
           Fire after 2s so WinOLS main window is ready.
           Works because ols_32on32.exe has no ASLR (packed exe = fixed base). */
        /* schedule_startup_attach(); — disabled: causes 37s UI freeze */

        /* Patch1: NOP the 9-second WinLicense blocking call at 0x0052CECA. */
        {
            BYTE* addr = (BYTE*)0x0052CECA;
            DWORD old_prot = 0;
            if (addr[0]==0xE8 && addr[1]==0x11 && addr[2]==0x3C &&
                addr[3]==0x37 && addr[4]==0x00 &&
                VirtualProtect(addr, 5, PAGE_EXECUTE_READWRITE, &old_prot)) {
                addr[0]=addr[1]=addr[2]=addr[3]=addr[4]=0x90;
                VirtualProtect(addr, 5, old_prot, &old_prot);
                wlog("Patch1: 9s call at 0x0052CECA -> NOP x5");
            }
        }
        /* Patch2: TODO - find correct blocking call address for Hardware Config hang.
           Patch2 attempt (JE→JMP at 0x005FA829/83D/851) was REVERTED:
           skipping those calls causes WinOLS to spin at 100% CPU indefinitely.
           Those calls include necessary timing code for WinLicense.
           Workaround: use automation (full_flow.py) which clicks OK from Colours tab,
           naturally skipping the Hardware-specific 8-minute WinLicense path. */
    } else if (reason == DLL_PROCESS_DETACH) {
        wlog("wdapi proxy unloaded");
        log_close();
    }
    return TRUE;
}

/* ── OLS300 device identity (confirmed from WDU_Init log) ───────────── */
#define OLS300_VID  0x0547
#define OLS300_PID  0x3000

/* (fake handle arrays declared at top of file) */

#define FAKE_DRIVER_HANDLE  ((WDU_DRIVER_HANDLE)g_fake_driver_data)
#define FAKE_DEVICE_HANDLE  ((WDU_DEVICE_HANDLE)g_fake_device_data)

/* ── WinDriver USB device structures (WinDriver 16.6 layout) ─────────── */
/* PAD_TO_64: adds DWORD padding after each pointer in 32-bit builds     */
#define _PAD64(name) DWORD dwPad_##name

typedef struct {
    BYTE  bLength; BYTE bDescriptorType; WORD bcdUSB;
    BYTE  bDeviceClass; BYTE bDeviceSubClass; BYTE bDeviceProtocol;
    BYTE  bMaxPacketSize0;
    WORD  idVendor; WORD idProduct; WORD bcdDevice;
    BYTE  iManufacturer; BYTE iProduct; BYTE iSerialNumber;
    BYTE  bNumConfigurations;
} WDU_DEVICE_DESCRIPTOR;  /* 18 bytes */

typedef struct {
    DWORD dwNumber;           /* pipe number */
    DWORD dwMaximumPacketSize;
    DWORD type;               /* transfer type */
    DWORD direction;          /* WDU_DIR_IN / WDU_DIR_OUT */
    DWORD dwInterval;
} WDU_PIPE_INFO;              /* 20 bytes */

typedef struct {
    BYTE bInterfaceNumber; BYTE bAlternateSetting;
    BYTE bNumEndpoints;    BYTE bInterfaceClass;
    BYTE bInterfaceSubClass; BYTE bInterfaceProtocol;
    BYTE iInterface;       BYTE pad;
    WDU_PIPE_INFO* pPipes; _PAD64(pPipes);
} WDU_ALTERNATE_SETTING;

typedef struct {
    WDU_ALTERNATE_SETTING* pAlternateSettings; _PAD64(pAlternateSettings);
    DWORD dwNumAltSettings;
    WDU_ALTERNATE_SETTING* pActiveAltSetting;  _PAD64(pActiveAltSetting);
} WDU_INTERFACE;

typedef struct {
    BYTE bLength; BYTE bDescriptorType; WORD wTotalLength;
    BYTE bNumInterfaces; BYTE bConfigurationValue;
    BYTE iConfiguration; BYTE bmAttributes; BYTE MaxPower;
} WDU_CONFIGURATION_DESCRIPTOR; /* 9 bytes */

typedef struct {
    WDU_CONFIGURATION_DESCRIPTOR Descriptor; /* offset 0, 9 bytes */
    /* 3 bytes padding to align DWORD */
    BYTE _pad[3];
    DWORD dwNumInterfaces;                    /* offset 12 */
    WDU_INTERFACE* pInterfaces;               /* offset 16 */
    _PAD64(pInterfaces);                      /* offset 20 */
} WDU_CONFIGURATION;

/* WD11 WDU_DEVICE layout (WinOLS compiled for WinDriver 11):
   offset 0:  Descriptor (18 bytes)
   offset 18: padding (2 bytes)
   offset 20: pConfigs
   offset 24: pActiveConfig
   offset 28: pActiveInterface[0..15]  (WD_MAXDEVICES=16 confirmed)
*/
#define WD_MAXDEVICES 16

typedef struct {
    WDU_DEVICE_DESCRIPTOR  Descriptor;
    WDU_CONFIGURATION*     pConfigs;
    WDU_CONFIGURATION*     pActiveConfig;
    WDU_ALTERNATE_SETTING* pActiveInterface[WD_MAXDEVICES];
} WDU_DEVICE;

/* WDU_EVENT_TABLE callback signatures */
typedef BOOL  (__cdecl *WDU_ATTACH_CALLBACK)(WDU_DEVICE_HANDLE, WDU_DEVICE*, PVOID);
typedef void  (__cdecl *WDU_DETACH_CALLBACK)(WDU_DEVICE_HANDLE, PVOID);
typedef BOOL  (__cdecl *WDU_POWER_CALLBACK) (WDU_DEVICE_HANDLE, DWORD, PVOID);

typedef struct {
    WDU_ATTACH_CALLBACK pfDeviceAttach;
    WDU_DETACH_CALLBACK pfDeviceDetach;
    WDU_POWER_CALLBACK  pfPowerChange;
    PVOID               pUserData;
} WDU_EVENT_TABLE;

/* ── Fake OLS300 USB device info (WD16.6 struct layout) ─────────────── */
/* WDU_PIPE_INFO: dwNumber, dwMaximumPacketSize, type, direction, dwInterval */
static WDU_PIPE_INFO g_pipes[2] = {
    { 0, 64, 3, 2, 0 },   /* pipe 0: Bulk OUT */
    { 1, 64, 3, 1, 0 },   /* pipe 1: Bulk IN  */
};
static WDU_ALTERNATE_SETTING g_altset = {
    0, 0, 2, 0xFF, 0, 0, 0, 0, g_pipes, 0
};
static WDU_INTERFACE g_iface = {
    &g_altset, 0, 1, &g_altset, 0
};
static WDU_CONFIGURATION_DESCRIPTOR g_cfgdesc = {
    9, 2, sizeof(WDU_CONFIGURATION_DESCRIPTOR), 1, 1, 0, 0x80, 250
};
static WDU_CONFIGURATION g_config;   /* initialized in WDU_Init */
static WDU_DEVICE        g_fake_device;

/* Forward declarations */
static DWORD WINAPI attach_thread(LPVOID param);
static WDU_ATTACH_CALLBACK g_attach_cb         = NULL;
static PVOID               g_attach_userdata   = NULL;
static WDU_DEVICE_HANDLE   g_attach_handle     = NULL;
static WDU_DRIVER_HANDLE   g_real_driver_handle = NULL; /* real wdapi1660 handle */
/* Global buffer for real_init output — avoids stack corruption from __stdcall mismatch */
static WDU_DRIVER_HANDLE   g_real_init_out     = NULL;

/* ── Startup attach: fire pfDeviceAttach at fixed ols_32on32.exe addr ── */
/* ols_32on32.exe has no ASLR: pfDeviceAttach=0x005FA860, userData=0x01A99544 */
static void schedule_startup_attach(void) {
    if (g_attach_cb) return;  /* already set by WDU_Init */
    g_attach_cb       = (WDU_ATTACH_CALLBACK)(uintptr_t)0x005FA860;
    g_attach_userdata = (PVOID)(uintptr_t)0x01A99544;
    wlog("Startup attach: pfDeviceAttach=0x005FA860 userData=0x01A99544");
    HANDLE ht = CreateThread(NULL, 0, attach_thread, NULL, CREATE_SUSPENDED, NULL);
    if (ht) {
        SetThreadPriority(ht, THREAD_PRIORITY_BELOW_NORMAL);
        ResumeThread(ht); CloseHandle(ht);
    }
}

/* ── WDU_Init — let REAL wdapi handle device detection via WinUSB ────── */
__declspec(dllexport)
DWORD __cdecl WDU_Init(WDU_DRIVER_HANDLE* phDriver,
                        WDU_MATCH_TABLE*   pMatchTables,
                        DWORD              dwNumMatchTables,
                        void*              pEventTable,
                        const char*        sLicense,
                        DWORD              dwOptions) {
    wlog("WDU_Init: VID=0x%04X PID=0x%04X",
         pMatchTables ? pMatchTables[0].wVendorId : 0,
         pMatchTables ? pMatchTables[0].wProductId : 0);

    /* Open Roadrunner UART BEFORE activating USB — at this point the Roadrunner
       MCU is still in native/command mode and will respond to 56 56 version req.
       Once USB is active the MCU may switch to emulation mode and ignore UART.
       DTR is kept LOW (see rr_open) to prevent accidental MCU reset.           */
    if (g_rr_com == INVALID_HANDLE_VALUE) {
        wlog("WDU_Init: opening COM13 before USB init...");
        if (!rr_open("COM13")) rr_autodetect();
        if (g_rr_com != INVALID_HANDLE_VALUE) {
            wlog("WDU_Init: COM13 open — running init handshake at 9600...");
            if (rr_init_with_baud(g_rr_com)) {
                /* Switch timeouts to data-transfer mode after init */
                COMMTIMEOUTS to2 = {50, 2, 5000, 2, 5000};
                SetCommTimeouts(g_rr_com, &to2);
                wlog("WDU_Init: Roadrunner UART init OK — ready for Load");
            } else {
                wlog("WDU_Init: Roadrunner UART init FAILED (no 56 56 response)");
            }
        } else {
            wlog("WDU_Init: COM13 not available");
        }
    }

    /* Try real wdapi — first open driver with demo license, then init USB */
    typedef DWORD (__cdecl *PFN_OPEN)(DWORD, const char*);
    typedef DWORD (__cdecl *PFN_INIT)(WDU_DRIVER_HANDLE*, WDU_MATCH_TABLE*,
                                       DWORD, void*, const char*, DWORD);
    PFN_OPEN real_open = (PFN_OPEN)get_real("WDC_DriverOpen");
    PFN_INIT real_init = (PFN_INIT)get_real("WDU_Init");

    if (real_open && real_init) {
        /* Try WinOLS license first, then demo license */
        DWORD open_r = real_open(0, sLicense);
        if (open_r != 0) open_r = real_open(0, "12345abcde1234.license");
        wlog("  WDC_DriverOpen -> 0x%08lX", (unsigned long)open_r);

        /* Use global buffer to avoid stack corruption from calling convention mismatch */
        g_real_init_out = NULL;
        DWORD r = real_init(&g_real_init_out, pMatchTables, dwNumMatchTables,
                            pEventTable, "12345abcde1234.license", dwOptions);
        wlog("  WDU_Init (real) -> 0x%08lX real_handle=%p",
             (unsigned long)r, g_real_init_out);
        /* Store handle in global for cleanup — global is not stack-corrupted */
        if (r == 0 && g_real_init_out != NULL) {
            g_real_driver_handle = g_real_init_out;
            wlog("  g_real_driver_handle stored: %p", g_real_driver_handle);
        }
        if (r == 0 && g_real_init_out) {
            /* WDU_Init succeeded with real wdapi1660. Store real handle for
               WDU_Transfer forwarding (real USB commands reach the device).
               Give WinOLS a FAKE WD11-compatible handle to avoid WD16/WD11 crash.
               Schedule our own pfDeviceAttach after 500ms — don't rely on real
               WinDriver callback which can fire 30-60s late. */
            g_real_driver_handle = g_real_init_out;
            wlog("  WDU_Init real SUCCESS: stored real=%p, giving WinOLS fake handle", g_real_init_out);
            if (phDriver) *phDriver = FAKE_DRIVER_HANDLE;
            /* Initialize fake device structs (same as fallback path) */
            g_config.Descriptor      = g_cfgdesc;
            g_config.pInterfaces     = &g_iface;
            g_config.dwNumInterfaces = 1;
            memset(&g_fake_device, 0, sizeof(g_fake_device));
            g_fake_device.Descriptor.bLength            = 18;
            g_fake_device.Descriptor.bDescriptorType    = 1;
            g_fake_device.Descriptor.bcdUSB             = 0x0200;
            g_fake_device.Descriptor.idVendor           = OLS300_VID;
            g_fake_device.Descriptor.idProduct          = OLS300_PID;
            g_fake_device.Descriptor.bcdDevice          = 0x0100;
            g_fake_device.Descriptor.bMaxPacketSize0    = 64;
            g_fake_device.Descriptor.bNumConfigurations = 1;
            g_fake_device.pConfigs       = &g_config;
            g_fake_device.pActiveConfig  = &g_config;
            for (int i = 0; i < WD_MAXDEVICES; i++)
                g_fake_device.pActiveInterface[i] = &g_altset;
            if (pEventTable) {
                WDU_EVENT_TABLE* tbl = (WDU_EVENT_TABLE*)pEventTable;
                if (tbl->pfDeviceAttach) {
                    g_attach_cb       = tbl->pfDeviceAttach;
                    g_attach_userdata = tbl->pUserData;
                    g_attach_handle   = NULL;  /* fake device handle for WinOLS */
                    wlog("  Scheduling pfDeviceAttach (500ms)...");
                    HANDLE ht2 = CreateThread(NULL, 0, attach_thread, NULL,
                                              CREATE_SUSPENDED, NULL);
                    if (ht2) {
                        SetThreadPriority(ht2, THREAD_PRIORITY_BELOW_NORMAL);
                        ResumeThread(ht2); CloseHandle(ht2);
                    }
                }
            }
            return 0;
        }
        wlog("  WDU_Init failed (0x%08lX) — falling back to fake mode", (unsigned long)r);
    }

    /* Fallback: fake mode if real wdapi can't find device */
    if (phDriver) *phDriver = FAKE_DRIVER_HANDLE;
    g_attach_handle = NULL;  /* use fake handle in fallback mode */
    wlog("  WDU_Init -> fake fallback");

    /* Build fake device structures at runtime (can't use static init with ptrs) */
    g_config.Descriptor      = g_cfgdesc;
    g_config.pInterfaces     = &g_iface;
    g_config.dwNumInterfaces = 1;
    memset(&g_fake_device, 0, sizeof(g_fake_device));
    g_fake_device.Descriptor.bLength            = 18;
    g_fake_device.Descriptor.bDescriptorType    = 1;
    g_fake_device.Descriptor.bcdUSB             = 0x0200;
    g_fake_device.Descriptor.idVendor           = OLS300_VID;
    g_fake_device.Descriptor.idProduct          = OLS300_PID;
    g_fake_device.Descriptor.bcdDevice          = 0x0100;
    g_fake_device.Descriptor.bMaxPacketSize0    = 64;
    g_fake_device.Descriptor.bNumConfigurations = 1;
    g_fake_device.pConfigs       = &g_config;
    g_fake_device.pActiveConfig  = &g_config;
    /* Fill all WD_MAXDEVICES entries */
    for (int i = 0; i < WD_MAXDEVICES; i++)
        g_fake_device.pActiveInterface[i] = &g_altset;

    /* Call pfDeviceAttach after a short delay on a thread.
       500ms gives WinOLS enough time to finish WDU_Init processing.
       Thread has THREAD_PRIORITY_BELOW_NORMAL to avoid starving main thread. */
    if (pEventTable) {
        WDU_EVENT_TABLE* tbl = (WDU_EVENT_TABLE*)pEventTable;
        if (tbl->pfDeviceAttach) {
            g_attach_cb       = tbl->pfDeviceAttach;
            g_attach_userdata = tbl->pUserData;
            wlog("  Scheduling pfDeviceAttach (500ms delay)...");
            HANDLE ht = CreateThread(NULL, 0, attach_thread, NULL,
                                     CREATE_SUSPENDED, NULL);
            if (ht) {
                SetThreadPriority(ht, THREAD_PRIORITY_BELOW_NORMAL);
                ResumeThread(ht);
                CloseHandle(ht);
            }
        }
    }
    return 0;
}

static DWORD WINAPI attach_thread(LPVOID param) {
    (void)param;
    Sleep(500);  /* 500ms: first attach — triggers EP6 identification polling */
    if (!g_attach_cb) return 0;
    WDU_DEVICE_HANDLE use_handle = g_attach_handle ? g_attach_handle : FAKE_DEVICE_HANDLE;

    /* Always use fake WD11-format device info — real wdapi1660 returns WD16
       format which is incompatible with WinOLS compiled for WD11.           */
    WDU_DEVICE* use_device = &g_fake_device;

    /* Verify fake device structure integrity before passing to WinOLS */
    if (use_device == &g_fake_device) {
        void* check = g_fake_device.pActiveInterface[5];
        wlog("[attach] g_fake_device.pActiveInterface[5] = %p (should be &g_altset=%p)",
             check, (void*)&g_altset);
        if (!check) {
            wlog("[attach] ERROR: pActiveInterface[5] is NULL! Re-init fake device.");
            for (int i = 0; i < WD_MAXDEVICES; i++)
                g_fake_device.pActiveInterface[i] = &g_altset;
        }
    }

    wlog("[attach] pfDeviceAttach(handle=%p real=%d device=%p userData=%p)",
         use_handle, (g_attach_handle != NULL), use_device, g_attach_userdata);

    /* If using real handle, use FAKE handle for pfDeviceAttach to avoid WD16 internals crash */
    WDU_DEVICE_HANDLE safe_handle = (g_attach_handle && g_real_driver_handle)
                                     ? FAKE_DEVICE_HANDLE  /* avoid WD16 internal crash */
                                     : use_handle;
    wlog("[attach] Using safe_handle=%p for callback", safe_handle);
    BOOL ok = g_attach_cb(safe_handle, use_device, g_attach_userdata);
    wlog("[attach] pfDeviceAttach returned %d", ok);

    /* Second pfDeviceAttach at +3s — activates Load/Disconnect button in WinOLS.
       IMPORTANT: fire only ONCE (static flag). Without this, second attach causes
       WinOLS to trigger WDU_Uninit → 8-min WinLicense loop → infinite cycle. */
    static volatile LONG g_attach2_fired = 0;
    if (ok && g_attach_cb && InterlockedCompareExchange(&g_attach2_fired, 1, 0) == 0) {
        Sleep(3000);
        if (g_attach_cb) {
            WDU_DEVICE_HANDLE handle2 = (WDU_DEVICE_HANDLE)g_fake_stream_data;
            wlog("[attach2] Firing second pfDeviceAttach handle=%p (once only)...", handle2);
            BOOL ok2 = g_attach_cb(handle2, use_device, g_attach_userdata);
            wlog("[attach2] second pfDeviceAttach returned %d", ok2);
        }
    }
    return 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_Uninit(WDU_DRIVER_HANDLE hDriver) {
    void** fp = (void**)__builtin_frame_address(0);
    void** fp1 = fp ? (void**)*fp : NULL;
    void** fp2 = fp1 ? (void**)*fp1 : NULL;
    void* r0 = fp ? fp[1] : (void*)0;
    void* r1 = fp1 ? fp1[1] : (void*)0;
    void* r2 = fp2 ? fp2[1] : (void*)0;
    wlog("WDU_Uninit(handle=%p) caller=0x%08X r1=0x%08X r2=0x%08X",
         hDriver, (unsigned)r0, (unsigned)r1, (unsigned)r2);
    /* Close the real wdapi session so the next WDU_Init can open cleanly. */
    if (g_real_driver_handle) {
        typedef DWORD (__cdecl *FN)(WDU_DRIVER_HANDLE);
        FN fn = (FN)get_real("WDU_Uninit");
        if (fn) {
            DWORD r = fn(g_real_driver_handle);
            wlog("  real WDU_Uninit -> 0x%08lX", (unsigned long)r);
        }
        g_real_driver_handle = NULL;
    }
    g_attach_handle = NULL;
    g_attach_cb = NULL;
    return 0;
}

/* ── WDU_Transfer / WDU_TransferBulk — intercept data ───────────────── */
__declspec(dllexport)
DWORD __cdecl WDU_Transfer(WDU_DEVICE_HANDLE hDevice,
                            DWORD dwPipeNum, DWORD fRead,
                            DWORD dwOptions, void* pBuffer,
                            DWORD dwBytes, DWORD* pdwBytesTransferred,
                            BYTE* pSetupPacket, DWORD dwTimeout) {
    /* Track EP2 OUT command count for EP6 state machine */
    static int g_ep2_out_count = 0;
    if (!fRead && (dwPipeNum == 0x02 || dwPipeNum == 2) && pBuffer && dwBytes > 0)
        g_ep2_out_count++;
    /* Log ALL transfers (rate-limited after 300) */
    static int g_all_count = 0;
    if (++g_all_count <= 2000)
        wlog("WDU_Transfer pipe=0x%02lX %s %lu bytes",
             (unsigned long)dwPipeNum, fRead?"IN":"OUT", (unsigned long)dwBytes);
    if (!fRead && pBuffer && dwBytes > 0)
        log_hex("WDU_Transfer TX", pBuffer, dwBytes);

    /* Intercept pipe 0x86 (Bulk IN) reads — OLS300 identification/data stream.
       Serve the g_id_packet buffer (448 bytes). Content is updated by Sprint 1
       firmware analysis. Currently a placeholder; will be replaced with correct bytes. */
    if (fRead && (dwPipeNum == 0x86 || dwPipeNum == 134) && pBuffer && dwBytes >= 16) {
        /* Auto-reload id_packet.bin if fuzzer changed it */
        reload_id_packet_if_changed();
        DWORD give = dwBytes < ID_PACKET_SIZE ? dwBytes : ID_PACKET_SIZE;
        memcpy(pBuffer, g_id_packet, give);
        if (give < dwBytes)
            memset((BYTE*)pBuffer + give, 0, dwBytes - give);
        if (pdwBytesTransferred) *pdwBytesTransferred = give;
        /* Set field_8=1 via stack walk (02:23 working config):
           fp2 = EBP of identification function (0x0052CB44)
           [EBP - 0x1DC] = OLS module object; object[8] = field_8 */
        {
            void** fp0 = (void**)__builtin_frame_address(0);
            void** fp1 = fp0 ? (void**)*fp0 : NULL;
            void** fp2 = fp1 ? (void**)*fp1 : NULL;
            if (fp2) {
                DWORD fp2_val = (DWORD)(uintptr_t)fp2;
                if (fp2_val > 0x00100000 && fp2_val < 0x7F000000) {
                    BYTE** op = (BYTE**)((BYTE*)fp2 - 0x1DC);
                    DWORD ov = (DWORD)(uintptr_t)op;
                    if (ov > 0x00100000 && ov < 0x7F000000) {
                        BYTE* obj = *op;
                        if ((DWORD)(uintptr_t)obj > 0x10000 &&
                            (DWORD)(uintptr_t)obj < 0x7F000000 && obj[8] == 0) {
                            obj[8] = 1;
                            wlog("field_8=1: obj=%p", obj);
                        }
                    }
                }
            }
        }
        static int g_ep6_count = 0;
        /* After EP2 commands: modify EP6 to signal "command processed / ready".
           This tells WinOLS the OLS300 accepted the EP2 command and is ready for more.
           Without this, WinOLS sees "idle" state and stops after one EP2 exchange.
           Use byte[3]=g_ep2_out_count to signal processing state to WinOLS. */
        if (g_ep2_out_count > 0 && give >= 6) {
            BYTE* buf = (BYTE*)pBuffer;
            /* After firmware check command (0x2E FE 1F 02):
               EP6 bytes[4:5] must reflect firmware version 0x044A.
               WinOLS reads EP6 AFTER EP2 check to confirm firmware version.
               Without this, WinOLS sees wrong version and stops communication. */
            buf[3] = (BYTE)g_ep2_out_count;
            buf[4] = 0x04;  /* firmware version high = 0x044A */
            buf[5] = 0x4A;  /* firmware version low */
        }
        if (++g_ep6_count <= 5) {
            wlog("WDU_Transfer ID pipe=0x%lX %lu bytes first=[%02X %02X %02X %02X] ep2_count=%d",
                 (unsigned long)dwPipeNum, (unsigned long)give,
                 ((BYTE*)pBuffer)[0], ((BYTE*)pBuffer)[1],
                 ((BYTE*)pBuffer)[2], ((BYTE*)pBuffer)[3],
                 g_ep2_out_count);
        }
        /* One-time memory scan: find ECU data in WinOLS process memory.
           The DMA addr (0x148AC) is a ROM file offset, NOT a Windows VA.
           We scan all readable pages for the known ECU signature bytes.  */
        if (g_dma_start_addr > 0x10000 && !g_scan_done) {
            g_scan_done = 1;
            wlog("MEM SCAN: suche ECU-Daten im WinOLS-Prozess...");
            SYSTEM_INFO si; GetSystemInfo(&si);
            BYTE* addr = (BYTE*)si.lpMinimumApplicationAddress;
            BYTE* maxAddr = (BYTE*)si.lpMaximumApplicationAddress;
            int found = 0;
            while (addr < maxAddr && found < 5) {
                MEMORY_BASIC_INFORMATION mbi;
                if (!VirtualQuery(addr, &mbi, sizeof(mbi))) { addr += 0x1000; continue; }
                /* Only scan committed, readable, non-executable pages */
                if (mbi.State == MEM_COMMIT &&
                    (mbi.Protect & (PAGE_READONLY|PAGE_READWRITE|PAGE_WRITECOPY)) &&
                    !(mbi.Protect & PAGE_GUARD) && mbi.RegionSize >= 0x10000) {
                    /* Scan this region for ECU signature (first 8 bytes of Audi A3 ROM) */
                    BYTE* p = (BYTE*)mbi.BaseAddress;
                    BYTE* end = p + mbi.RegionSize - 8;
                    /* safe scan — region is verified readable via VirtualQuery */
                    while (p < end) {
                        if (p[0]==0xAE && p[1]==0x14 && p[2]==0xCB && p[3]==0x14) {
                            /* ROM base = hit VA - ROM file offset at this location */
                            DWORD candidate_base = (DWORD)(uintptr_t)p - g_dma_start_addr;
                            wlog("MEM SCAN HIT: VA=0x%08lX base=0x%08lX [%02X %02X %02X %02X] region=0x%08lX",
                                 (unsigned long)(uintptr_t)p,
                                 (unsigned long)candidate_base,
                                 p[0],p[1],p[2],p[3],
                                 (unsigned long)(uintptr_t)mbi.BaseAddress);
                            if (!g_rom_base) {
                                g_rom_base = candidate_base;
                                /* Update dma_size to full region (= full ROM size) */
                                g_dma_size = (DWORD)mbi.RegionSize;
                                wlog("MEM SCAN: ROM base=0x%08lX size=0x%08lX (full ROM)",
                                     (unsigned long)g_rom_base, (unsigned long)g_dma_size);
                            }
                            found++;
                            if (found >= 3) break;
                            p += 4;
                        } else { p++; }
                    }
                }
                addr = (BYTE*)mbi.BaseAddress + mbi.RegionSize;
            }
            if (!found) wlog("MEM SCAN: Signatur AE 14 CB 14 nicht gefunden");
            else        wlog("MEM SCAN: %d Treffer gefunden", found);

            /* Trigger write NOW if 1E 2C already arrived (g_dma_ready) */
            if (g_rom_base && g_dma_ready && g_bridge_done &&
                g_rr_com != INVALID_HANDLE_VALUE) {
                BYTE* ecuData = (BYTE*)(uintptr_t)(g_rom_base + g_dma_start_addr);
                DWORD total = (g_dma_size + 255) / 256;
                wlog("S3: MEM SCAN → Write %lu Blocks, plain[0:4]=%02X %02X %02X %02X",
                     (unsigned long)total,
                     ecuData[0],ecuData[1],ecuData[2],ecuData[3]);
                if (g_rr_ft && g_FT_Purge) g_FT_Purge(g_rr_ft, 1|2);
                int ok2 = 1;
                for (DWORD blk = 0; blk < total && ok2; blk++) {
                    BYTE plain[256] = {0};
                    DWORD off = blk * 256;
                    DWORD copy = (g_dma_size - off < 256) ? (g_dma_size - off) : 256;
                    memcpy(plain, ecuData + off, copy);
                    ok2 = rr_write_block_com(g_rr_com, (int)blk, plain);
                    if (!ok2) wlog("S3: Block %lu FAILED", (unsigned long)blk);
                }
                if (ok2) wlog("S3: *** EPROM WRITE COMPLETE *** %lu blocks", (unsigned long)total);
                else     wlog("S3: Write FAILED");
                g_bridge_done = FALSE;
                g_dma_ready = FALSE;
            }
        }
        return 0;
    }

    /* Intercept ALL transfers in fake mode — no real USB device available.
       TX: log for Sprint 3 protocol capture, fake success.
       RX (non-EP6): return empty data immediately (no 3s WinDriver timeouts).
       Forwarding to real wdapi causes 3s timeouts × N retries = UI freeze.       */
    if (!fRead && pBuffer && dwBytes > 0) {
        log_hex("WDU_Transfer TX (OLS300 cmd)", pBuffer, dwBytes);

        /* ── Sprint 3: Load Bridge ───────────────────────────────────────
           Parse OLS300 DMA pointer commands and write ECU data to Roadrunner.
           UART (COM13) was already opened+inited in WDU_Init before USB activated.
           We are IN-PROCESS in WinOLS so we can read its VA directly.           */
        BYTE* cmd = (BYTE*)pBuffer;
        if (dwBytes == 8 && cmd[0] == 0x1E && cmd[1] == 0x28) {
            DWORD va = ((DWORD)cmd[4]) | ((DWORD)cmd[5]<<8) |
                       ((DWORD)cmd[6]<<16) | ((DWORD)cmd[7]<<24);
            g_dma_start_addr = va;
            g_bridge_done = FALSE;
            g_dma_ready = FALSE;
            g_rom_base = 0;     /* reset — will be rediscovered by scan */
            g_scan_done = 0;    /* allow new scan for this Load */
            wlog("S3: DMA addr=0x%08lX size=0x%04X rr_com=%s",
                 (unsigned long)va, (unsigned)g_dma_size,
                 g_rr_com != INVALID_HANDLE_VALUE ? "OPEN" : "CLOSED");

            /* At 1E 28: release USB + prepare UART. Data is NOT ready yet —
               WinOLS writes it to the DMA buffer after 1E 28.
               Actual write happens at 1E 2C when data is confirmed ready.  */
            if (va > 0x10000) {
                g_bridge_done = TRUE;
                wlog("S3: USB Uninit + UART-Vorbereitung (Daten kommen bei 1E 2C)...");
                /* Release USB so MCU enters download mode */
                if (g_real_driver_handle) {
                    typedef DWORD (__cdecl *FN)(WDU_DRIVER_HANDLE);
                    FN fn_u = (FN)get_real("WDU_Uninit");
                    if (fn_u) { fn_u(g_real_driver_handle); g_real_driver_handle = NULL; }
                }
                Sleep(300);
                /* Reopen D2XX + UART init */
                if (g_rr_ft && g_FT_Close) { g_FT_Close(g_rr_ft); g_rr_ft = NULL; }
                if (g_FT_Open) {
                    void* fth2 = NULL;
                    if (g_FT_Open(0, &fth2) == 0 && fth2) {
                        g_rr_ft = fth2;
                        if (g_FT_SetBitMode) g_FT_SetBitMode(fth2, 0, 0);
                        if (g_FT_SetBaudRate) g_FT_SetBaudRate(fth2, RR_BAUD);
                        if (g_FT_SetDataCharacteristics) g_FT_SetDataCharacteristics(fth2, 8, 0, 0);
                        if (g_FT_SetFlowControl) g_FT_SetFlowControl(fth2, 0, 0, 0);
                        if (g_FT_SetLatencyTimer) g_FT_SetLatencyTimer(fth2, 2);
                        if (g_FT_SetTimeouts) g_FT_SetTimeouts(fth2, 1500, 1500);
                        if (g_FT_ClrDtr) g_FT_ClrDtr(fth2);
                        if (g_FT_Purge) g_FT_Purge(fth2, 1|2);
                    }
                }
                if (rr_init_with_baud(g_rr_com))
                    wlog("S3: UART bereit — warte auf 1E 2C (ECU-Daten)...");
                else
                    wlog("S3: UART init FAILED");
            }
        }
        if (dwBytes == 8 && cmd[0] == 0x1E && cmd[1] == 0x2C) {
            DWORD va2 = ((DWORD)cmd[4]) | ((DWORD)cmd[5]<<8) |
                        ((DWORD)cmd[6]<<16) | ((DWORD)cmd[7]<<24);
            if (g_dma_start_addr > 0 && va2 > g_dma_start_addr)
                g_dma_size = va2 - g_dma_start_addr;
            wlog("S3: 1E 2C ptr2=0x%08lX size=0x%04X — ECU-Daten jetzt bereit",
                 (unsigned long)va2, (unsigned)g_dma_size);
            g_dma_ready = TRUE;  /* signal that 1E 2C has arrived */

            /* Write if ROM base is already known (scan ran before 1E 2C) */
            if (g_bridge_done && g_dma_start_addr > 0 &&
                g_rom_base != 0 && g_rr_com != INVALID_HANDLE_VALUE) {
                BYTE* ecuData = (BYTE*)(uintptr_t)(g_rom_base + g_dma_start_addr);
                DWORD total = (g_dma_size + 255) / 256;
                wlog("S3: Schreibe %lu Blocks, plain[0:4]=%02X %02X %02X %02X",
                     (unsigned long)total,
                     ecuData[0],ecuData[1],ecuData[2],ecuData[3]);
                if (g_rr_ft && g_FT_Purge) g_FT_Purge(g_rr_ft, 1|2);
                int ok = 1;
                for (DWORD blk = 0; blk < total && ok; blk++) {
                    BYTE plain[256] = {0};
                    DWORD off = blk * 256;
                    DWORD copy = (g_dma_size - off < 256) ? (g_dma_size - off) : 256;
                    memcpy(plain, ecuData + off, copy);
                    ok = rr_write_block_com(g_rr_com, (int)blk, plain);
                    if (!ok) wlog("S3: Block %lu FAILED", (unsigned long)blk);
                }
                if (ok) wlog("S3: *** EPROM WRITE COMPLETE *** %lu blocks", (unsigned long)total);
                else    wlog("S3: Write FAILED");
                g_bridge_done = FALSE;  /* allow next Load */
            }
        }
        /* ── End Sprint 3 ─────────────────────────────────────────────── */

        if (pdwBytesTransferred) *pdwBytesTransferred = dwBytes;
        return 0;
    }
    if (fRead && pBuffer && dwBytes > 0) {
        /* EP2 IN (pipe 0x82): OLS300 ACK/firmware version response.
           WinOLS checks firmware checksum after sending 0x2E FE 1F 02 command.
           Expected checksum: 0x044A. Response bytes [0..1] = 0x04 0x4A to pass check.
           Without this, WinOLS uploads the entire 8051 firmware every session. */
        if (dwPipeNum == 0x82 || dwPipeNum == 2) {
            memset(pBuffer, 0, dwBytes);
            /* Response format depends on command:
               64 bytes: firmware version check (0x2E FE 1F 02...)
                         → bytes 0,1 = checksum big-endian: (b0<<8)|b1 = 0x044A
               8 bytes:  EPROM config query (0x20 0x30...) or register command
                         → try echoing back buf[1] in byte[0] as ACK
               other:    all zeros */
            if (dwBytes == 64 && dwBytes > 1) {
                /* WinOLS reads checksum as little-endian WORD at offset 0:
                   val = buf[0] | (buf[1]<<8). Need val=0x044A → buf[0]=0x4A, buf[1]=0x04 */
                ((BYTE*)pBuffer)[0] = 0x4A;  /* LE low byte of 0x044A */
                ((BYTE*)pBuffer)[1] = 0x04;  /* LE high byte of 0x044A */
            } else if (dwBytes == 8) {
                /* 0x20 0x30 hardware status: 0x00=defective, 0x01=OK.
                   Return 0x01 so WinOLS proceeds past the check to send DMA pointer. */
                ((BYTE*)pBuffer)[0] = 0x01;
                ((BYTE*)pBuffer)[1] = 0x00;
                wlog("EP2 IN 8b: returning status=01 (OK) for cmd 20 30");
            }
            /* For other sizes: all zeros = ACK/success */
            if (pdwBytesTransferred) *pdwBytesTransferred = dwBytes;
            wlog("WDU_Transfer EP2 IN pipe=0x%02lX %lu bytes -> LE_val=%04X (want 044A)",
                 (unsigned long)dwPipeNum, (unsigned long)dwBytes,
                 (unsigned)(((BYTE*)pBuffer)[0] | (((BYTE*)pBuffer)[1]<<8)));
            return 0;
        }
        /* Generic RX (EP6 already handled above): return FTDI status bytes.
           EP6 polling: WinOLS keeps connection alive without timing out. */
        if (dwBytes >= 2) {
            ((BYTE*)pBuffer)[0] = 0x01;
            ((BYTE*)pBuffer)[1] = 0x60;
            if (pdwBytesTransferred) *pdwBytesTransferred = 2;
        } else {
            if (pdwBytesTransferred) *pdwBytesTransferred = 0;
        }
        return 0;
    }

    /* Forward to real wdapi1660 for non-read transfers */
    if (get_real("WDU_Transfer")) {
        typedef DWORD (__cdecl *PFN)(WDU_DEVICE_HANDLE,DWORD,DWORD,DWORD,
                                      void*,DWORD,DWORD*,BYTE*,DWORD);
        PFN fn = (PFN)get_real("WDU_Transfer");
        DWORD r = fn(hDevice, dwPipeNum, fRead, dwOptions,
                     pBuffer, dwBytes, pdwBytesTransferred, pSetupPacket, dwTimeout);
        DWORD got = pdwBytesTransferred ? *pdwBytesTransferred : 0;
        wlog("  WDU_Transfer pipe=%lu read=%lu req=%lu -> 0x%lX got=%lu",
             (unsigned long)dwPipeNum, (unsigned long)fRead,
             (unsigned long)dwBytes, (unsigned long)r, (unsigned long)got);
        if (r == 0 && fRead && pBuffer && got > 0 && got < 10000)
            log_hex("WDU_Transfer RX", pBuffer, got);
        return r;
    }
    if (pdwBytesTransferred) *pdwBytesTransferred = 0;
    return 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_TransferBulk(WDU_DEVICE_HANDLE hDevice,
                                 DWORD dwPipeNum, void* pBuffer,
                                 DWORD* pdwBytes, DWORD dwOptions,
                                 DWORD dwTimeout) {
    DWORD sz = pdwBytes ? *pdwBytes : 0;
    if (pBuffer && sz > 0)
        log_hex("WDU_TransferBulk TX", pBuffer, sz);

    /* Forward to real wdapi1660 */
    if (g_real_driver_handle && get_real("WDU_TransferBulk")) {
        typedef DWORD (__cdecl *PFN)(WDU_DEVICE_HANDLE,DWORD,void*,DWORD*,DWORD,DWORD);
        PFN fn = (PFN)get_real("WDU_TransferBulk");
        DWORD r = fn(g_real_driver_handle, dwPipeNum, pBuffer, pdwBytes, dwOptions, dwTimeout);
        wlog("  WDU_TransferBulk (real) pipe=%lu -> 0x%lX got=%lu",
             (unsigned long)dwPipeNum, (unsigned long)r,
             pdwBytes ? (unsigned long)*pdwBytes : 0);
        if (pBuffer && pdwBytes && *pdwBytes > 0)
            log_hex("WDU_TransferBulk RX", pBuffer, *pdwBytes);
        return r;
    }
    if (pdwBytes) *pdwBytes = 0;
    return 0;
}

/* ── WDU Stream functions ─────────────────────────────────────────────── */
/* (fake stream handle array declared at top of file) */

__declspec(dllexport)
DWORD __cdecl WDU_StreamOpen(WDU_DEVICE_HANDLE hDevice, DWORD dwPipeNum,
                              DWORD dwBufferSize, DWORD dwRxSize,
                              BOOL fBlocking, DWORD dwOptions,
                              DWORD dwTimeout, void** phStream) {
    wlog("WDU_StreamOpen(pipe=%lu) -> fake handle", (unsigned long)dwPipeNum);
    /* Return valid non-NULL handle so WinOLS won't write-to-NULL crash */
    if (phStream) *phStream = g_fake_stream_data;
    return 0; /* WD_STATUS_SUCCESS */
}

__declspec(dllexport)
DWORD __cdecl WDU_StreamRead(void* hStream, void* pBuffer, DWORD bytes,
                              DWORD* pdwBytesRead) {
    /* TODO: read from Roadrunner, translate to OLS300 response */
    if (pdwBytesRead) *pdwBytesRead = 0;
    wlog("WDU_StreamRead(%lu bytes requested) -> 0 bytes (TODO: Roadrunner)", (unsigned long)bytes);
    return 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_StreamWrite(void* hStream, const void* pBuffer,
                               DWORD bytes, DWORD* pdwBytesWritten) {
    /* TODO: translate OLS300 command to Roadrunner MoatesWare */
    if (pBuffer && bytes > 0)
        log_hex("WDU_StreamWrite TX (OLS300 cmd)", pBuffer, bytes);
    if (pdwBytesWritten) *pdwBytesWritten = bytes;
    return 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_StreamClose(void* hStream) {
    wlog("WDU_StreamClose -> fake OK");
    return 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_StreamStart(void* hStream) {
    wlog("WDU_StreamStart -> fake OK");
    return 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_StreamStop(void* hStream) {
    wlog("WDU_StreamStop -> fake OK");
    return 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_StreamFlush(void* hStream) { return 0; }

__declspec(dllexport)
DWORD __cdecl WDU_StreamGetStatus(void* hStream, BOOL* pfIsRunning,
                                   DWORD* pdwLastError, DWORD* pdwBytesInBuf) {
    if (pfIsRunning)   *pfIsRunning   = TRUE;
    if (pdwLastError)  *pdwLastError  = 0;
    if (pdwBytesInBuf) *pdwBytesInBuf = 0;
    return 0;
}

/* ── Device info functions ───────────────────────────────────────────── */
__declspec(dllexport)
DWORD __cdecl WDU_GetDeviceInfo(WDU_DEVICE_HANDLE hDevice, void** ppDeviceInfo) {
    /* Return our fake device — do NOT call real DLL (fake handle would crash) */
    wlog("WDU_GetDeviceInfo(handle=%p) -> fake device", hDevice);
    if (ppDeviceInfo) *ppDeviceInfo = &g_fake_device;
    return 0;
}

__declspec(dllexport)
void __cdecl WDU_PutDeviceInfo(void* pDeviceInfo) {
    /* No-op — we own the fake device memory, don't free it */
    (void)pDeviceInfo;
}

__declspec(dllexport)
DWORD __cdecl WDU_GetDeviceAddr(WDU_DEVICE_HANDLE hDevice,
                                 DWORD* pdwBusNum, DWORD* pdwDevAddr) {
    wlog("WDU_GetDeviceAddr -> fake bus=0 addr=1");
    if (pdwBusNum)  *pdwBusNum  = 0;
    if (pdwDevAddr) *pdwDevAddr = 1;
    return 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_ResetDevice(WDU_DEVICE_HANDLE hDevice, DWORD dwOptions) {
    wlog("WDU_ResetDevice -> fake OK");
    return 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_ResetPipe(WDU_DEVICE_HANDLE hDevice, DWORD dwPipeNum) { return 0; }

__declspec(dllexport)
DWORD __cdecl WDU_SetInterface(WDU_DEVICE_HANDLE hDevice,
                                DWORD dwInterfaceNum, DWORD dwAlternateSetting) { return 0; }

__declspec(dllexport)
DWORD __cdecl WDU_HaltTransfer(WDU_DEVICE_HANDLE hDevice, DWORD dwPipeNum) { return 0; }

__declspec(dllexport)
DWORD __cdecl WDU_SelectiveSuspend(WDU_DEVICE_HANDLE hDevice, DWORD dwOptions) { return 0; }

__declspec(dllexport)
DWORD __cdecl WDU_Wakeup(WDU_DEVICE_HANDLE hDevice, DWORD dwOptions) { return 0; }

__declspec(dllexport)
DWORD __cdecl WDU_GetLangIDs(WDU_DEVICE_HANDLE hDevice, BYTE* pbNumSupportedLangIDs,
                              WORD* pLangIDs, DWORD dwLangIDsSize) {
    /* Return English (0x0409) as supported language */
    if (pbNumSupportedLangIDs) *pbNumSupportedLangIDs = 1;
    if (pLangIDs && dwLangIDsSize >= 2) pLangIDs[0] = 0x0409;
    return 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_GetStringDesc(WDU_DEVICE_HANDLE hDevice, BYTE bStrIndex,
                                 void* pbBuf, DWORD dwBufSize, WORD wLangID,
                                 DWORD* pdwDescSize) {
    wlog("WDU_GetStringDesc(handle=%p idx=%u langID=0x%04X bufSize=%lu)",
         hDevice, bStrIndex, wLangID, (unsigned long)dwBufSize);

    /* Intercept serial number request (index from iSerialNumber in descriptor).
       Return a fixed serial "BSL100001" so WinOLS can match it. */
    if (bStrIndex > 0 && pbBuf && dwBufSize >= 20) {
        /* USB string descriptor: length(1) + type(1) + UTF-16LE string */
        const wchar_t* serial = L"BSL100001";
        DWORD slen = (DWORD)(wcslen(serial) * 2);
        BYTE* b = (BYTE*)pbBuf;
        b[0] = (BYTE)(2 + slen);   /* bLength */
        b[1] = 0x03;               /* bDescriptorType = STRING */
        memcpy(b + 2, serial, slen);
        if (pdwDescSize) *pdwDescSize = 2 + slen;
        wlog("  Returned serial string idx=%u: BSL100001", bStrIndex);
        return 0; /* WD_STATUS_SUCCESS */
    }
    return 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_GetDeviceRegistryProperty(WDU_DEVICE_HANDLE hDevice,
        void* pProperty, DWORD property, void* pBuf, DWORD* pdwSize) {
    typedef DWORD (__cdecl *PFN)(WDU_DEVICE_HANDLE,void*,DWORD,void*,DWORD*);
    PFN fn = (PFN)get_real("WDU_GetDeviceRegistryProperty");
    return fn ? fn(hDevice, pProperty, property, pBuf, pdwSize) : 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_TransferDefaultPipe(WDU_DEVICE_HANDLE hDevice,
        DWORD fRead, DWORD dwOptions, void* pBuffer, DWORD dwBytes,
        DWORD* pdwBytesTransferred, BYTE* pSetupPacket, DWORD dwTimeout) {
    if (!fRead && pBuffer && dwBytes > 0)
        log_hex("WDU_TransferDefaultPipe TX", pBuffer, dwBytes);
    typedef DWORD (__cdecl *PFN)(WDU_DEVICE_HANDLE,DWORD,DWORD,void*,DWORD,DWORD*,BYTE*,DWORD);
    PFN fn = (PFN)get_real("WDU_TransferDefaultPipe");
    if (!fn) return 0xFFFFFFFF;
    DWORD r = fn(hDevice, fRead, dwOptions, pBuffer, dwBytes,
                 pdwBytesTransferred, pSetupPacket, dwTimeout);
    if (fRead && pBuffer && pdwBytesTransferred && *pdwBytesTransferred > 0)
        log_hex("WDU_TransferDefaultPipe RX", pBuffer, *pdwBytesTransferred);
    return r;
}

__declspec(dllexport)
DWORD __cdecl WDU_TransferInterrupt(WDU_DEVICE_HANDLE hDevice,
        DWORD dwPipeNum, DWORD fRead, DWORD dwOptions,
        void* pBuffer, DWORD dwBytes, DWORD* pdwBytesTransferred, DWORD dwTimeout) {
    typedef DWORD (__cdecl *PFN)(WDU_DEVICE_HANDLE,DWORD,DWORD,DWORD,void*,DWORD,DWORD*,DWORD);
    PFN fn = (PFN)get_real("WDU_TransferInterrupt");
    return fn ? fn(hDevice, dwPipeNum, fRead, dwOptions, pBuffer, dwBytes,
                   pdwBytesTransferred, dwTimeout) : 0xFFFFFFFF;
}

__declspec(dllexport)
DWORD __cdecl WDU_TransferIsoch(WDU_DEVICE_HANDLE hDevice,
        DWORD dwPipeNum, DWORD fRead, DWORD dwOptions,
        void* pBuffer, DWORD dwBytes, DWORD* pdwBytesTransferred, DWORD dwTimeout) {
    typedef DWORD (__cdecl *PFN)(WDU_DEVICE_HANDLE,DWORD,DWORD,DWORD,void*,DWORD,DWORD*,DWORD);
    PFN fn = (PFN)get_real("WDU_TransferIsoch");
    return fn ? fn(hDevice, dwPipeNum, fRead, dwOptions, pBuffer, dwBytes,
                   pdwBytesTransferred, dwTimeout) : 0xFFFFFFFF;
}

/* ── WDC / WD passthrough functions (all forwarded) ─────────────────── */
#define FWD(ret, name, ...) \
__declspec(dllexport) ret __cdecl name(__VA_ARGS__) { \
    typedef ret (__cdecl *PFN)(__VA_ARGS__); \
    PFN fn = (PFN)get_real(#name); \
    if (!fn) return (ret)0; \
    return fn; \
}

/* Simple zero-arg passthrough helpers */
__declspec(dllexport) DWORD __cdecl WDC_DriverOpen(void* pCfg, const char* pcLic) {
    /* Fake success — WinDriver kernel not installed */
    wlog("WDC_DriverOpen -> fake success");
    return 0;
}

__declspec(dllexport) DWORD __cdecl WDC_DriverClose(void) {
    wlog("WDC_DriverClose -> fake OK");
    return 0;
}

__declspec(dllexport) DWORD __cdecl WDC_Version(char* pVer, DWORD dwLen) {
    wlog("WDC_Version called");
    if (pVer && dwLen > 10) strncpy_s(pVer, dwLen, "11.0.0", _TRUNCATE);
    return 0;
}

/* ── Catch-all logger for WDC functions called by WinOLS ────────────── */
__declspec(dllexport) DWORD __cdecl WDC_CallKerPlug_log(void* a, void* b) {
    wlog("WDC_CallKerPlug called!");
    return 0;
}

/* Stub macros — no real DLL, just return 0 */
#define PT0(name) __declspec(dllexport) DWORD __cdecl name(void) { return 0; }
#define PT1(name, T1) __declspec(dllexport) DWORD __cdecl name(T1 a) { (void)a; return 0; }
#define PT2(name, T1, T2) __declspec(dllexport) DWORD __cdecl name(T1 a, T2 b) { (void)a;(void)b; return 0; }
#define PT3(name, T1, T2, T3) __declspec(dllexport) DWORD __cdecl name(T1 a,T2 b,T3 c) { (void)a;(void)b;(void)c; return 0; }

PT1(WDC_Err, DWORD)
PT1(WDC_Trace, DWORD)
PT1(WDC_SetDebugOptions, DWORD)
PT1(WDC_GetWDHandle, void*)
PT1(WDC_GetBusType, void*)
PT1(WDC_GetDevContext, void*)
PT1(WDC_EventIsRegistered, void*)
PT1(WDC_IntIsEnabled, void*)
PT1(SleepWrapper, DWORD)
PT1(PrintDbgMessage, const char*)
PT1(vPrintDbgMessage, const char*)
PT2(WD_LogAdd, DWORD, const char*)
PT0(WD_CloseLog)
PT0(WD_LogStop)
PT0(WD_OpenLog)
PT0(WD_LogStart)
PT0(WDC_Sleep)
PT0(get_os_type)

/* ── Stubs for all remaining exports (previously DEF-forwarded) ─────── */
PT1(OsMutexCreate,  void*)
PT1(OsMutexClose,   void*)
PT1(OsMutexLock,    void*)
PT1(OsMutexUnlock,  void*)
PT1(OsEventCreate,  void*)
PT1(OsEventClose,   void*)
PT1(OsEventReset,   void*)
PT1(OsEventSignal,  void*)
PT2(OsEventWait,    void*, DWORD)

/* ── Event / Interrupt helpers ───────────────────────────────────────── */
PT1(EventAlloc,    void*)
PT2(EventDup,      void*, void*)
PT1(EventFree,     void*)
PT2(EventRegister,   void*, void*)
PT1(EventUnregister, void*)
PT2(InterruptEnable,  void*, void*)
PT1(InterruptDisable, void*)
PT2(InterruptThreadEnable,  void*, void*)
PT1(InterruptThreadDisable, void*)
PT1(FreeDllPtr,    void*)
PT0(GetPageCount)
PT0(GetPageSize)

/* ── Thread helpers ──────────────────────────────────────────────────── */
PT2(ThreadStart, void*, void*)
PT1(ThreadStop,  void*)
PT1(ThreadWait,  void*)

/* ── Util helpers ────────────────────────────────────────────────────── */
PT0(UtilClrScr)
PT1(UtilGetFileName,      void*)
PT1(UtilGetFileSize,      void*)
PT1(UtilGetStringFromUser, void*)
PT1(Stat2Str, DWORD)

/* ── VB helpers ──────────────────────────────────────────────────────── */
PT2(VB_EventRegister,   void*, void*)
PT1(VB_EventUnregister, void*)
PT2(VB_InterruptEnable,  void*, void*)
PT1(VB_InterruptDisable, void*)
PT1(VB_Stat2Str, DWORD)
PT2(VB_ThreadLoopStart, void*, void*)
PT1(VB_ThreadLoopStop,  void*)
PT2(WDU_VB_Init,   void*, void*)
PT1(WDU_VB_Uninit, void*)
PT2(WD_VB_DriverName, void*, void*)
PT2(WD_VB_InterruptThreadEnable,  void*, void*)
PT1(WD_VB_InterruptThreadDisable, void*)

/* ── HS (Hardware Spy) ───────────────────────────────────────────────── */
PT2(HSConfigurePci, void*, void*)
PT2(HSWatchAlloc,   void*, void*)
PT1(HSWatchFree,    void*)
PT2(PciEventCreate,    void*, void*)
PT2(PcmciaEventCreate, void*, void*)

/* ── WDC device/addr/DMA ─────────────────────────────────────────────── */
PT2(WDC_AddrSpaceIsActive, void*, DWORD)
PT2(WDC_CallKerPlug,   void*, void*)
PT2(WDC_CardCleanupSetup, void*, void*)
PT1(WDC_DMABufUnlock,  void*)
PT2(WDC_DMAContigBufLock, void*, void*)
PT2(WDC_DMASGBufLock,  void*, void*)
PT1(WDC_DMASyncCpu,    void*)
PT1(WDC_DMASyncIo,     void*)
PT2(WDC_EventRegister,   void*, void*)
PT1(WDC_EventUnregister, void*)
PT2(WDC_IntEnable,   void*, void*)
PT1(WDC_IntDisable,  void*)
PT2(WDC_IsaDeviceOpen,  void*, void*)
PT1(WDC_IsaDeviceClose, void*)
PT2(WDC_KernelPlugInOpen, void*, void*)
PT2(WDC_MultiTransfer,  void*, DWORD)
PT2(WDC_PciDeviceOpen,  void*, void*)
PT1(WDC_PciDeviceClose, void*)
PT2(WDC_PciGetDeviceInfo, void*, void*)
PT2(WDC_PciScanDevices,           void*, void*)
PT2(WDC_PciScanDevicesByTopology,  void*, void*)
PT2(WDC_PciScanRegisteredDevices,  void*, void*)
PT2(WDC_PcmciaDeviceOpen,   void*, void*)
PT1(WDC_PcmciaDeviceClose,  void*)
PT2(WDC_PcmciaGetDeviceInfo, void*, void*)
PT2(WDC_PcmciaScanDevices,   void*, void*)
PT2(WDC_PcmciaSetVpp,        void*, DWORD)
PT2(WDC_PcmciaSetWindow,     void*, void*)
PT2(WDC_PcmciaReadAttribSpace,  void*, void*)
PT2(WDC_PcmciaWriteAttribSpace, void*, void*)
PT2(WDC_SharedBufferAlloc, DWORD, void*)
PT2(WDC_ReadAddrBlock,  void*, void*)
PT2(WDC_WriteAddrBlock, void*, void*)

/* ── WDC Read/Write addr (all widths) ────────────────────────────────── */
#define PT_RWADDR(name) \
PT2(name##8,  void*, DWORD) \
PT2(name##16, void*, DWORD) \
PT2(name##32, void*, DWORD) \
PT2(name##64, void*, DWORD)

PT_RWADDR(WDC_ReadAddr)
PT_RWADDR(WDC_WriteAddr)
PT_RWADDR(WDC_PciReadCfg)
PT_RWADDR(WDC_PciWriteCfg)
PT_RWADDR(WDC_PciReadCfgBySlot)
PT_RWADDR(WDC_PciWriteCfgBySlot)
/* base-variant stubs (no width suffix) */
PT2(WDC_PciReadCfg,      void*, void*)
PT2(WDC_PciWriteCfg,     void*, void*)
PT2(WDC_PciReadCfgBySlot,  void*, void*)
PT2(WDC_PciWriteCfgBySlot, void*, void*)

/* ── WD logging / driver name ─────────────────────────────────────────── */
PT1(WD_DriverName,   const char*)
PT1(WdFunctionLog,   void*)
