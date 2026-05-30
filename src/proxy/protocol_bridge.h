#pragma once
/*
 * protocol_bridge.h — OLS300 ↔ MoatesWare protocol translation (S5/S6/S7).
 *
 * CORRECTION: WinOLS communicates with the OLS300 chip simulator (not Batronix).
 * Batronix is an EEPROM programmer — completely unrelated to chip simulation.
 *
 * This module:
 *  1. Intercepts FT_Write bytes from WinOLS (OLS300 protocol)
 *  2. Translates OLS300 commands to MoatesWare commands for the Roadrunner
 *  3. Returns OLS300-format responses to WinOLS via FT_Read
 *
 * OLS300 protocol discovery:
 *  - Run WinOLS with this proxy installed and Roadrunner connected
 *  - Check %TEMP%\winols_bridge.log for FT_Write/FT_Read hex dumps
 *  - The log reveals exact OLS300 command bytes
 *  - Update CMD_OLS300_* constants below once log data is available
 *
 * Current state: PHASE_LOG (passthrough + logging only)
 * After first real WinOLS session: switch to PHASE_BRIDGE
 */

#include <windows.h>
#include "logger.h"
#include "roadrunner.h"

/* Bridge operating phase */
typedef enum {
    BRIDGE_PHASE_LOG    = 0,  /* Passthrough + logging only */
    BRIDGE_PHASE_BRIDGE = 1,  /* Active Batronix->MoatesWare translation */
} bridge_phase_t;

static bridge_phase_t g_phase = BRIDGE_PHASE_BRIDGE;

/* Active Roadrunner handle (set when FT_Open/FT_OpenEx succeeds) */
static FT_HANDLE g_rr_ftdi_handle = NULL;

/* Response buffer for FT_Read after a bridged operation */
#define RESP_BUF_SIZE (512 * 1024)
static BYTE  g_resp_buf[RESP_BUF_SIZE];
static DWORD g_resp_len = 0;
static DWORD g_resp_pos = 0;

static inline void resp_reset(void) { g_resp_len = 0; g_resp_pos = 0; }

static inline void resp_push(const BYTE* data, DWORD len) {
    if (g_resp_len + len > RESP_BUF_SIZE) len = RESP_BUF_SIZE - g_resp_len;
    if (len > 0) {
        memcpy(g_resp_buf + g_resp_len, data, len);
        g_resp_len += len;
    }
}

static inline DWORD resp_pop(BYTE* out, DWORD max_len) {
    DWORD avail = g_resp_len - g_resp_pos;
    DWORD give  = (avail < max_len) ? avail : max_len;
    if (give > 0) {
        memcpy(out, g_resp_buf + g_resp_pos, give);
        g_resp_pos += give;
    }
    return give;
}

/*
 * ── OLS300 command bytes ─────────────────────────────────────────────────
 *
 * UNKNOWN — to be discovered via logging proxy.
 * Run WinOLS with proxy + Roadrunner connected, then read:
 *   %TEMP%\winols_bridge.log
 * The FT_Write TX hex dumps will show exact OLS300 command bytes.
 *
 * Placeholder values — DO NOT use for translation until confirmed.
 */
#define OLS300_CMD_UNKNOWN  0x00   /* placeholder — update from log */
#define OLS300_ACK          0x06   /* standard ACK (likely correct) */
#define OLS300_NAK          0x15   /* standard NAK (likely correct) */

/* Keep Batronix names as aliases during transition for compile compatibility */
#define BAT_STX         0x02
#define BAT_CMD_READ    0x52
#define BAT_CMD_WRITE   0x57
#define BAT_CMD_ERASE   0x45
#define BAT_CMD_VERIFY  0x56
#define BAT_CMD_INIT    0x49
#define BAT_CMD_TRACE   0x54
#define BAT_ACK         OLS300_ACK

/* ── Handle a FT_Write call from WinOLS ─────────────────────────────── */
/*
 * Returns TRUE if the call was handled by the bridge (response in resp_buf).
 * Returns FALSE if it should be passed through to the real FTDI DLL.
 */
