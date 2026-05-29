#pragma once
/*
 * roadrunner.h — MoatesWare protocol implementation (S5/S6/S7).
 *
 * Communicates with the Roadrunner EPROM emulator via a Windows COM port
 * (FTDI VCP driver, \\.\COM%d).  All transfers are 256-byte aligned.
 *
 * Protocol layers (from EmUtility analysis):
 *   MMSerial   → Win32 serial (ReadFile/WriteFile on COM handle)
 *   MoatesWare → BulkRead / BulkWrite with 1-byte XOR checksum
 *   MMAutoProm → SetUSBBaud, ReadBlock, WriteBlock, Trace
 *   RoadRunner → SetEmulationMode, GetEmulationMode
 */

#include <windows.h>
#include "logger.h"

/* ── Constants ───────────────────────────────────────────────────────── */
#define RR_INITIAL_BAUD     9600
#define RR_FAST_BAUD       115200
#define RR_BLOCK_SIZE       256        /* All transfers must be multiples */
#define RR_READ_TIMEOUT_MS  3000
#define RR_WRITE_TIMEOUT_MS 3000

/*
 * MoatesWare command bytes (empirically determined from EmUtility
 * behaviour and community reverse-engineering of the Moates protocol).
 *
 * The Roadrunner uses a simple framing:
 *   [CMD] [ADDR_HI] [ADDR_LO] [SIZE_HI] [SIZE_LO]   → for read
 *   [CMD] [ADDR_HI] [ADDR_LO] [SIZE_HI] [SIZE_LO] [DATA...] [CS]  → write
 *
 * NOTE: Exact byte values marked UNKNOWN will be confirmed by the
 * logging proxy (S3) once WinOLS is run with a Roadrunner present.
 * Placeholders below are based on the Moates Ostrich protocol which
 * shares the same codebase.
 */
#define CMD_SET_BAUD         0x53  /* 'S' — SetUSBBaud handshake */
#define CMD_BULK_READ        0x52  /* 'R' — BulkRead  */
#define CMD_BULK_WRITE       0x57  /* 'W' — BulkWrite */
#define CMD_SET_BANK         0x42  /* 'B' — SetBank   */
#define CMD_GET_BANK         0x62  /* 'b' — GetBank   */
#define CMD_SET_EMU_MODE     0x4D  /* 'M' — SetEmulationMode */
#define CMD_GET_EMU_MODE     0x6D  /* 'm' — GetEmulationMode */
#define CMD_TRACE_START      0x54  /* 'T' — Trace mode start */
#define CMD_TRACE_STOP       0x74  /* 't' — Trace mode stop  */
#define CMD_GET_VERSION      0x56  /* 'V' — GetVersion       */
#define CMD_ACK              0x06  /* ACK response byte      */
#define CMD_NAK              0x15  /* NAK response byte      */

/* Emulation mode characters */
#define EMU_MODE_ACTIVE       'A'
#define EMU_MODE_PERSISTENT   'P'
#define EMU_MODE_NONPERSISTENT 'N'
#define EMU_MODE_STATIC       'S'

/* ── COM port handle ─────────────────────────────────────────────────── */
static HANDLE g_rr_com = INVALID_HANDLE_VALUE;
static int    g_rr_com_num = -1;

/* ── Checksum (XOR of all data bytes) ────────────────────────────────── */
static inline BYTE rr_checksum(const BYTE* data, DWORD len) {
    BYTE cs = 0;
    for (DWORD i = 0; i < len; i++) cs ^= data[i];
    return cs;
}

/* ── Low-level serial I/O ────────────────────────────────────────────── */
static inline BOOL rr_write_bytes(const BYTE* buf, DWORD len) {
    if (g_rr_com == INVALID_HANDLE_VALUE) return FALSE;
    DWORD written = 0;
    return WriteFile(g_rr_com, buf, len, &written, NULL) && written == len;
}

static inline BOOL rr_read_bytes(BYTE* buf, DWORD len) {
    if (g_rr_com == INVALID_HANDLE_VALUE) return FALSE;
    DWORD total = 0;
    while (total < len) {
        DWORD got = 0;
        if (!ReadFile(g_rr_com, buf + total, len - total, &got, NULL))
            return FALSE;
        if (got == 0) return FALSE;  /* timeout */
        total += got;
    }
    return TRUE;
}

