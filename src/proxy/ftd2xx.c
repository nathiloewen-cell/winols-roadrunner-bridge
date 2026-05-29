/*
 * ftd2xx.c — WinOLS Roadrunner Bridge: ftd2xx.dll proxy
 *
 * Sprint 3: Passthrough skeleton with full call logging.
 * Every FT_xxx function is intercepted, logged, then forwarded to the
 * real System32\ftd2xx.dll.  No translation yet — that comes in S4-S7.
 *
 * Build (32-bit DLL, matches WinOLS):
 *   i686-w64-mingw32-gcc -shared -o ftd2xx.dll ftd2xx.c \
 *       -Wl,--out-implib,ftd2xx.lib -Wl,--kill-at \
 *       -DWINVER=0x0601 -D_WIN32_WINNT=0x0601
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "ftd2xx_proxy.h"
#include "logger.h"
#include "real_ftd2xx.h"

/* ── DLL entry point ────────────────────────────────────────────────── */
BOOL WINAPI DllMain(HINSTANCE hInst, DWORD reason, LPVOID reserved) {
    (void)hInst; (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hInst);
        log_init();
        if (!load_real_dll()) {
            log_write("FATAL: could not load System32\\ftd2xx.dll");
        } else {
            log_write("Proxy loaded. Real ftd2xx.dll at %p", (void*)g_real_dll);
        }
    } else if (reason == DLL_PROCESS_DETACH) {
        log_write("Proxy unloaded.");
        log_close();
        if (g_real_dll) FreeLibrary(g_real_dll);
    }
    return TRUE;
}

