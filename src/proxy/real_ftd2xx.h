#pragma once
/*
 * real_ftd2xx.h — Dynamic loader for the REAL ftd2xx.dll (System32).
 *
 * Our proxy DLL sits in the WinOLS app directory and intercepts all
 * FT_xxx calls. For passthrough functions (and for the transport layer
 * of the bridge itself), we need the real 64-bit ftd2xx.dll from System32.
 *
 * NOTE: WinOLS ships a 32-bit ftd2xx.dll — we are the 32-bit proxy.
 *       The real library is also loaded as 32-bit from System32.
 */

#include <windows.h>
#include "ftd2xx_proxy.h"

/* Function pointer typedefs for every D2XX export we use */
typedef FT_STATUS (__stdcall *PFN_FT_CreateDeviceInfoList)(LPDWORD);
typedef FT_STATUS (__stdcall *PFN_FT_GetDeviceInfoList)(FT_DEVICE_LIST_INFO_NODE*, LPDWORD);
typedef FT_STATUS (__stdcall *PFN_FT_GetDeviceInfoDetail)(DWORD,LPDWORD,LPDWORD,LPDWORD,LPDWORD,LPVOID,LPVOID,FT_HANDLE*);
typedef FT_STATUS (__stdcall *PFN_FT_Open)(int, FT_HANDLE*);
typedef FT_STATUS (__stdcall *PFN_FT_OpenEx)(PVOID, DWORD, FT_HANDLE*);
typedef FT_STATUS (__stdcall *PFN_FT_Close)(FT_HANDLE);
typedef FT_STATUS (__stdcall *PFN_FT_Read)(FT_HANDLE, LPVOID, DWORD, LPDWORD);
typedef FT_STATUS (__stdcall *PFN_FT_Write)(FT_HANDLE, LPVOID, DWORD, LPDWORD);
typedef FT_STATUS (__stdcall *PFN_FT_SetBaudRate)(FT_HANDLE, ULONG);
typedef FT_STATUS (__stdcall *PFN_FT_SetDataCharacteristics)(FT_HANDLE, UCHAR, UCHAR, UCHAR);
typedef FT_STATUS (__stdcall *PFN_FT_SetTimeouts)(FT_HANDLE, ULONG, ULONG);
typedef FT_STATUS (__stdcall *PFN_FT_GetQueueStatus)(FT_HANDLE, LPDWORD);
typedef FT_STATUS (__stdcall *PFN_FT_Purge)(FT_HANDLE, ULONG);
typedef FT_STATUS (__stdcall *PFN_FT_SetFlowControl)(FT_HANDLE, USHORT, UCHAR, UCHAR);
typedef FT_STATUS (__stdcall *PFN_FT_SetDtr)(FT_HANDLE);
typedef FT_STATUS (__stdcall *PFN_FT_ClrDtr)(FT_HANDLE);
typedef FT_STATUS (__stdcall *PFN_FT_SetRts)(FT_HANDLE);
typedef FT_STATUS (__stdcall *PFN_FT_ClrRts)(FT_HANDLE);
typedef FT_STATUS (__stdcall *PFN_FT_GetModemStatus)(FT_HANDLE, ULONG*);
typedef FT_STATUS (__stdcall *PFN_FT_SetChars)(FT_HANDLE, UCHAR, UCHAR, UCHAR, UCHAR);
typedef FT_STATUS (__stdcall *PFN_FT_SetBreakOn)(FT_HANDLE);
typedef FT_STATUS (__stdcall *PFN_FT_SetBreakOff)(FT_HANDLE);
typedef FT_STATUS (__stdcall *PFN_FT_ResetDevice)(FT_HANDLE);
typedef FT_STATUS (__stdcall *PFN_FT_SetUSBParameters)(FT_HANDLE, ULONG, ULONG);
typedef FT_STATUS (__stdcall *PFN_FT_GetDeviceInfo)(FT_HANDLE, FT_DEVICE*, LPDWORD, PCHAR, PCHAR, LPVOID);
typedef FT_STATUS (__stdcall *PFN_FT_GetDriverVersion)(FT_HANDLE, LPDWORD);
typedef FT_STATUS (__stdcall *PFN_FT_GetLibraryVersion)(LPDWORD);
typedef FT_STATUS (__stdcall *PFN_FT_SetLatencyTimer)(FT_HANDLE, UCHAR);
typedef FT_STATUS (__stdcall *PFN_FT_GetLatencyTimer)(FT_HANDLE, PUCHAR);
typedef FT_STATUS (__stdcall *PFN_FT_SetBitMode)(FT_HANDLE, UCHAR, UCHAR);
typedef FT_STATUS (__stdcall *PFN_FT_GetBitMode)(FT_HANDLE, PUCHAR);
typedef FT_STATUS (__stdcall *PFN_FT_SetVIDPID)(DWORD, DWORD);
typedef FT_STATUS (__stdcall *PFN_FT_GetVIDPID)(LPDWORD, LPDWORD);
typedef FT_STATUS (__stdcall *PFN_FT_ListDevices)(PVOID, PVOID, DWORD);
typedef FT_STATUS (__stdcall *PFN_FT_Reload)(WORD, WORD);
typedef FT_STATUS (__stdcall *PFN_FT_GetComPortNumber)(FT_HANDLE, LPLONG);
typedef FT_STATUS (__stdcall *PFN_FT_EE_Read)(FT_HANDLE, PFT_PROGRAM_DATA);
typedef FT_STATUS (__stdcall *PFN_FT_EE_ReadEx)(FT_HANDLE, PFT_PROGRAM_DATA, char*, char*, char*, char*);
typedef FT_STATUS (__stdcall *PFN_FT_EE_Program)(FT_HANDLE, PFT_PROGRAM_DATA);
typedef FT_STATUS (__stdcall *PFN_FT_EraseEE)(FT_HANDLE);
typedef FT_STATUS (__stdcall *PFN_FT_ReadEE)(FT_HANDLE, DWORD, LPWORD);
typedef FT_STATUS (__stdcall *PFN_FT_WriteEE)(FT_HANDLE, DWORD, WORD);
typedef FT_STATUS (__stdcall *PFN_FT_CyclePort)(FT_HANDLE);
typedef FT_STATUS (__stdcall *PFN_FT_RescanDevices)(void);
typedef FT_STATUS (__stdcall *PFN_FT_StopInTask)(FT_HANDLE);
typedef FT_STATUS (__stdcall *PFN_FT_RestartInTask)(FT_HANDLE);
typedef FT_STATUS (__stdcall *PFN_FT_SetResetPipeRetryCount)(FT_HANDLE, DWORD);
typedef FT_STATUS (__stdcall *PFN_FT_ResetPort)(FT_HANDLE);
typedef FT_STATUS (__stdcall *PFN_FT_SetEventNotification)(FT_HANDLE, DWORD, PVOID);
typedef FT_STATUS (__stdcall *PFN_FT_GetStatus)(FT_HANDLE, DWORD*, DWORD*, DWORD*);

