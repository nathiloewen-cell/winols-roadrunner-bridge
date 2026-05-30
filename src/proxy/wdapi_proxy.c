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
        log_init();
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

/* Forward declarations for async attach */
static DWORD WINAPI attach_thread(LPVOID param);
static WDU_ATTACH_CALLBACK g_attach_cb         = NULL;
static PVOID               g_attach_userdata   = NULL;
static WDU_DEVICE_HANDLE   g_attach_handle     = NULL;
static WDU_DRIVER_HANDLE   g_real_driver_handle = NULL; /* real wdapi1660 handle */

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

        WDU_DRIVER_HANDLE real_handle = NULL;
        DWORD r = real_init(&real_handle, pMatchTables, dwNumMatchTables,
                            pEventTable, "12345abcde1234.license", dwOptions);
        wlog("  WDU_Init (real) -> 0x%08lX real_handle=%p",
             (unsigned long)r, real_handle);
        if (r == 0 && real_handle) {
            /* WDU_Init succeeded with real wdapi1660, but the handle is WD16-format
               and incompatible with WinOLS compiled for WD11. Fall through to fake mode
               which uses WD11-compatible fake handle. Store real handle for WDU_Transfer. */
            wlog("  WDU_Init real SUCCESS (handle=%p) but WD16/WD11 compat issue — using fake mode", real_handle);
            g_attach_handle = NULL;  /* force fake mode to avoid WD11/WD16 crash */
            /* Fall through to fake mode below */
        }
        if (r == 0 && real_handle) {
            /* WDU_Init succeeded! Store real handle for WDU_Transfer forwarding.
               WinOLS gets fake handle (no WD16/WD11 crash), but WDU_Transfer
               uses the real handle → Roadrunner receives actual OLS300 commands! */
            g_real_driver_handle = real_handle;
            wlog("  Real handle stored for WDU_Transfer forwarding: %p", real_handle);
            if (phDriver) *phDriver = real_handle;
            wlog("  WDU_Init SUCCESS with real handle %p", real_handle);
            if (pEventTable) {
                WDU_EVENT_TABLE* tbl = (WDU_EVENT_TABLE*)pEventTable;
                if (tbl->pfDeviceAttach) {
                    g_attach_cb       = tbl->pfDeviceAttach;
                    g_attach_userdata = tbl->pUserData;
                    g_attach_handle   = real_handle;
                    wlog("  Scheduling pfDeviceAttach with real handle + NULL device");
                    HANDLE ht = CreateThread(NULL, 0, attach_thread, NULL,
                                             CREATE_SUSPENDED, NULL);
                    if (ht) {
                        SetThreadPriority(ht, THREAD_PRIORITY_BELOW_NORMAL);
                        ResumeThread(ht); CloseHandle(ht);
                    }
                }
            }
            return r;
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
    Sleep(500);
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
    return 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_Uninit(WDU_DRIVER_HANDLE hDriver) {
    wlog("WDU_Uninit(handle=%p)", hDriver);
    /* After disconnect, re-trigger attach so WinOLS sees device reconnect.
       This simulates the OLS300 device being present persistently.         */
    if (g_attach_cb) {
        HANDLE ht = CreateThread(NULL, 0, attach_thread, NULL,
                                 CREATE_SUSPENDED, NULL);
        if (ht) {
            SetThreadPriority(ht, THREAD_PRIORITY_BELOW_NORMAL);
            ResumeThread(ht);
            CloseHandle(ht);
        }
    }
    return 0;
}

/* ── WDU_Transfer / WDU_TransferBulk — intercept data ───────────────── */
__declspec(dllexport)
DWORD __cdecl WDU_Transfer(WDU_DEVICE_HANDLE hDevice,
                            DWORD dwPipeNum, DWORD fRead,
                            DWORD dwOptions, void* pBuffer,
                            DWORD dwBytes, DWORD* pdwBytesTransferred,
                            BYTE* pSetupPacket, DWORD dwTimeout) {
    if (!fRead && pBuffer && dwBytes > 0)
        log_hex("WDU_Transfer TX", pBuffer, dwBytes);

    /* Intercept pipe 0x86 (Bulk IN) reads — these are OLS300 identification requests.
       The OLS300 responds with its firmware info. We fake this response so WinOLS
       accepts the connection. Based on reverse engineering: WinOLS stores "OLS821"
       as module identifier; return minimal OLS identification response. */
    if (fRead && (dwPipeNum == 0x86 || dwPipeNum == 134) && pBuffer && dwBytes >= 16) {
        /* OLS300 identification response (structure discovered from reverse engineering):
           Bytes 0-7: model string "OLS821\0\0"  (or similar firmware version)
           Bytes 8-N: firmware data, status flags, capabilities
           Return enough data to make WinOLS accept the module. */
        memset(pBuffer, 0, dwBytes < 448 ? dwBytes : 448);
        BYTE* b = (BYTE*)pBuffer;
        /* From reverse engineering: OLS module struct stores "OLS821" at offset 0x50=80.
           This comes from the WDU_Transfer init response. Try various locations. */
        /* Try: offset 0 header */
        b[0] = 0x01;  /* magic/version */
        b[1] = 0x00;
        /* offset 0x08 = 8: status */
        b[8] = 0x01;
        /* offset 0x10 = 16: type identifier */
        b[16] = 0x03;  /* OLS300 type */
        /* offset 0x50 = 80: firmware version string "OLS821" */
        if ((int)dwBytes > 86) {
            b[0x50] = 0x4F; b[0x51] = 0x4C; b[0x52] = 0x53;  /* OLS */
            b[0x53] = 0x38; b[0x54] = 0x32; b[0x55] = 0x31;  /* 821 */
        }
        /* offset 0xD0 = 208: second copy */
        if ((int)dwBytes > 214) {
            b[0xD0] = 0x4F; b[0xD1] = 0x4C; b[0xD2] = 0x53;
            b[0xD3] = 0x38; b[0xD4] = 0x32; b[0xD5] = 0x31;
        }
        if (pdwBytesTransferred) *pdwBytesTransferred = dwBytes < 448 ? dwBytes : 448;
        wlog("WDU_Transfer FAKE OLS300 ID response (pipe=0x%lX, %lu bytes)",
             (unsigned long)dwPipeNum, (unsigned long)*pdwBytesTransferred);
        return 0;  /* WD_STATUS_SUCCESS */
    }

    /* Log other transfers for protocol discovery */
    if (!fRead && pBuffer && dwBytes > 0)
        log_hex("WDU_Transfer TX (OLS300 cmd)", pBuffer, dwBytes);

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