/* ── Open COM port for Roadrunner ────────────────────────────────────── */
static inline BOOL rr_open(int com_num) {
    char path[32];
    sprintf_s(path, sizeof(path), "\\\\.\\COM%d", com_num);
    g_rr_com = CreateFileA(path,
        GENERIC_READ | GENERIC_WRITE, 0, NULL,
        OPEN_EXISTING, 0, NULL);
    if (g_rr_com == INVALID_HANDLE_VALUE) {
        log_write("RR: Failed to open %s (err=%lu)", path, GetLastError());
        return FALSE;
    }

    DCB dcb = {0};
    dcb.DCBlength = sizeof(dcb);
    GetCommState(g_rr_com, &dcb);
    dcb.BaudRate = RR_INITIAL_BAUD;
    dcb.ByteSize = 8;
    dcb.Parity   = NOPARITY;
    dcb.StopBits = ONESTOPBIT;
    SetCommState(g_rr_com, &dcb);

    COMMTIMEOUTS to = {0};
    to.ReadIntervalTimeout         = 50;
    to.ReadTotalTimeoutMultiplier  = 10;
    to.ReadTotalTimeoutConstant    = RR_READ_TIMEOUT_MS;
    to.WriteTotalTimeoutConstant   = RR_WRITE_TIMEOUT_MS;
    SetCommTimeouts(g_rr_com, &to);

    g_rr_com_num = com_num;
    log_write("RR: Opened COM%d at %d baud", com_num, RR_INITIAL_BAUD);
    return TRUE;
}

static inline void rr_close(void) {
    if (g_rr_com != INVALID_HANDLE_VALUE) {
        CloseHandle(g_rr_com);
        g_rr_com = INVALID_HANDLE_VALUE;
        log_write("RR: COM%d closed", g_rr_com_num);
        g_rr_com_num = -1;
    }
}

/*
 * Auto-detect the Roadrunner COM port by trying COM1-COM20.
 * Sends CMD_GET_VERSION and waits for a response.
 */
static inline BOOL rr_autodetect(void) {
    for (int i = 1; i <= 20; i++) {
        if (rr_open(i)) {
            /* Send version request, wait for ACK */
            BYTE cmd = CMD_GET_VERSION;
            BYTE resp = 0;
            if (rr_write_bytes(&cmd, 1) && rr_read_bytes(&resp, 1)) {
                if (resp == CMD_ACK || resp >= 0x20) {  /* printable = version string */
                    log_write("RR: Autodetect found Roadrunner on COM%d", i);
                    return TRUE;
                }
            }
            rr_close();
        }
    }
    log_write("RR: Autodetect failed — no Roadrunner found on COM1-COM20");
    return FALSE;
}

/* ── Baud-rate negotiation ───────────────────────────────────────────── */
static inline BOOL rr_set_baud(DWORD baud) {
    BYTE cmd[6];
    cmd[0] = CMD_SET_BAUD;
    cmd[1] = (BYTE)((baud >> 24) & 0xFF);
    cmd[2] = (BYTE)((baud >> 16) & 0xFF);
    cmd[3] = (BYTE)((baud >>  8) & 0xFF);
    cmd[4] = (BYTE)( baud        & 0xFF);
    cmd[5] = rr_checksum(cmd + 1, 4);
    if (!rr_write_bytes(cmd, 6)) return FALSE;

    BYTE resp = 0;
    if (!rr_read_bytes(&resp, 1) || resp != CMD_ACK) {
        log_write("RR: SetBaud to %lu failed (resp=0x%02X)", (unsigned long)baud, resp);
        return FALSE;
    }

    /* Switch host side */
    DCB dcb = {0};
    dcb.DCBlength = sizeof(dcb);
    GetCommState(g_rr_com, &dcb);
    dcb.BaudRate = baud;
    SetCommState(g_rr_com, &dcb);
    log_write("RR: Baud switched to %lu", (unsigned long)baud);
    return TRUE;
}

/* ── BulkRead (S5) ───────────────────────────────────────────────────── */
/*
 * Read `size` bytes from emulator RAM starting at `addr`.
 * Both addr and size must be 256-byte aligned.
 * Returns TRUE and fills `out` on success.
 */
static inline BOOL rr_bulk_read(DWORD addr, DWORD size, BYTE* out) {
    if (!out) return FALSE;
    /* Alignment check */
    if ((addr & 0xFF) || (size & 0xFF)) {
        log_write("RR: BulkRead alignment error addr=0x%lX size=0x%lX",
                  (unsigned long)addr, (unsigned long)size);
        return FALSE;
    }

    BYTE cmd[5];
    cmd[0] = CMD_BULK_READ;
    cmd[1] = (BYTE)((addr >> 8) & 0xFF);
    cmd[2] = (BYTE)( addr       & 0xFF);
    cmd[3] = (BYTE)((size >> 8) & 0xFF);
    cmd[4] = (BYTE)( size       & 0xFF);

    log_write("RR: BulkRead addr=0x%04lX size=0x%04lX",
              (unsigned long)addr, (unsigned long)size);

    if (!rr_write_bytes(cmd, 5)) return FALSE;

    /* Read data */
    if (!rr_read_bytes(out, size)) {
        log_write("RR: BulkRead timed out reading %lu bytes", (unsigned long)size);
        return FALSE;
    }

    /* Read + verify checksum byte */
    BYTE cs_received = 0;
    if (!rr_read_bytes(&cs_received, 1)) return FALSE;
    BYTE cs_expected = rr_checksum(out, size);
    if (cs_received != cs_expected) {
        log_write("RR: BulkRead checksum error expected=0x%02X got=0x%02X",
                  cs_expected, cs_received);
        return FALSE;
    }

    log_write("RR: BulkRead OK (%lu bytes)", (unsigned long)size);
    return TRUE;
}

