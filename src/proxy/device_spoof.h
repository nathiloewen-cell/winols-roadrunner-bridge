#pragma once
/*
 * device_spoof.h — Roadrunner → OLS300 device identity spoof (S4, corrected).
 *
 * CORRECTION: Batronix is an EEPROM programmer, NOT a chip simulator.
 * WinOLS uses the OLS300 as its native chip simulator (EPROM emulator).
 * The Roadrunner (Moates) is the equivalent of the OLS300.
 *
 * WinOLS identifies the OLS300:
 *  - Via standard FTDI USB (VID=0403, PID=6001)
 *  - Matched by SERIAL NUMBER entered in Hardware → Simulator → Properties
 *  - Device description is generic ("FT232R USB UART" or similar)
 *
 * Bridge strategy:
 *  1. Register Roadrunner's custom PID (B471) with D2XX so WinOLS sees it
 *  2. WinOLS enumerates FTDI devices → finds Roadrunner
 *  3. User enters Roadrunner's serial number in Simulator Properties
 *  4. WinOLS opens by serial → proxy intercepts → bridge translates
 *     OLS300 protocol commands to MoatesWare commands
 *
 * OLS300 protocol: discovered empirically via logging proxy (S3).
 * Run WinOLS with proxy installed and check %TEMP%\winols_bridge.log.
 */

#include "ftd2xx_proxy.h"
#include "logger.h"

/* Roadrunner real identity */
#define RR_VID         0x0403
#define RR_PID         0xB471
#define RR_DEVICE_ID   ((RR_VID << 16) | RR_PID)   /* 0x0403B471 */
#define RR_DESCRIPTION "DataLoader"

/*
 * OLS300 identity — WinOLS's native simulator (what we spoof TO).
 * PID 6001 = standard FTDI FT232R (OLS300 uses standard FTDI chip).
 * Serial number is user-configurable in WinOLS Simulator Properties —
 * set it to the Roadrunner's actual FTDI serial number.
 */
#define SPOOF_DESCRIPTION  "FT232R USB UART"   /* OLS300 generic FTDI desc  */
#define SPOOF_SERIAL       ""                   /* Keep real serial — user   */
                                                /* must enter it in WinOLS   */
#define SPOOF_DEVICE_ID    0x04036001           /* OLS300: standard FT232R   */

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
    /*
     * WinOLS opens the OLS300 by SERIAL NUMBER (FT_OPEN_BY_SERIAL_NUMBER),
     * not by description. The serial number comes from the user's entry in
     * Hardware → Simulator → Properties.
     *
     * We don't redirect here — the user configures the Roadrunner's real
     * serial number in WinOLS, so FT_OpenEx will already use the right serial.
     * The proxy just needs to ensure the Roadrunner is visible (PID registered).
     *
     * Log the open attempt so we can verify the serial number in the log file.
     */
    if (flags == FT_OPEN_BY_SERIAL_NUMBER) {
        log_write("SPOOF: FT_OpenEx by serial='%s' (OLS300 slot -> Roadrunner)",
                  (const char*)arg);
    } else if (flags == FT_OPEN_BY_DESCRIPTION) {
        log_write("SPOOF: FT_OpenEx by desc='%s'", (const char*)arg);
    }
    (void)real_desc_out;
    return FALSE;   /* No redirect needed — serial number match handles it */
}
