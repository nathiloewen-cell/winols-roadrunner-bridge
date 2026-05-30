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
    /* _fsopen with _SH_DENYWR allows other processes to read while we write */
    g_log = _fsopen(path, "a", 0x20 /* _SH_DENYWR */);
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

/* ── Vectored Exception Handler: intercept NULL-write crash ─────────── */
static BYTE g_safe_write_buf[4096];

static LONG WINAPI veh_handler(EXCEPTION_POINTERS* pEx) {
    if (!pEx || !pEx->ExceptionRecord || !pEx->ContextRecord)
        return EXCEPTION_CONTINUE_SEARCH;
    if (pEx->ExceptionRecord->ExceptionCode != EXCEPTION_ACCESS_VIOLATION)
        return EXCEPTION_CONTINUE_SEARCH;
    DWORD op    = (DWORD)pEx->ExceptionRecord->ExceptionInformation[0];
    DWORD fault = (DWORD)pEx->ExceptionRecord->ExceptionInformation[1];
    /* Catch: write to NULL/low addresses AND write to kernel-space (>0x80000000) */
    BOOL is_bad = (op == 1) && (fault < 0x10000 || fault >= 0x80000000);
    if (is_bad) {
        CONTEXT* ctx = pEx->ContextRecord;
        DWORD safe   = (DWORD)(uintptr_t)g_safe_write_buf;
        wlog("VEH: bad write at EIP=0x%08lX fault=0x%08lX — redirecting",
             (unsigned long)pEx->ExceptionRecord->ExceptionAddress,
             (unsigned long)fault);
        /* Redirect any register pointing to the bad address */
        if (ctx->Eax == fault || ctx->Eax < 0x10000 || ctx->Eax >= 0x80000000) ctx->Eax = safe;
        if (ctx->Ebx == fault || ctx->Ebx < 0x10000 || ctx->Ebx >= 0x80000000) ctx->Ebx = safe;
        if (ctx->Ecx == fault || ctx->Ecx < 0x10000 || ctx->Ecx >= 0x80000000) ctx->Ecx = safe;
        if (ctx->Edx == fault || ctx->Edx < 0x10000 || ctx->Edx >= 0x80000000) ctx->Edx = safe;
        if (ctx->Esi == fault || ctx->Esi < 0x10000 || ctx->Esi >= 0x80000000) ctx->Esi = safe;
        if (ctx->Edi == fault || ctx->Edi < 0x10000 || ctx->Edi >= 0x80000000) ctx->Edi = safe;
        return EXCEPTION_CONTINUE_EXECUTION;
    }
    return EXCEPTION_CONTINUE_SEARCH;
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
        /* Load the real wdapi1100 from our backup name */
        char path[MAX_PATH];
        GetModuleFileNameA(NULL, path, MAX_PATH);
        char* last = strrchr(path, '\\');
        if (last) {
            strcpy_s(last+1, MAX_PATH - (last-path) - 1, "wdapi1100_real.dll");
        }
        g_real = LoadLibraryA(path);
        if (g_real) {
            wlog("Loaded real wdapi from: %s", path);
        } else {
            /* Try System32 as fallback */
            g_real = LoadLibraryA("wdapi1100_real.dll");
            if (!g_real) wlog("WARNING: could not load wdapi1100_real.dll");
        }
    } else if (reason == DLL_PROCESS_DETACH) {
        wlog("wdapi proxy unloaded");
        log_close();
        if (g_real) FreeLibrary(g_real);
    }
    return TRUE;
}

/* ── OLS300 device identity (confirmed from WDU_Init log) ───────────── */
#define OLS300_VID  0x0547
#define OLS300_PID  0x3000

/* (fake handle arrays declared at top of file) */

#define FAKE_DRIVER_HANDLE  ((WDU_DRIVER_HANDLE)g_fake_driver_data)
#define FAKE_DEVICE_HANDLE  ((WDU_DEVICE_HANDLE)g_fake_device_data)

/* ── WinDriver USB device structures (minimal subset) ───────────────── */
typedef struct {
    BYTE  bLength; BYTE bDescriptorType; WORD bcdUSB;
    BYTE  bDeviceClass; BYTE bDeviceSubClass; BYTE bDeviceProtocol;
    BYTE  bMaxPacketSize0;
    WORD  idVendor; WORD idProduct; WORD bcdDevice;
    BYTE  iManufacturer; BYTE iProduct; BYTE iSerialNumber;
    BYTE  bNumConfigurations;
} WDU_DEVICE_DESCRIPTOR;