/* ── BulkWrite (S6) ──────────────────────────────────────────────────── */
/*
 * Write `size` bytes from `data` to emulator RAM at `addr`.
 * Both addr and size must be 256-byte aligned.
 */
static inline BOOL rr_bulk_write(DWORD addr, DWORD size, const BYTE* data) {
    if (!data) return FALSE;
    if ((addr & 0xFF) || (size & 0xFF)) {
        log_write("RR: BulkWrite alignment error addr=0x%lX size=0x%lX",
                  (unsigned long)addr, (unsigned long)size);
        return FALSE;
    }

    BYTE hdr[5];
    hdr[0] = CMD_BULK_WRITE;
    hdr[1] = (BYTE)((addr >> 8) & 0xFF);
    hdr[2] = (BYTE)( addr       & 0xFF);
    hdr[3] = (BYTE)((size >> 8) & 0xFF);
    hdr[4] = (BYTE)( size       & 0xFF);

    log_write("RR: BulkWrite addr=0x%04lX size=0x%04lX",
              (unsigned long)addr, (unsigned long)size);

    if (!rr_write_bytes(hdr, 5)) return FALSE;
    if (!rr_write_bytes(data, size)) return FALSE;

    /* Send checksum */
    BYTE cs = rr_checksum(data, size);
    if (!rr_write_bytes(&cs, 1)) return FALSE;

    /* Wait for ACK */
    BYTE resp = 0;
    if (!rr_read_bytes(&resp, 1) || resp != CMD_ACK) {
        log_write("RR: BulkWrite NAK/timeout (resp=0x%02X)", resp);
        return FALSE;
    }

    log_write("RR: BulkWrite OK (%lu bytes)", (unsigned long)size);
    return TRUE;
}

/* ── Trace mode (S7) ─────────────────────────────────────────────────── */
static volatile BOOL g_trace_active = FALSE;
static HANDLE g_trace_thread = NULL;

/* Callback type: called for each address the ECU reads */
typedef void (*rr_trace_callback)(DWORD addr);
static rr_trace_callback g_trace_cb = NULL;

static DWORD WINAPI rr_trace_thread(LPVOID param) {
    (void)param;
    log_write("RR: Trace thread started");
    BYTE addr_buf[2];
    while (g_trace_active) {
        if (rr_read_bytes(addr_buf, 2)) {
            DWORD addr = ((DWORD)addr_buf[0] << 8) | addr_buf[1];
            if (g_trace_cb) g_trace_cb(addr);
        }
    }
    log_write("RR: Trace thread stopped");
    return 0;
}

static inline BOOL rr_trace_start(DWORD start_addr, DWORD end_addr,
                                   rr_trace_callback cb) {
    BYTE cmd[5];
    cmd[0] = CMD_TRACE_START;
    cmd[1] = (BYTE)((start_addr >> 8) & 0xFF);
    cmd[2] = (BYTE)( start_addr       & 0xFF);
    cmd[3] = (BYTE)((end_addr   >> 8) & 0xFF);
    cmd[4] = (BYTE)( end_addr         & 0xFF);
    if (!rr_write_bytes(cmd, 5)) return FALSE;

    BYTE resp = 0;
    if (!rr_read_bytes(&resp, 1) || resp != CMD_ACK) {
        log_write("RR: TraceStart failed (resp=0x%02X)", resp);
        return FALSE;
    }

    g_trace_cb = cb;
    g_trace_active = TRUE;
    g_trace_thread = CreateThread(NULL, 0, rr_trace_thread, NULL, 0, NULL);
    log_write("RR: Trace started [0x%04lX -> 0x%04lX]",
              (unsigned long)start_addr, (unsigned long)end_addr);
    return TRUE;
}

static inline void rr_trace_stop(void) {
    if (!g_trace_active) return;
    g_trace_active = FALSE;
    BYTE cmd = CMD_TRACE_STOP;
    rr_write_bytes(&cmd, 1);
    if (g_trace_thread) {
        WaitForSingleObject(g_trace_thread, 2000);
        CloseHandle(g_trace_thread);
        g_trace_thread = NULL;
    }
    log_write("RR: Trace stopped");
}