/* ── Real DLL handle and function pointers ───────────────────────────── */
static HMODULE g_real_dll = NULL;

#define DECL_REAL(name) static PFN_##name real_##name = NULL;
DECL_REAL(FT_CreateDeviceInfoList) DECL_REAL(FT_GetDeviceInfoList)
DECL_REAL(FT_GetDeviceInfoDetail)  DECL_REAL(FT_Open)
DECL_REAL(FT_OpenEx)               DECL_REAL(FT_Close)
DECL_REAL(FT_Read)                 DECL_REAL(FT_Write)
DECL_REAL(FT_SetBaudRate)          DECL_REAL(FT_SetDataCharacteristics)
DECL_REAL(FT_SetTimeouts)          DECL_REAL(FT_GetQueueStatus)
DECL_REAL(FT_Purge)                DECL_REAL(FT_SetFlowControl)
DECL_REAL(FT_SetDtr)               DECL_REAL(FT_ClrDtr)
DECL_REAL(FT_SetRts)               DECL_REAL(FT_ClrRts)
DECL_REAL(FT_GetModemStatus)       DECL_REAL(FT_SetChars)
DECL_REAL(FT_SetBreakOn)           DECL_REAL(FT_SetBreakOff)
DECL_REAL(FT_ResetDevice)          DECL_REAL(FT_SetUSBParameters)
DECL_REAL(FT_GetDeviceInfo)        DECL_REAL(FT_GetDriverVersion)
DECL_REAL(FT_GetLibraryVersion)    DECL_REAL(FT_SetLatencyTimer)
DECL_REAL(FT_GetLatencyTimer)      DECL_REAL(FT_SetBitMode)
DECL_REAL(FT_GetBitMode)           DECL_REAL(FT_SetVIDPID)
DECL_REAL(FT_GetVIDPID)            DECL_REAL(FT_ListDevices)
DECL_REAL(FT_Reload)               DECL_REAL(FT_GetComPortNumber)
DECL_REAL(FT_EE_Read)              DECL_REAL(FT_EE_ReadEx)
DECL_REAL(FT_EE_Program)           DECL_REAL(FT_EraseEE)
DECL_REAL(FT_ReadEE)               DECL_REAL(FT_WriteEE)
DECL_REAL(FT_CyclePort)            DECL_REAL(FT_RescanDevices)
DECL_REAL(FT_StopInTask)           DECL_REAL(FT_RestartInTask)
DECL_REAL(FT_SetResetPipeRetryCount) DECL_REAL(FT_ResetPort)
DECL_REAL(FT_SetEventNotification) DECL_REAL(FT_GetStatus)