typedef struct {
    BYTE bEndpointAddress;  /* 0x02=BulkOUT, 0x86=BulkIN */
    BYTE bmAttributes;      /* 0x02 = Bulk */
    WORD wMaxPacketSize;
    BYTE bInterval;
    BYTE bPipeType;         /* WDU_PIPE_TYPE_BULK = 3 */
    DWORD dwNumber;         /* pipe index used in WDU_Transfer */
    DWORD dwMaximumPacketSize;
    BYTE direction;         /* 0=OUT, 1=IN */
    BYTE pad[3];
} WDU_PIPE_INFO;

typedef struct {
    BYTE bInterfaceNumber; BYTE bAlternateSetting;
    BYTE bNumEndpoints;    BYTE bInterfaceClass;
    BYTE bInterfaceSubClass; BYTE bInterfaceProtocol;
    BYTE iInterface;       BYTE pad;
    WDU_PIPE_INFO* pPipes;
} WDU_ALTERNATE_SETTING;

typedef struct {
    WDU_ALTERNATE_SETTING* pAlternateSettings;
    DWORD dwNumAltSettings;
    WDU_ALTERNATE_SETTING* pActiveAltSetting;
} WDU_INTERFACE;

typedef struct {
    BYTE bLength; BYTE bDescriptorType; WORD wTotalLength;
    BYTE bNumInterfaces; BYTE bConfigurationValue;
    BYTE iConfiguration; BYTE bmAttributes; BYTE MaxPower;
} WDU_CONFIGURATION_DESCRIPTOR;

typedef struct {
    WDU_CONFIGURATION_DESCRIPTOR Descriptor;
    WDU_INTERFACE* pInterfaces;
    DWORD dwNumInterfaces;
} WDU_CONFIGURATION;

/* WD_MAXDEVICES=16 confirmed: WinOLS reads pActiveInterface[5] = offset 48
   (20 bytes descriptor+pad + 4 pConfigs + 4 pActiveConfig + 5*4 = 48) */
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

/* ── Fake OLS300 USB device info ─────────────────────────────────────── */
static WDU_PIPE_INFO g_pipes[2] = {
    /* Bulk OUT pipe 0 — WinOLS sends commands on this */
    { 0x02, 0x02, 64, 0, 3, 0, 64, 0, {0,0,0} },
    /* Bulk IN  pipe 1 — WinOLS reads responses on this */
    { 0x86, 0x02, 64, 0, 3, 1, 64, 1, {0,0,0} },
};
static WDU_ALTERNATE_SETTING g_altset = {
    0, 0, 2, 0xFF, 0, 0, 0, 0, g_pipes
};
static WDU_INTERFACE g_iface = { &g_altset, 1, &g_altset };
static WDU_CONFIGURATION_DESCRIPTOR g_cfgdesc = {
    9, 2, sizeof(WDU_CONFIGURATION_DESCRIPTOR), 1, 1, 0, 0x80, 250
};
static WDU_CONFIGURATION g_config;   /* initialized in WDU_Init */
static WDU_DEVICE        g_fake_device;

/* Forward declarations for async attach */
static DWORD WINAPI attach_thread(LPVOID param);
static WDU_ATTACH_CALLBACK g_attach_cb       = NULL;
static PVOID               g_attach_userdata = NULL;

