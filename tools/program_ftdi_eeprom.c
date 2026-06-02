/*
 * program_ftdi_eeprom.c - Program FT232R EEPROM via WinDriver (wdapi1660_32.dll)
 *
 * Restores original VID=0x0403/PID=0x6001 on the TTL adapter (currently VID=0547/PID=3000)
 * Uses WinDriver USB control transfers — no FTDI driver needed.
 *
 * Build:
 *   i686-w64-mingw32-gcc -o program_ftdi_eeprom.exe program_ftdi_eeprom.c
 *       -L. -lwdapi1660_32 -DWINVER=0x0601 -D_WIN32_WINNT=0x0601
 *       -lkernel32 -luser32
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdint.h>

/* WinDriver minimal definitions */
typedef PVOID WDU_DRIVER_HANDLE;
typedef PVOID WDU_DEVICE_HANDLE;

typedef struct {
    WORD wVendorId;
    WORD wProductId;
    BYTE bDeviceClass;
    BYTE bDeviceSubClass;
    BYTE bInterfaceClass;
    BYTE bInterfaceSubClass;
    BYTE bInterfaceProtocol;
} WDU_MATCH_TABLE;

typedef struct {
    BOOL (__cdecl *pfDeviceAttach)(WDU_DEVICE_HANDLE, void*, PVOID);
    void (__cdecl *pfDeviceDetach)(WDU_DEVICE_HANDLE, PVOID);
    void*    pUserData;
} WDU_EVENT_TABLE;

/* Function pointers */
typedef DWORD (__cdecl *PFN_WDC_OPEN)(DWORD, const char*);
typedef DWORD (__cdecl *PFN_WDU_INIT)(WDU_DRIVER_HANDLE*, WDU_MATCH_TABLE*,
                                        DWORD, void*, const char*, DWORD);
typedef DWORD (__cdecl *PFN_WDU_TRANSFER_DEFAULT)(WDU_DEVICE_HANDLE, DWORD, DWORD,
    void*, DWORD, DWORD*, BYTE*, DWORD);
typedef DWORD (__cdecl *PFN_WDU_UNINIT)(WDU_DRIVER_HANDLE);

static HMODULE g_wdapi = NULL;
static PFN_WDC_OPEN            WDC_DriverOpen = NULL;
static PFN_WDU_INIT            WDU_Init       = NULL;
static PFN_WDU_TRANSFER_DEFAULT WDU_TransferDefaultPipe = NULL;
static PFN_WDU_UNINIT          WDU_Uninit     = NULL;

/* Device handle for callback */
static WDU_DEVICE_HANDLE g_device = NULL;

/* Callback when device is found */
static BOOL __cdecl on_attach(WDU_DEVICE_HANDLE hDev, void* pDevInfo, PVOID pData) {
    printf("  Device attached! handle=%p\n", hDev);
    g_device = hDev;
    return TRUE;  /* accept */
}

static DWORD send_control(WDU_DEVICE_HANDLE hDev, BYTE req_type, BYTE request,
                            WORD value, WORD index, BYTE* buf, DWORD len) {
    /* Build setup packet as 8-byte array */
    BYTE setup[8] = {req_type, request,
                     (BYTE)(value & 0xFF), (BYTE)(value >> 8),
                     (BYTE)(index & 0xFF), (BYTE)(index >> 8),
                     (BYTE)(len & 0xFF),   (BYTE)(len >> 8)};
    DWORD transferred = 0;
    DWORD is_read = (req_type & 0x80) ? 1 : 0;
    return WDU_TransferDefaultPipe(hDev, is_read, 0, buf ? buf : (void*)"\0",
                                   len ? len : 1, &transferred, setup, 3000);
}

static WORD read_eeprom_word(WDU_DEVICE_HANDLE hDev, WORD addr) {
    BYTE buf[2] = {0, 0};
    DWORD r = send_control(hDev, 0xC0, 0x90, 0, addr, buf, 2);
    if (r != 0) { printf("  Read @%d failed: 0x%08X\n", addr, r); return 0xFFFF; }
    return (WORD)(buf[0] | (buf[1] << 8));
}

static BOOL write_eeprom_word(WDU_DEVICE_HANDLE hDev, WORD addr, WORD val) {
    DWORD r = send_control(hDev, 0x40, 0x91, val, addr, NULL, 0);
    if (r != 0) { printf("  Write @%d=0x%04X failed: 0x%08X\n", addr, val, r); return FALSE; }
    return TRUE;
}

