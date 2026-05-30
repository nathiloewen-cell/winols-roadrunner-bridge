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

/* ── DLL Entry ───────────────────────────────────────────────────────── */
BOOL WINAPI DllMain(HINSTANCE hInst, DWORD reason, LPVOID res) {
    (void)hInst; (void)res;
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hInst);
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

/* WinOLS dereferences device handles as pointers to internal structures.
   We allocate real memory so reads return 0 instead of crashing.
   Size 256 bytes covers any internal WinDriver device struct WinOLS reads. */
static DWORD g_fake_driver_data[64] = {0};
static DWORD g_fake_device_data[64] = {0};

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

    /* Call WinOLS device-attach callback so it thinks OLS300 is connected.
       This makes 'Load/Disconnect' active and triggers WDU_Transfer calls. */
    if (pEventTable) {
        WDU_EVENT_TABLE* tbl = (WDU_EVENT_TABLE*)pEventTable;
        if (tbl->pfDeviceAttach) {
            /* Pass NULL for device info first — if WinOLS only needs the
               handle, this avoids struct layout mismatches entirely.      */
            wlog("  Calling pfDeviceAttach(handle=%p, device=NULL, userData=%p)",
                 FAKE_DEVICE_HANDLE, tbl->pUserData);
            BOOL ok = tbl->pfDeviceAttach(FAKE_DEVICE_HANDLE,
                                          &g_fake_device,
                                          tbl->pUserData);
            wlog("  pfDeviceAttach returned %d", ok);
        } else {
            wlog("  WARNING: pfDeviceAttach is NULL");
        }
    }
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
__declspec(dllexport)
DWORD __cdecl WDU_StreamOpen(WDU_DEVICE_HANDLE hDevice, DWORD dwPipeNum,
                              DWORD dwBufferSize, DWORD dwRxSize,
                              BOOL fBlocking, DWORD dwOptions,
                              DWORD dwTimeout, void** phStream) {
    wlog("WDU_StreamOpen(pipe=%lu bufsize=%lu)", (unsigned long)dwPipeNum,
         (unsigned long)dwBufferSize);
    typedef DWORD (__cdecl *PFN)(WDU_DEVICE_HANDLE,DWORD,DWORD,DWORD,BOOL,DWORD,DWORD,void**);
    PFN fn = (PFN)get_real("WDU_StreamOpen");
    if (!fn) return 0xFFFFFFFF;
    DWORD r = fn(hDevice, dwPipeNum, dwBufferSize, dwRxSize, fBlocking,
                 dwOptions, dwTimeout, phStream);
    wlog("  WDU_StreamOpen -> 0x%lX stream=%p", (unsigned long)r,
         phStream ? *phStream : NULL);
    return r;
}

__declspec(dllexport)
DWORD __cdecl WDU_StreamRead(void* hStream, void* pBuffer, DWORD bytes,
                              DWORD* pdwBytesRead) {
    typedef DWORD (__cdecl *PFN)(void*, void*, DWORD, DWORD*);
    PFN fn = (PFN)get_real("WDU_StreamRead");
    if (!fn) return 0xFFFFFFFF;
    DWORD r = fn(hStream, pBuffer, bytes, pdwBytesRead);
    if (pBuffer && pdwBytesRead && *pdwBytesRead > 0)
        log_hex("WDU_StreamRead RX", pBuffer, *pdwBytesRead);
    return r;
}

__declspec(dllexport)
DWORD __cdecl WDU_StreamWrite(void* hStream, const void* pBuffer,
                               DWORD bytes, DWORD* pdwBytesWritten) {
    if (pBuffer && bytes > 0)
        log_hex("WDU_StreamWrite TX", pBuffer, bytes);
    typedef DWORD (__cdecl *PFN)(void*, const void*, DWORD, DWORD*);
    PFN fn = (PFN)get_real("WDU_StreamWrite");
    if (!fn) return 0xFFFFFFFF;
    return fn(hStream, pBuffer, bytes, pdwBytesWritten);
}