#define LOAD_REAL(name) \
    real_##name = (PFN_##name)GetProcAddress(g_real_dll, #name);

static inline BOOL load_real_dll(void) {
    /* Load from System32 explicitly to avoid recursion */
    char sys32[MAX_PATH];
    GetSystemDirectoryA(sys32, MAX_PATH);
    strcat_s(sys32, MAX_PATH, "\\ftd2xx.dll");
    g_real_dll = LoadLibraryA(sys32);
    if (!g_real_dll) return FALSE;

    LOAD_REAL(FT_CreateDeviceInfoList) LOAD_REAL(FT_GetDeviceInfoList)
    LOAD_REAL(FT_GetDeviceInfoDetail)  LOAD_REAL(FT_Open)
    LOAD_REAL(FT_OpenEx)               LOAD_REAL(FT_Close)
    LOAD_REAL(FT_Read)                 LOAD_REAL(FT_Write)
    LOAD_REAL(FT_SetBaudRate)          LOAD_REAL(FT_SetDataCharacteristics)
    LOAD_REAL(FT_SetTimeouts)          LOAD_REAL(FT_GetQueueStatus)
    LOAD_REAL(FT_Purge)                LOAD_REAL(FT_SetFlowControl)
    LOAD_REAL(FT_SetDtr)               LOAD_REAL(FT_ClrDtr)
    LOAD_REAL(FT_SetRts)               LOAD_REAL(FT_ClrRts)
    LOAD_REAL(FT_GetModemStatus)       LOAD_REAL(FT_SetChars)
    LOAD_REAL(FT_SetBreakOn)           LOAD_REAL(FT_SetBreakOff)
    LOAD_REAL(FT_ResetDevice)          LOAD_REAL(FT_SetUSBParameters)
    LOAD_REAL(FT_GetDeviceInfo)        LOAD_REAL(FT_GetDriverVersion)
    LOAD_REAL(FT_GetLibraryVersion)    LOAD_REAL(FT_SetLatencyTimer)
    LOAD_REAL(FT_GetLatencyTimer)      LOAD_REAL(FT_SetBitMode)
    LOAD_REAL(FT_GetBitMode)           LOAD_REAL(FT_SetVIDPID)
    LOAD_REAL(FT_GetVIDPID)            LOAD_REAL(FT_ListDevices)
    LOAD_REAL(FT_Reload)               LOAD_REAL(FT_GetComPortNumber)
    LOAD_REAL(FT_EE_Read)              LOAD_REAL(FT_EE_ReadEx)
    LOAD_REAL(FT_EE_Program)           LOAD_REAL(FT_EraseEE)
    LOAD_REAL(FT_ReadEE)               LOAD_REAL(FT_WriteEE)
    LOAD_REAL(FT_CyclePort)            LOAD_REAL(FT_RescanDevices)
    LOAD_REAL(FT_StopInTask)           LOAD_REAL(FT_RestartInTask)
    LOAD_REAL(FT_SetResetPipeRetryCount) LOAD_REAL(FT_ResetPort)
    LOAD_REAL(FT_SetEventNotification) LOAD_REAL(FT_GetStatus)
    return TRUE;
}