static inline BOOL bridge_handle_write(FT_HANDLE handle,
                                        const BYTE* buf, DWORD len,
                                        LPDWORD written_out) {
    if (g_phase == BRIDGE_PHASE_LOG) return FALSE;
    if (handle != g_rr_ftdi_handle || !buf || len < 2) return FALSE;

    BYTE cmd = buf[0];

    /* Init / Identify */
    if (cmd == BAT_CMD_INIT || (cmd == BAT_STX && len >= 2 &&
                                  buf[1] == BAT_CMD_INIT)) {
        log_write("BRIDGE: Batronix INIT -> Roadrunner version request");
        resp_reset();
        BYTE ack = BAT_ACK;
        resp_push(&ack, 1);
        if (written_out) *written_out = len;
        return TRUE;
    }

    /* Read command: [STX][R][addr_hi][addr_lo][size_hi][size_lo][cs] */
    if ((cmd == BAT_CMD_READ || (cmd == BAT_STX && len > 1 &&
                                   buf[1] == BAT_CMD_READ)) && len >= 7) {
        int off = (cmd == BAT_STX) ? 1 : 0;
        DWORD addr = ((DWORD)buf[off+1] << 8) | buf[off+2];
        DWORD size = ((DWORD)buf[off+3] << 8) | buf[off+4];
        /* Round up to 256-byte boundary */
        DWORD aligned_size = (size + 255) & ~255u;
        log_write("BRIDGE: Batronix READ addr=0x%04lX size=0x%04lX",
                  (unsigned long)addr, (unsigned long)size);
        resp_reset();
        BYTE* tmp = (BYTE*)malloc(aligned_size);
        if (tmp && rr_bulk_read(addr & ~255u, aligned_size, tmp)) {
            BYTE ack = BAT_ACK;
            resp_push(&ack, 1);
            resp_push(tmp, size);                  /* send only requested bytes */
            BYTE cs = rr_checksum(tmp, size);
            resp_push(&cs, 1);
        } else {
            BYTE nak = 0x15;
            resp_push(&nak, 1);
        }
        free(tmp);
        if (written_out) *written_out = len;
        return TRUE;
    }

    /* Write command: [STX][W][addr_hi][addr_lo][size_hi][size_lo][data...][cs] */
    if ((cmd == BAT_CMD_WRITE || (cmd == BAT_STX && len > 1 &&
                                    buf[1] == BAT_CMD_WRITE)) && len >= 7) {
        int off = (cmd == BAT_STX) ? 1 : 0;
        DWORD addr      = ((DWORD)buf[off+1] << 8) | buf[off+2];
        DWORD size      = ((DWORD)buf[off+3] << 8) | buf[off+4];
        const BYTE* data = buf + off + 5;
        DWORD aligned_sz = (size + 255) & ~255u;
        log_write("BRIDGE: Batronix WRITE addr=0x%04lX size=0x%04lX",
                  (unsigned long)addr, (unsigned long)size);
        resp_reset();

        /* Pad data to 256-byte boundary */
        BYTE* padded = (BYTE*)calloc(aligned_sz, 1);
        if (padded) {
            memcpy(padded, data, (size < aligned_sz) ? size : aligned_sz);
            BOOL ok = rr_bulk_write(addr & ~255u, aligned_sz, padded);
            free(padded);
            BYTE resp = ok ? BAT_ACK : 0x15;
            resp_push(&resp, 1);
        } else {
            BYTE nak = 0x15;
            resp_push(&nak, 1);
        }
        if (written_out) *written_out = len;
        return TRUE;
    }

    return FALSE;  /* Unknown command — passthrough */
}

/* ── Handle a FT_Read call from WinOLS ──────────────────────────────── */
/*
 * If there is a pending bridge response, drain it into the read buffer.
 * Returns TRUE if the read was served from the bridge response buffer.
 */
static inline BOOL bridge_handle_read(FT_HANDLE handle,
                                       BYTE* buf, DWORD count,
                                       LPDWORD read_out) {
    if (g_phase == BRIDGE_PHASE_LOG) return FALSE;
    if (handle != g_rr_ftdi_handle) return FALSE;
    if (g_resp_len == 0 || g_resp_pos >= g_resp_len) return FALSE;

    DWORD gave = resp_pop(buf, count);
    if (read_out) *read_out = gave;
    log_write("BRIDGE: FT_Read served %lu bytes from response buffer", (unsigned long)gave);
    return TRUE;
}

/* Called when FT_Open/FT_OpenEx successfully opens the Roadrunner */
static inline void bridge_on_open(FT_HANDLE handle, int com_port) {
    g_rr_ftdi_handle = handle;
    resp_reset();
    log_write("BRIDGE: Roadrunner handle registered (handle=%p COM%d)",
              (void*)handle, com_port);
    /* Auto-detect COM port for Roadrunner MoatesWare layer */
    if (com_port > 0) rr_open(com_port);
    else              rr_autodetect();
}

static inline void bridge_on_close(FT_HANDLE handle) {
    if (handle == g_rr_ftdi_handle) {
        g_rr_ftdi_handle = NULL;
        rr_trace_stop();
        rr_close();
        log_write("BRIDGE: Roadrunner handle released");
    }
}