__declspec(dllexport)
DWORD __cdecl WDU_StreamClose(void* hStream) {
    wlog("WDU_StreamClose(%p)", hStream);
    typedef DWORD (__cdecl *PFN)(void*);
    PFN fn = (PFN)get_real("WDU_StreamClose");
    return fn ? fn(hStream) : 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_StreamStart(void* hStream) {
    typedef DWORD (__cdecl *PFN)(void*);
    PFN fn = (PFN)get_real("WDU_StreamStart");
    return fn ? fn(hStream) : 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_StreamStop(void* hStream) {
    typedef DWORD (__cdecl *PFN)(void*);
    PFN fn = (PFN)get_real("WDU_StreamStop");
    return fn ? fn(hStream) : 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_StreamFlush(void* hStream) {
    typedef DWORD (__cdecl *PFN)(void*);
    PFN fn = (PFN)get_real("WDU_StreamFlush");
    return fn ? fn(hStream) : 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_StreamGetStatus(void* hStream, BOOL* pfIsRunning,
                                   DWORD* pdwLastError, DWORD* pdwBytesInBuf) {
    typedef DWORD (__cdecl *PFN)(void*, BOOL*, DWORD*, DWORD*);
    PFN fn = (PFN)get_real("WDU_StreamGetStatus");
    return fn ? fn(hStream, pfIsRunning, pdwLastError, pdwBytesInBuf) : 0;
}

/* ── Device info functions ───────────────────────────────────────────── */
__declspec(dllexport)
DWORD __cdecl WDU_GetDeviceInfo(WDU_DEVICE_HANDLE hDevice, void** ppDeviceInfo) {
    typedef DWORD (__cdecl *PFN)(WDU_DEVICE_HANDLE, void**);
    PFN fn = (PFN)get_real("WDU_GetDeviceInfo");
    DWORD r = fn ? fn(hDevice, ppDeviceInfo) : 0xFFFFFFFF;
    wlog("WDU_GetDeviceInfo(handle=%p) -> 0x%lX info=%p",
         hDevice, (unsigned long)r, ppDeviceInfo ? *ppDeviceInfo : NULL);
    return r;
}

__declspec(dllexport)
void __cdecl WDU_PutDeviceInfo(void* pDeviceInfo) {
    typedef void (__cdecl *PFN)(void*);
    PFN fn = (PFN)get_real("WDU_PutDeviceInfo");
    if (fn) fn(pDeviceInfo);
}

__declspec(dllexport)
DWORD __cdecl WDU_GetDeviceAddr(WDU_DEVICE_HANDLE hDevice,
                                 DWORD* pdwBusNum, DWORD* pdwDevAddr) {
    typedef DWORD (__cdecl *PFN)(WDU_DEVICE_HANDLE, DWORD*, DWORD*);
    PFN fn = (PFN)get_real("WDU_GetDeviceAddr");
    DWORD r = fn ? fn(hDevice, pdwBusNum, pdwDevAddr) : 0xFFFFFFFF;
    if (r == 0)
        wlog("WDU_GetDeviceAddr -> bus=%lu addr=%lu",
             pdwBusNum ? (unsigned long)*pdwBusNum : 0,
             pdwDevAddr ? (unsigned long)*pdwDevAddr : 0);
    return r;
}

__declspec(dllexport)
DWORD __cdecl WDU_ResetDevice(WDU_DEVICE_HANDLE hDevice, DWORD dwOptions) {
    wlog("WDU_ResetDevice(%p options=0x%lX)", hDevice, (unsigned long)dwOptions);
    typedef DWORD (__cdecl *PFN)(WDU_DEVICE_HANDLE, DWORD);
    PFN fn = (PFN)get_real("WDU_ResetDevice");
    return fn ? fn(hDevice, dwOptions) : 0xFFFFFFFF;
}

__declspec(dllexport)
DWORD __cdecl WDU_ResetPipe(WDU_DEVICE_HANDLE hDevice, DWORD dwPipeNum) {
    typedef DWORD (__cdecl *PFN)(WDU_DEVICE_HANDLE, DWORD);
    PFN fn = (PFN)get_real("WDU_ResetPipe");
    return fn ? fn(hDevice, dwPipeNum) : 0xFFFFFFFF;
}

__declspec(dllexport)
DWORD __cdecl WDU_SetInterface(WDU_DEVICE_HANDLE hDevice,
                                DWORD dwInterfaceNum, DWORD dwAlternateSetting) {
    typedef DWORD (__cdecl *PFN)(WDU_DEVICE_HANDLE, DWORD, DWORD);
    PFN fn = (PFN)get_real("WDU_SetInterface");
    return fn ? fn(hDevice, dwInterfaceNum, dwAlternateSetting) : 0xFFFFFFFF;
}

__declspec(dllexport)
DWORD __cdecl WDU_HaltTransfer(WDU_DEVICE_HANDLE hDevice, DWORD dwPipeNum) {
    typedef DWORD (__cdecl *PFN)(WDU_DEVICE_HANDLE, DWORD);
    PFN fn = (PFN)get_real("WDU_HaltTransfer");
    return fn ? fn(hDevice, dwPipeNum) : 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_SelectiveSuspend(WDU_DEVICE_HANDLE hDevice, DWORD dwOptions) {
    typedef DWORD (__cdecl *PFN)(WDU_DEVICE_HANDLE, DWORD);
    PFN fn = (PFN)get_real("WDU_SelectiveSuspend");
    return fn ? fn(hDevice, dwOptions) : 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_Wakeup(WDU_DEVICE_HANDLE hDevice, DWORD dwOptions) {
    typedef DWORD (__cdecl *PFN)(WDU_DEVICE_HANDLE, DWORD);
    PFN fn = (PFN)get_real("WDU_Wakeup");
    return fn ? fn(hDevice, dwOptions) : 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_GetLangIDs(WDU_DEVICE_HANDLE hDevice, BYTE* pbNumSupportedLangIDs,
                              WORD* pLangIDs, DWORD dwLangIDsSize) {
    typedef DWORD (__cdecl *PFN)(WDU_DEVICE_HANDLE,BYTE*,WORD*,DWORD);
    PFN fn = (PFN)get_real("WDU_GetLangIDs");
    return fn ? fn(hDevice, pbNumSupportedLangIDs, pLangIDs, dwLangIDsSize) : 0;
}

__declspec(dllexport)
DWORD __cdecl WDU_GetStringDesc(WDU_DEVICE_HANDLE hDevice, BYTE bStrIndex,
                                 void* pbBuf, DWORD dwBufSize, WORD wLangID,
                                 DWORD* pdwDescSize) {
    typedef DWORD (__cdecl *PFN)(WDU_DEVICE_HANDLE,BYTE,void*,DWORD,WORD,DWORD*);
    PFN fn = (PFN)get_real("WDU_GetStringDesc");
    return fn ? fn(hDevice, bStrIndex, pbBuf, dwBufSize, wLangID, pdwDescSize) : 0;
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