int main(void) {
    printf("=== FTDI FT232R EEPROM Programmer ===\n");
    printf("Restoring VID=0x0547/PID=0x3000 → VID=0x0403/PID=0x6001\n\n");

    /* Load wdapi */
    char path[MAX_PATH];
    GetModuleFileNameA(NULL, path, MAX_PATH);
    char* last = strrchr(path, '\\');
    if (last) strcpy_s(last+1, MAX_PATH-(last-path)-1, "wdapi1660_32.dll");
    else strcpy_s(path, MAX_PATH, "wdapi1660_32.dll");

    g_wdapi = LoadLibraryA(path);
    if (!g_wdapi) {
        /* Try system path */
        g_wdapi = LoadLibraryA("C:\\Program Files\\EVC\\WinOLS\\wdapi1660_32.dll");
    }
    if (!g_wdapi) {
        printf("ERROR: wdapi1660_32.dll not found!\n");
        return 1;
    }
    printf("Loaded wdapi1660_32.dll\n");

    WDC_DriverOpen         = (PFN_WDC_OPEN)GetProcAddress(g_wdapi, "WDC_DriverOpen");
    WDU_Init               = (PFN_WDU_INIT)GetProcAddress(g_wdapi, "WDU_Init");
    WDU_TransferDefaultPipe= (PFN_WDU_TRANSFER_DEFAULT)GetProcAddress(g_wdapi, "WDU_TransferDefaultPipe");
    WDU_Uninit             = (PFN_WDU_UNINIT)GetProcAddress(g_wdapi, "WDU_Uninit");

    if (!WDC_DriverOpen || !WDU_Init || !WDU_TransferDefaultPipe) {
        printf("ERROR: Failed to get wdapi functions\n");
        return 1;
    }

    /* Open WinDriver */
    DWORD r = WDC_DriverOpen(0, "12345abcde1234.license");
    printf("WDC_DriverOpen → 0x%08X\n", r);
    if (r != 0) { printf("ERROR: WDC_DriverOpen failed\n"); return 1; }

    /* Register for our device */
    WDU_MATCH_TABLE match = {0x0547, 0x3000, 0, 0, 0, 0, 0};
    WDU_EVENT_TABLE events = {on_attach, NULL, NULL};
    WDU_DRIVER_HANDLE hDriver = NULL;

    r = WDU_Init(&hDriver, &match, 1, &events, "12345abcde1234.license", 0);
    printf("WDU_Init → 0x%08X handle=%p\n", r, hDriver);

    if (r != 0) {
        printf("ERROR: WDU_Init failed\n");
        return 1;
    }

    /* Wait for device attach */
    printf("Waiting for device...\n");
    int timeout = 50;
    while (!g_device && timeout-- > 0) Sleep(100);

    if (!g_device) {
        printf("ERROR: Device not found (timeout)\n");
        if (WDU_Uninit) WDU_Uninit(hDriver);
        return 1;
    }

    printf("Device found!\n\n");
    printf("Reading EEPROM...\n");

    /* Read current EEPROM */
    WORD eeprom[64];
    int num_words = 0;
    for (int i = 0; i < 64; i++) {
        eeprom[i] = read_eeprom_word(g_device, (WORD)i);
        if (eeprom[i] == 0xFFFF && i > 4) break;
        num_words = i + 1;
    }
    printf("  Read %d words\n", num_words);

    if (num_words >= 3) {
        printf("  Current VID=0x%04X PID=0x%04X\n", eeprom[1], eeprom[2]);
    }

    /* Calculate FTDI checksum */
    WORD chk = 0xAAAA;
    for (int i = 0; i < num_words-1; i++) {
        chk ^= eeprom[i];
        chk = (WORD)((chk << 1) | (chk >> 15));
    }

    /* New values */
    WORD new_vid = 0x0403;
    WORD new_pid = 0x6001;

    printf("\nProgramming VID=0x%04X PID=0x%04X...\n", new_vid, new_pid);

    /* Update checksum with new values */
    WORD eeprom_new[64];
    memcpy(eeprom_new, eeprom, sizeof(eeprom));
    eeprom_new[1] = new_vid;
    eeprom_new[2] = new_pid;

    /* Recalculate checksum */
    WORD new_chk = 0xAAAA;
    for (int i = 0; i < num_words-1; i++) {
        new_chk ^= eeprom_new[i];
        new_chk = (WORD)((new_chk << 1) | (new_chk >> 15));
    }
    eeprom_new[num_words-1] = new_chk;

    BOOL ok = TRUE;

    /* Write VID */
    printf("  Writing VID=0x%04X @ word 1...", new_vid);
    if (write_eeprom_word(g_device, 1, new_vid)) {
        printf(" OK\n");
    } else { ok = FALSE; }

    /* Write PID */
    printf("  Writing PID=0x%04X @ word 2...", new_pid);
    if (write_eeprom_word(g_device, 2, new_pid)) {
        printf(" OK\n");
    } else { ok = FALSE; }

    /* Write checksum */
    printf("  Writing checksum=0x%04X @ word %d...", new_chk, num_words-1);
    if (write_eeprom_word(g_device, (WORD)(num_words-1), new_chk)) {
        printf(" OK\n");
    } else { ok = FALSE; }

    /* Verify */
    printf("\nVerifying...\n");
    WORD v_vid = read_eeprom_word(g_device, 1);
    WORD v_pid = read_eeprom_word(g_device, 2);
    printf("  VID=0x%04X PID=0x%04X\n", v_vid, v_pid);

    if (v_vid == new_vid && v_pid == new_pid) {
        printf("\nSUCCESS! EEPROM programmed.\n");
        printf("Please DISCONNECT and RECONNECT the TTL adapter.\n");
        printf("Windows will install FTDI VCP driver → COM port appears.\n");
        printf("Then FT_Prog can load the XML for full configuration.\n");
    } else {
        printf("\nERROR: Verification failed! Device may need to be reconnected.\n");
        ok = FALSE;
    }

    if (WDU_Uninit) WDU_Uninit(hDriver);
    FreeLibrary(g_wdapi);

    printf("\nPress Enter to exit...");
    getchar();
    return ok ? 0 : 1;
}