/* ── WDU_Init — fake success + trigger attach callback ──────────────── */
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

    if (phDriver) *phDriver = FAKE_DRIVER_HANDLE;
    wlog("  WDU_Init -> fake success, now triggering attach callback");

    /* Build fake device structures at runtime (can't use static init with ptrs) */
    g_config.Descriptor   = g_cfgdesc;
    g_config.pInterfaces  = &g_iface;
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
    /* Fill all WD_MAXDEVICES entries — WinOLS reads up to index 5 at minimum */
    for (int i = 0; i < WD_MAXDEVICES; i++)
        g_fake_device.pActiveInterface[i] = &g_altset;

    /* ASYNC: call pfDeviceAttach from a worker thread 200ms after WDU_Init
       returns. Calling it synchronously (from inside WDU_Init) means WinOLS
       hasn't finished its own initialization yet, so it returns 0 (reject).
       Giving WinOLS 200ms to complete init lets the callback succeed. */
    if (pEventTable) {
        WDU_EVENT_TABLE* tbl = (WDU_EVENT_TABLE*)pEventTable;
        if (tbl->pfDeviceAttach) {
            g_attach_cb       = tbl->pfDeviceAttach;
            g_attach_userdata = tbl->pUserData;
            wlog("  Scheduling async pfDeviceAttach (200ms delay)...");
            CreateThread(NULL, 0, attach_thread, NULL, 0, NULL);
        }
    }
    return 0;
}

static DWORD WINAPI attach_thread(LPVOID param) {
    (void)param;
    Sleep(200);
    if (!g_attach_cb) return 0;
    wlog("[async] pfDeviceAttach(handle=%p device=%p userData=%p)",
         FAKE_DEVICE_HANDLE, &g_fake_device, g_attach_userdata);
    BOOL ok = g_attach_cb(FAKE_DEVICE_HANDLE, &g_fake_device, g_attach_userdata);
    wlog("[async] pfDeviceAttach returned %d", ok);
    return 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_Uninit(WDU_DRIVER_HANDLE hDriver) {
    wlog("WDU_Uninit -> fake OK");
    return 0;
}

/* ── WDU_Transfer / WDU_TransferBulk — intercept data ───────────────── */
__declspec(dllexport)
DWORD __cdecl WDU_Transfer(WDU_DEVICE_HANDLE hDevice,
                            DWORD dwPipeNum, DWORD fRead,
                            DWORD dwOptions, void* pBuffer,
                            DWORD dwBytes, DWORD* pdwBytesTransferred,
                            BYTE* pSetupPacket, DWORD dwTimeout) {
    /* TODO S5: translate OLS300 protocol to Roadrunner MoatesWare */
    if (!fRead && pBuffer && dwBytes > 0)
        log_hex("WDU_Transfer TX (OLS300 cmd)", pBuffer, dwBytes);
    if (pdwBytesTransferred) *pdwBytesTransferred = 0;
    return 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_TransferBulk(WDU_DEVICE_HANDLE hDevice,
                                 DWORD dwPipeNum, void* pBuffer,
                                 DWORD* pdwBytes, DWORD dwOptions,
                                 DWORD dwTimeout) {
    /* TODO S6: translate OLS300 bulk transfer to Roadrunner MoatesWare */
    DWORD sz = pdwBytes ? *pdwBytes : 0;
    if (pBuffer && sz > 0)
        log_hex("WDU_TransferBulk TX (OLS300 cmd)", pBuffer, sz);
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
    typedef DWORD (__cdecl *PFN)(char*, DWORD);
    PFN fn = (PFN)get_real("WDC_Version");
    DWORD r = fn ? fn(pVer, dwLen) : 0;
    if (pVer) wlog("WDC_Version -> '%s'", pVer);
    return r;
}

/* All remaining wdapi exports — simple passthrough via GetProcAddress */
#define PT0(name) __declspec(dllexport) DWORD __cdecl name(void) \
    { typedef DWORD (__cdecl *F)(void); F f=(F)get_real(#name); return f?f():0; }

#define PT1(name, T1) __declspec(dllexport) DWORD __cdecl name(T1 a) \
    { typedef DWORD (__cdecl *F)(T1); F f=(F)get_real(#name); return f?f(a):0; }

#define PT2(name, T1, T2) __declspec(dllexport) DWORD __cdecl name(T1 a, T2 b) \
    { typedef DWORD (__cdecl *F)(T1,T2); F f=(F)get_real(#name); return f?f(a,b):0; }

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

/* ── All other exports are forwarded via wdapi1100.def → wdapi1100_real ─
   Do NOT add PT macros here — wrong arg counts cause access violations.
   The DEF file forwarder approach passes args unchanged.              ── */
#if 0  /* disabled - use DEF forwarders instead */
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

/* ── WD logging / driver name ─────────────────────────────────────────── */
PT1(WD_DriverName,   const char*)
PT1(WdFunctionLog,   void*)
#endif  /* disabled PT macros */
