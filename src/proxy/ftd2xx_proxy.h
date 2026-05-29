#pragma once
/*
 * ftd2xx_proxy.h — FTDI D2XX type definitions for the WinOLS proxy DLL.
 *
 * Mirrors the official ftd2xx.h API so we can intercept every call
 * WinOLS / BSL100.dll makes to the real FTDI library.
 */

#include <windows.h>
#include <stdint.h>

/* ── Handle type ─────────────────────────────────────────────────────── */
typedef PVOID  FT_HANDLE;
typedef ULONG  FT_STATUS;

/* ── Status codes ───────────────────────────────────────────────────── */
#define FT_OK                          0
#define FT_INVALID_HANDLE              1
#define FT_DEVICE_NOT_FOUND            2
#define FT_DEVICE_NOT_OPENED           3
#define FT_IO_ERROR                    4
#define FT_INSUFFICIENT_RESOURCES      5
#define FT_INVALID_PARAMETER           6
#define FT_INVALID_BAUD_RATE           7
#define FT_DEVICE_NOT_OPENED_FOR_ERASE 8
#define FT_DEVICE_NOT_OPENED_FOR_WRITE 9
#define FT_FAILED_TO_WRITE_DEVICE     10
#define FT_EEPROM_READ_FAILED         11
#define FT_EEPROM_WRITE_FAILED        12
#define FT_EEPROM_ERASE_FAILED        13
#define FT_EEPROM_NOT_PRESENT         14
#define FT_EEPROM_NOT_PROGRAMMED      15
#define FT_INVALID_ARGS               16
#define FT_NOT_SUPPORTED              17
#define FT_OTHER_ERROR                18

/* ── FT_OpenEx flags ─────────────────────────────────────────────────── */
#define FT_OPEN_BY_SERIAL_NUMBER  1
#define FT_OPEN_BY_DESCRIPTION    2
#define FT_OPEN_BY_LOCATION       4

/* ── FT_ListDevices flags ─────────────────────────────────────────────── */
#define FT_LIST_NUMBER_ONLY   0x80000000
#define FT_LIST_BY_INDEX      0x40000000
#define FT_LIST_ALL           0x20000000

/* ── Purge flags ────────────────────────────────────────────────────── */
#define FT_PURGE_RX 1
#define FT_PURGE_TX 2

/* ── Data characteristics ───────────────────────────────────────────── */
#define FT_BITS_8  8
#define FT_BITS_7  7
#define FT_STOP_BITS_1 0
#define FT_STOP_BITS_2 2
#define FT_PARITY_NONE 0
#define FT_PARITY_ODD  1
#define FT_PARITY_EVEN 2

/* ── Flow control ───────────────────────────────────────────────────── */
#define FT_FLOW_NONE     0x0000
#define FT_FLOW_RTS_CTS  0x0100
#define FT_FLOW_DTR_DSR  0x0200
#define FT_FLOW_XON_XOFF 0x0400

/* ── Bit-bang modes ──────────────────────────────────────────────────── */
#define FT_BITMODE_RESET        0x00
#define FT_BITMODE_ASYNC_BITBANG 0x01
#define FT_BITMODE_MPSSE        0x02
#define FT_BITMODE_SYNC_BITBANG 0x04

/* ── Device info ────────────────────────────────────────────────────── */
#define FT_FLAGS_OPENED  1
#define FT_FLAGS_HISPEED 2

typedef struct _ft_device_list_info_node {
    ULONG   Flags;
    ULONG   Type;
    ULONG   ID;
    DWORD   LocId;
    char    SerialNumber[16];
    char    Description[64];
    FT_HANDLE Handle;
} FT_DEVICE_LIST_INFO_NODE;

typedef enum {
    FT_DEVICE_BM = 0,
    FT_DEVICE_AM,
    FT_DEVICE_100AX,
    FT_DEVICE_UNKNOWN,
    FT_DEVICE_2232C,
    FT_DEVICE_232R,
    FT_DEVICE_2232H,
    FT_DEVICE_4232H,
    FT_DEVICE_232H,
    FT_DEVICE_X_SERIES,
} FT_DEVICE;

/* ── EEPROM structures ───────────────────────────────────────────────── */
typedef struct ft_program_data {
    DWORD  Signature1;
    DWORD  Signature2;
    DWORD  Version;
    WORD   VendorId;
    WORD   ProductId;
    char*  Manufacturer;
    char*  ManufacturerId;
    char*  Description;
    char*  SerialNumber;
    WORD   MaxPower;
    WORD   PnP;
    WORD   SelfPowered;
    WORD   RemoteWakeup;
    /* ... additional fields omitted for brevity */
} FT_PROGRAM_DATA, *PFT_PROGRAM_DATA;
