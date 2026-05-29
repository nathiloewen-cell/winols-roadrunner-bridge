#pragma once
/*
 * device_spoof.h — Roadrunner → Batronix device identity spoof (S4).
 *
 * WinOLS / BSL100.dll look for a Batronix device when enumerating FTDI
 * hardware. This module intercepts FT_CreateDeviceInfoList,
 * FT_GetDeviceInfoList, and FT_OpenEx to replace the Roadrunner's
 * real identity (VID=0403, PID=B471, desc="DataLoader") with a
 * Batronix-compatible one.
 *
 * Known Batronix description strings (from Batronix.pep / WinOLS source):
 *   "Prog-Express 16"   — Batronix BX32 programmer (most common)
 *   "Prog-Express 32"
 *   "Batronix"
 * We default to "Prog-Express 16" which matches WinOLS 2.x expectations.
 */

#include "ftd2xx_proxy.h"
#include "logger.h"

/* Roadrunner real identity */
#define RR_VID         0x0403
#define RR_PID         0xB471
#define RR_DEVICE_ID   ((RR_VID << 16) | RR_PID)   /* 0x0403B471 */
#define RR_DESCRIPTION "DataLoader"

/* Batronix spoofed identity presented to WinOLS */
#define SPOOF_DESCRIPTION  "Prog-Express 16"
#define SPOOF_SERIAL       "BX000001"
#define SPOOF_DEVICE_ID    0x04036001   /* Standard FTDI FT232R ID */

/*
 * Returns TRUE if this device node represents the Roadrunner.
 * Matches on device ID (VID/PID combined) or description string.
 */
static inline BOOL is_roadrunner(const FT_DEVICE_LIST_INFO_NODE* node) {
    if (!node) return FALSE;
    if (node->ID == RR_DEVICE_ID) return TRUE;
    if (strstr(node->Description, RR_DESCRIPTION)) return TRUE;
    return FALSE;
}

/*
 * Patch a single FT_DEVICE_LIST_INFO_NODE so it looks like a Batronix
 * to WinOLS.  Called after the real FT_GetDeviceInfoList returns.
 */
static inline void spoof_node(FT_DEVICE_LIST_INFO_NODE* node) {
    if (!node) return;
    log_write("SPOOF: Roadrunner (ID=0x%08lX desc='%s') -> Batronix '%s'",
              (unsigned long)node->ID, node->Description, SPOOF_DESCRIPTION);
    node->ID = SPOOF_DEVICE_ID;
    strncpy_s(node->Description, sizeof(node->Description),
              SPOOF_DESCRIPTION, _TRUNCATE);
    strncpy_s(node->SerialNumber, sizeof(node->SerialNumber),
              SPOOF_SERIAL, _TRUNCATE);
}

/*
 * Check whether an FT_OpenEx call is targeting the spoofed Batronix
 * description — if so, redirect it to the real Roadrunner device.
 * Returns TRUE and modifies *arg_out if redirection is needed.
 */
static inline BOOL spoof_open_ex(PVOID arg, DWORD flags,
                                  const char** real_desc_out) {
    if (flags != FT_OPEN_BY_DESCRIPTION) return FALSE;
    const char* desc = (const char*)arg;
    if (!desc) return FALSE;
    /* If WinOLS is asking for the spoofed Batronix name, redirect */
    if (strcmp(desc, SPOOF_DESCRIPTION) == 0 ||
        strstr(desc, "Prog-Express") ||
        strstr(desc, "Batronix")) {
        log_write("SPOOF: FT_OpenEx('%s') -> redirected to Roadrunner '%s'",
                  desc, RR_DESCRIPTION);
        *real_desc_out = RR_DESCRIPTION;
        return TRUE;
    }
    return FALSE;
}
