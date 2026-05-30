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
    fopen_s(&g_log, path, "a");
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

/* ── WDU_Init — intercept USB device registration ────────────────────── */
__declspec(dllexport)
DWORD __cdecl WDU_Init(WDU_DRIVER_HANDLE* phDriver,
                        WDU_MATCH_TABLE* pMatchTables,
                        DWORD dwNumMatchTables,
                        void* pEventTable,
                        const char* sLicense,
                        DWORD dwOptions) {
    wlog("WDU_Init called with %lu match table(s):", (unsigned long)dwNumMatchTables);
    if (pMatchTables) {
        for (DWORD i = 0; i < dwNumMatchTables; i++) {
            wlog("  [%lu] VID=0x%04X PID=0x%04X DevClass=0x%02X IfClass=0x%02X",
                 (unsigned long)i,
                 pMatchTables[i].wVendorId,
                 pMatchTables[i].wProductId,
                 pMatchTables[i].bDeviceClass,
                 pMatchTables[i].bInterfaceClass);
        }
    }
    if (sLicense) wlog("  License: %.32s", sLicense);

    typedef DWORD (__cdecl *PFN)(WDU_DRIVER_HANDLE*, WDU_MATCH_TABLE*,
                                   DWORD, void*, const char*, DWORD);
    PFN fn = (PFN)get_real("WDU_Init");
    if (!fn) { wlog("  WDU_Init: real fn not found"); return 0xFFFFFFFF; }
    DWORD r = fn(phDriver, pMatchTables, dwNumMatchTables,
                 pEventTable, sLicense, dwOptions);
    wlog("  WDU_Init -> 0x%08lX  handle=%p", (unsigned long)r,
         phDriver ? *phDriver : NULL);
    return r;
}

__declspec(dllexport)
DWORD __cdecl WDU_Uninit(WDU_DRIVER_HANDLE hDriver) {
    wlog("WDU_Uninit(handle=%p)", hDriver);
    typedef DWORD (__cdecl *PFN)(WDU_DRIVER_HANDLE);
    PFN fn = (PFN)get_real("WDU_Uninit");
    return fn ? fn(hDriver) : 0;
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

    typedef DWORD (__cdecl *PFN)(WDU_DEVICE_HANDLE, DWORD, DWORD, DWORD,
                                   void*, DWORD, DWORD*, BYTE*, DWORD);
    PFN fn = (PFN)get_real("WDU_Transfer");
    if (!fn) return 0xFFFFFFFF;
    DWORD r = fn(hDevice, dwPipeNum, fRead, dwOptions, pBuffer, dwBytes,
                 pdwBytesTransferred, pSetupPacket, dwTimeout);

    if (fRead && pBuffer && pdwBytesTransferred && *pdwBytesTransferred > 0)
        log_hex("WDU_Transfer RX", pBuffer, *pdwBytesTransferred);
    else
        wlog("WDU_Transfer(pipe=%lu fRead=%lu bytes=%lu) -> 0x%lX",
             (unsigned long)dwPipeNum, (unsigned long)fRead,
             (unsigned long)dwBytes, (unsigned long)r);
    return r;
}

__declspec(dllexport)
DWORD __cdecl WDU_TransferBulk(WDU_DEVICE_HANDLE hDevice,
                                 DWORD dwPipeNum, void* pBuffer,
                                 DWORD* pdwBytes, DWORD dwOptions,
                                 DWORD dwTimeout) {
    DWORD sz = pdwBytes ? *pdwBytes : 0;
    if (pBuffer && sz > 0)
        log_hex("WDU_TransferBulk TX", pBuffer, sz);

    typedef DWORD (__cdecl *PFN)(WDU_DEVICE_HANDLE,DWORD,void*,DWORD*,DWORD,DWORD);
    PFN fn = (PFN)get_real("WDU_TransferBulk");
    if (!fn) return 0xFFFFFFFF;
    DWORD r = fn(hDevice, dwPipeNum, pBuffer, pdwBytes, dwOptions, dwTimeout);

    if (pBuffer && pdwBytes && *pdwBytes > 0)
        log_hex("WDU_TransferBulk RX", pBuffer, *pdwBytes);
    wlog("  WDU_TransferBulk -> 0x%lX", (unsigned long)r);
    return r;
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
    wlog("WDC_DriverOpen called");
    typedef DWORD (__cdecl *PFN)(void*, const char*);
    PFN fn = (PFN)get_real("WDC_DriverOpen");
    DWORD r = fn ? fn(pCfg, pcLic) : 0xFFFFFFFF;
    wlog("  WDC_DriverOpen -> 0x%lX", (unsigned long)r);
    return r;
}

__declspec(dllexport) DWORD __cdecl WDC_DriverClose(void) {
    typedef DWORD (__cdecl *PFN)(void);
    PFN fn = (PFN)get_real("WDC_DriverClose");
    return fn ? fn() : 0;
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