/* ── Passthrough macro ───────────────────────────────────────────────── */
/* Used for functions we intercept-and-log but do not yet translate */
#define PASSTHROUGH_1(fn, T1, a1) \
    __declspec(dllexport) FT_STATUS __stdcall fn(T1 a1) { \
        log_write(#fn "(" #a1 "=%p)", (void*)(uintptr_t)(a1)); \
        if (!real_##fn) return FT_OTHER_ERROR; \
        FT_STATUS r = real_##fn(a1); \
        log_write("  -> %lu", (unsigned long)r); \
        return r; \
    }

/* ── Device enumeration ──────────────────────────────────────────────── */
__declspec(dllexport)
FT_STATUS __stdcall FT_CreateDeviceInfoList(LPDWORD count) {
    if (!real_FT_CreateDeviceInfoList) return FT_OTHER_ERROR;
    FT_STATUS r = real_FT_CreateDeviceInfoList(count);
    log_write("FT_CreateDeviceInfoList -> %lu devices, status=%lu",
              count ? (unsigned long)*count : 0, (unsigned long)r);
    return r;
}

__declspec(dllexport)
FT_STATUS __stdcall FT_GetDeviceInfoList(FT_DEVICE_LIST_INFO_NODE* list,
                                          LPDWORD count) {
    if (!real_FT_GetDeviceInfoList) return FT_OTHER_ERROR;
    FT_STATUS r = real_FT_GetDeviceInfoList(list, count);
    if (r == FT_OK && list && count) {
        for (DWORD i = 0; i < *count; i++) {
            log_write("  Device[%lu]: ID=0x%08lX desc='%s' serial='%s' flags=0x%lX",
                      (unsigned long)i,
                      (unsigned long)list[i].ID,
                      list[i].Description,
                      list[i].SerialNumber,
                      (unsigned long)list[i].Flags);
        }
    }
    log_write("FT_GetDeviceInfoList -> %lu devices, status=%lu",
              count ? (unsigned long)*count : 0, (unsigned long)r);
    return r;
}

__declspec(dllexport)
FT_STATUS __stdcall FT_GetDeviceInfoDetail(DWORD idx, LPDWORD flags,
    LPDWORD type, LPDWORD id, LPDWORD locid,
    LPVOID serial, LPVOID desc, FT_HANDLE* handle) {
    if (!real_FT_GetDeviceInfoDetail) return FT_OTHER_ERROR;
    FT_STATUS r = real_FT_GetDeviceInfoDetail(
        idx, flags, type, id, locid, serial, desc, handle);
    log_write("FT_GetDeviceInfoDetail[%lu] id=0x%08lX desc='%s' -> %lu",
              (unsigned long)idx,
              id ? (unsigned long)*id : 0,
              desc ? (char*)desc : "",
              (unsigned long)r);
    return r;
}

/* ── Open / Close ────────────────────────────────────────────────────── */
__declspec(dllexport)
FT_STATUS __stdcall FT_Open(int device_number, FT_HANDLE* handle) {
    log_write("FT_Open(device=%d)", device_number);
    if (!real_FT_Open) return FT_OTHER_ERROR;
    FT_STATUS r = real_FT_Open(device_number, handle);
    log_write("  -> handle=%p status=%lu",
              handle ? *handle : NULL, (unsigned long)r);
    return r;
}

__declspec(dllexport)
FT_STATUS __stdcall FT_OpenEx(PVOID arg, DWORD flags, FT_HANDLE* handle) {
    if (flags == FT_OPEN_BY_DESCRIPTION)
        log_write("FT_OpenEx(desc='%s')", (char*)arg);
    else if (flags == FT_OPEN_BY_SERIAL_NUMBER)
        log_write("FT_OpenEx(serial='%s')", (char*)arg);
    else
        log_write("FT_OpenEx(arg=%p flags=0x%lX)", arg, (unsigned long)flags);
    if (!real_FT_OpenEx) return FT_OTHER_ERROR;
    FT_STATUS r = real_FT_OpenEx(arg, flags, handle);
    log_write("  -> handle=%p status=%lu",
              handle ? *handle : NULL, (unsigned long)r);
    return r;
}

__declspec(dllexport)
FT_STATUS __stdcall FT_Close(FT_HANDLE handle) {
    log_write("FT_Close(handle=%p)", handle);
    if (!real_FT_Close) return FT_OTHER_ERROR;
    return real_FT_Close(handle);
}

/* ── Read / Write  (most important for protocol analysis) ─────────────── */
__declspec(dllexport)
FT_STATUS __stdcall FT_Write(FT_HANDLE handle, LPVOID buf,
                              DWORD count, LPDWORD written) {
    log_write("FT_Write(handle=%p, %lu bytes)", handle, (unsigned long)count);
    log_hex("TX", buf, count);
    if (!real_FT_Write) return FT_OTHER_ERROR;
    FT_STATUS r = real_FT_Write(handle, buf, count, written);
    log_write("  -> written=%lu status=%lu",
              written ? (unsigned long)*written : 0, (unsigned long)r);
    return r;
}

__declspec(dllexport)
FT_STATUS __stdcall FT_Read(FT_HANDLE handle, LPVOID buf,
                             DWORD count, LPDWORD read_bytes) {
    if (!real_FT_Read) return FT_OTHER_ERROR;
    FT_STATUS r = real_FT_Read(handle, buf, count, read_bytes);
    log_write("FT_Read(handle=%p, req=%lu, got=%lu) -> %lu",
              handle, (unsigned long)count,
              read_bytes ? (unsigned long)*read_bytes : 0,
              (unsigned long)r);
    if (r == FT_OK && read_bytes && *read_bytes > 0)
        log_hex("RX", buf, *read_bytes);
    return r;
}

/* ── Configuration passthrough ───────────────────────────────────────── */
__declspec(dllexport)
FT_STATUS __stdcall FT_SetBaudRate(FT_HANDLE h, ULONG baud) {
    log_write("FT_SetBaudRate(handle=%p, baud=%lu)", h, (unsigned long)baud);
    if (!real_FT_SetBaudRate) return FT_OTHER_ERROR;
    return real_FT_SetBaudRate(h, baud);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_SetDataCharacteristics(FT_HANDLE h,
        UCHAR bits, UCHAR stop, UCHAR parity) {
    log_write("FT_SetDataCharacteristics(bits=%u stop=%u parity=%u)",
              bits, stop, parity);
    if (!real_FT_SetDataCharacteristics) return FT_OTHER_ERROR;
    return real_FT_SetDataCharacteristics(h, bits, stop, parity);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_SetTimeouts(FT_HANDLE h, ULONG rx, ULONG tx) {
    log_write("FT_SetTimeouts(rx=%lu tx=%lu)", (unsigned long)rx, (unsigned long)tx);
    if (!real_FT_SetTimeouts) return FT_OTHER_ERROR;
    return real_FT_SetTimeouts(h, rx, tx);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_GetQueueStatus(FT_HANDLE h, LPDWORD count) {
    if (!real_FT_GetQueueStatus) return FT_OTHER_ERROR;
    FT_STATUS r = real_FT_GetQueueStatus(h, count);
    if (count && *count > 0)
        log_write("FT_GetQueueStatus -> %lu bytes waiting", (unsigned long)*count);
    return r;
}

__declspec(dllexport)
FT_STATUS __stdcall FT_Purge(FT_HANDLE h, ULONG mask) {
    log_write("FT_Purge(mask=0x%lX)", (unsigned long)mask);
    if (!real_FT_Purge) return FT_OTHER_ERROR;
    return real_FT_Purge(h, mask);
}

/* ── Simple 1-arg passthroughs ───────────────────────────────────────── */
#define PT1(fn, T1, a1, fmt) \
__declspec(dllexport) FT_STATUS __stdcall fn(T1 a1) { \
    log_write(#fn "(" fmt ")", (a1)); \
    return real_##fn ? real_##fn(a1) : FT_OTHER_ERROR; \
}

PT1(FT_ResetDevice,  FT_HANDLE, h, "h=%p")
PT1(FT_CyclePort,    FT_HANDLE, h, "h=%p")
PT1(FT_StopInTask,   FT_HANDLE, h, "h=%p")
PT1(FT_RestartInTask,FT_HANDLE, h, "h=%p")
PT1(FT_ResetPort,    FT_HANDLE, h, "h=%p")
PT1(FT_EraseEE,      FT_HANDLE, h, "h=%p")

__declspec(dllexport)
FT_STATUS __stdcall FT_SetFlowControl(FT_HANDLE h, USHORT fc,
                                       UCHAR xon, UCHAR xoff) {
    log_write("FT_SetFlowControl(fc=0x%04X)", fc);
    if (!real_FT_SetFlowControl) return FT_OTHER_ERROR;
    return real_FT_SetFlowControl(h, fc, xon, xoff);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_SetDtr(FT_HANDLE h) {
    if (!real_FT_SetDtr) return FT_OTHER_ERROR;
    return real_FT_SetDtr(h);
}
__declspec(dllexport)
FT_STATUS __stdcall FT_ClrDtr(FT_HANDLE h) {
    if (!real_FT_ClrDtr) return FT_OTHER_ERROR;
    return real_FT_ClrDtr(h);
}
__declspec(dllexport)
FT_STATUS __stdcall FT_SetRts(FT_HANDLE h) {
    if (!real_FT_SetRts) return FT_OTHER_ERROR;
    return real_FT_SetRts(h);
}
__declspec(dllexport)
FT_STATUS __stdcall FT_ClrRts(FT_HANDLE h) {
    if (!real_FT_ClrRts) return FT_OTHER_ERROR;
    return real_FT_ClrRts(h);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_GetModemStatus(FT_HANDLE h, ULONG* status) {
    if (!real_FT_GetModemStatus) return FT_OTHER_ERROR;
    return real_FT_GetModemStatus(h, status);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_SetLatencyTimer(FT_HANDLE h, UCHAR lat) {
    log_write("FT_SetLatencyTimer(%u ms)", lat);
    if (!real_FT_SetLatencyTimer) return FT_OTHER_ERROR;
    return real_FT_SetLatencyTimer(h, lat);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_GetLatencyTimer(FT_HANDLE h, PUCHAR lat) {
    if (!real_FT_GetLatencyTimer) return FT_OTHER_ERROR;
    return real_FT_GetLatencyTimer(h, lat);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_SetBitMode(FT_HANDLE h, UCHAR mask, UCHAR mode) {
    log_write("FT_SetBitMode(mask=0x%02X mode=0x%02X)", mask, mode);
    if (!real_FT_SetBitMode) return FT_OTHER_ERROR;
    return real_FT_SetBitMode(h, mask, mode);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_GetBitMode(FT_HANDLE h, PUCHAR mode) {
    if (!real_FT_GetBitMode) return FT_OTHER_ERROR;
    return real_FT_GetBitMode(h, mode);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_SetVIDPID(DWORD vid, DWORD pid) {
    log_write("FT_SetVIDPID(vid=0x%04lX pid=0x%04lX)",
              (unsigned long)vid, (unsigned long)pid);
    if (!real_FT_SetVIDPID) return FT_OTHER_ERROR;
    return real_FT_SetVIDPID(vid, pid);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_GetVIDPID(LPDWORD vid, LPDWORD pid) {
    if (!real_FT_GetVIDPID) return FT_OTHER_ERROR;
    return real_FT_GetVIDPID(vid, pid);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_ListDevices(PVOID a, PVOID b, DWORD flags) {
    log_write("FT_ListDevices(flags=0x%lX)", (unsigned long)flags);
    if (!real_FT_ListDevices) return FT_OTHER_ERROR;
    return real_FT_ListDevices(a, b, flags);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_GetDeviceInfo(FT_HANDLE h, FT_DEVICE* dev,
    LPDWORD id, PCHAR serial, PCHAR desc, LPVOID dummy) {
    if (!real_FT_GetDeviceInfo) return FT_OTHER_ERROR;
    FT_STATUS r = real_FT_GetDeviceInfo(h, dev, id, serial, desc, dummy);
    log_write("FT_GetDeviceInfo -> id=0x%08lX desc='%s'",
              id ? (unsigned long)*id : 0, desc ? desc : "");
    return r;
}

__declspec(dllexport)
FT_STATUS __stdcall FT_GetDriverVersion(FT_HANDLE h, LPDWORD ver) {
    if (!real_FT_GetDriverVersion) return FT_OTHER_ERROR;
    return real_FT_GetDriverVersion(h, ver);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_GetLibraryVersion(LPDWORD ver) {
    if (!real_FT_GetLibraryVersion) return FT_OTHER_ERROR;
    FT_STATUS r = real_FT_GetLibraryVersion(ver);
    if (r == FT_OK && ver)
        log_write("FT_GetLibraryVersion -> 0x%08lX", (unsigned long)*ver);
    return r;
}

__declspec(dllexport)
FT_STATUS __stdcall FT_SetUSBParameters(FT_HANDLE h, ULONG in, ULONG out) {
    log_write("FT_SetUSBParameters(in=%lu out=%lu)",
              (unsigned long)in, (unsigned long)out);
    if (!real_FT_SetUSBParameters) return FT_OTHER_ERROR;
    return real_FT_SetUSBParameters(h, in, out);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_SetChars(FT_HANDLE h, UCHAR ec, UCHAR ee,
                                  UCHAR sc, UCHAR se) {
    if (!real_FT_SetChars) return FT_OTHER_ERROR;
    return real_FT_SetChars(h, ec, ee, sc, se);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_SetBreakOn(FT_HANDLE h) {
    if (!real_FT_SetBreakOn) return FT_OTHER_ERROR;
    return real_FT_SetBreakOn(h);
}
__declspec(dllexport)
FT_STATUS __stdcall FT_SetBreakOff(FT_HANDLE h) {
    if (!real_FT_SetBreakOff) return FT_OTHER_ERROR;
    return real_FT_SetBreakOff(h);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_Reload(WORD vid, WORD pid) {
    log_write("FT_Reload(vid=0x%04X pid=0x%04X)", vid, pid);
    if (!real_FT_Reload) return FT_OTHER_ERROR;
    return real_FT_Reload(vid, pid);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_GetComPortNumber(FT_HANDLE h, LPLONG port) {
    if (!real_FT_GetComPortNumber) return FT_OTHER_ERROR;
    FT_STATUS r = real_FT_GetComPortNumber(h, port);
    if (r == FT_OK && port)
        log_write("FT_GetComPortNumber -> COM%ld", *port);
    return r;
}

__declspec(dllexport)
FT_STATUS __stdcall FT_RescanDevices(void) {
    log_write("FT_RescanDevices()");
    if (!real_FT_RescanDevices) return FT_OTHER_ERROR;
    return real_FT_RescanDevices();
}

__declspec(dllexport)
FT_STATUS __stdcall FT_SetResetPipeRetryCount(FT_HANDLE h, DWORD count) {
    if (!real_FT_SetResetPipeRetryCount) return FT_OTHER_ERROR;
    return real_FT_SetResetPipeRetryCount(h, count);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_SetEventNotification(FT_HANDLE h,
                                              DWORD mask, PVOID param) {
    log_write("FT_SetEventNotification(mask=0x%lX)", (unsigned long)mask);
    if (!real_FT_SetEventNotification) return FT_OTHER_ERROR;
    return real_FT_SetEventNotification(h, mask, param);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_GetStatus(FT_HANDLE h,
    DWORD* rx, DWORD* tx, DWORD* ev) {
    if (!real_FT_GetStatus) return FT_OTHER_ERROR;
    return real_FT_GetStatus(h, rx, tx, ev);
}

/* ── EEPROM passthrough ───────────────────────────────────────────────── */
__declspec(dllexport)
FT_STATUS __stdcall FT_EE_Read(FT_HANDLE h, PFT_PROGRAM_DATA d) {
    if (!real_FT_EE_Read) return FT_OTHER_ERROR;
    return real_FT_EE_Read(h, d);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_EE_ReadEx(FT_HANDLE h, PFT_PROGRAM_DATA d,
    char* man, char* manid, char* desc, char* serial) {
    if (!real_FT_EE_ReadEx) return FT_OTHER_ERROR;
    return real_FT_EE_ReadEx(h, d, man, manid, desc, serial);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_EE_Program(FT_HANDLE h, PFT_PROGRAM_DATA d) {
    log_write("FT_EE_Program() called");
    if (!real_FT_EE_Program) return FT_OTHER_ERROR;
    return real_FT_EE_Program(h, d);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_ReadEE(FT_HANDLE h, DWORD offset, LPWORD val) {
    if (!real_FT_ReadEE) return FT_OTHER_ERROR;
    return real_FT_ReadEE(h, offset, val);
}

__declspec(dllexport)
FT_STATUS __stdcall FT_WriteEE(FT_HANDLE h, DWORD offset, WORD val) {
    log_write("FT_WriteEE(offset=0x%lX val=0x%04X)",
              (unsigned long)offset, val);
    if (!real_FT_WriteEE) return FT_OTHER_ERROR;
    return real_FT_WriteEE(h, offset, val);
}
