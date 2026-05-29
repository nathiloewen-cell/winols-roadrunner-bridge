#pragma once
/*
 * logger.h — File-based call logger for the ftd2xx proxy.
 *
 * Every intercepted FTDI call is written to a log file so we can
 * reconstruct the Batronix command protocol empirically (S1 follow-up).
 *
 * Log file: %TEMP%\winols_bridge.log
 */

#include <windows.h>
#include <stdio.h>
#include <stdarg.h>
#include <time.h>

static FILE* g_log = NULL;
static CRITICAL_SECTION g_log_cs;

static inline void log_init(void) {
    char path[MAX_PATH];
    GetTempPathA(MAX_PATH, path);
    strcat_s(path, MAX_PATH, "winols_bridge.log");
    fopen_s(&g_log, path, "a");
    InitializeCriticalSection(&g_log_cs);
    if (g_log) {
        fprintf(g_log,
            "\n=== WinOLS Roadrunner Bridge ===\n"
            "=== Log started ================\n\n");
        fflush(g_log);
    }
}

static inline void log_close(void) {
    if (g_log) { fclose(g_log); g_log = NULL; }
    DeleteCriticalSection(&g_log_cs);
}

static inline void log_write(const char* fmt, ...) {
    if (!g_log) return;
    EnterCriticalSection(&g_log_cs);
    SYSTEMTIME st;
    GetLocalTime(&st);
    fprintf(g_log, "[%02d:%02d:%02d.%03d] ",
            st.wHour, st.wMinute, st.wSecond, st.wMilliseconds);
    va_list ap;
    va_start(ap, fmt);
    vfprintf(g_log, fmt, ap);
    va_end(ap);
    fprintf(g_log, "\n");
    fflush(g_log);
    LeaveCriticalSection(&g_log_cs);
}

/* Hex-dump helper — logs raw bytes with address prefix */
static inline void log_hex(const char* label,
                            const void* buf, DWORD len) {
    if (!g_log || !buf || len == 0) return;
    EnterCriticalSection(&g_log_cs);
    const unsigned char* p = (const unsigned char*)buf;
    DWORD limit = (len > 256) ? 256 : len;   /* cap at 256 bytes */
    fprintf(g_log, "  %s [%lu bytes]%s:\n",
            label, (unsigned long)len,
            (len > 256) ? " (truncated)" : "");
    for (DWORD i = 0; i < limit; i++) {
        if ((i & 15) == 0) fprintf(g_log, "  %04lX: ", (unsigned long)i);
        fprintf(g_log, "%02X ", p[i]);
        if ((i & 15) == 15 || i == limit - 1) fprintf(g_log, "\n");
    }
    fflush(g_log);
    LeaveCriticalSection(&g_log_cs);
}
