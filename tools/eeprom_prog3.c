/*
 * eeprom_prog2.c - Simple FTDI EEPROM programmer via WinDriver
 * Build: i686-w64-mingw32-gcc -o eeprom_prog2.exe eeprom_prog2.c -L. -lkernel32
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>

/* ?????? WinDriver minimal types ????????????????????????????????????????????????????????????????????????????????? */
typedef PVOID WDU_DRIVER_HANDLE;
typedef PVOID WDU_DEVICE_HANDLE;

typedef struct {
    WORD  wVendorId, wProductId;
    BYTE  bDevClass, bDevSubClass;
    BYTE  bIfClass, bIfSubClass, bIfProtocol;
} WDU_MATCH_TABLE;

typedef struct {
    BOOL  (__cdecl *pfDeviceAttach)(WDU_DEVICE_HANDLE, PVOID, PVOID);
    VOID  (__cdecl *pfDeviceDetach)(WDU_DEVICE_HANDLE, PVOID);
    PVOID pUserData;
} WDU_EVENT_TABLE;

/* ?????? Global device handle ????????????????????????????????????????????????????????????????????????????????????????????? */
static volatile WDU_DEVICE_HANDLE g_dev = NULL;
static HANDLE g_event;

/* ?????? Callback ????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????? */
static BOOL __cdecl on_attach(WDU_DEVICE_HANDLE hDev, PVOID pInfo, PVOID pData) {
    g_dev = hDev;
    SetEvent(g_event);
    printf("  Attached: %p\n", hDev);
    return TRUE;
}

/* ?????? USB control transfer ????????????????????????????????????????????????????????????????????????????????????????????? */
static DWORD usb_ctrl(WDU_DEVICE_HANDLE hDev,
                       BYTE req_type, BYTE req,
                       WORD val, WORD idx,
                       BYTE *buf, DWORD len,
                       DWORD *got) {
    typedef DWORD (__cdecl *FN)(PVOID,DWORD,DWORD,PVOID,DWORD,DWORD*,BYTE*,DWORD);
    static FN fn = NULL;
    if (!fn) {
        HMODULE h = GetModuleHandleA("wdapi1660_32.dll");
        if (!h) { printf("  wdapi not loaded!\n"); return 0xFFFFFFFF; }
        fn = (FN)GetProcAddress(h, "WDU_TransferDefaultPipe");
        if (!fn) { printf("  WDU_TransferDefaultPipe not found!\n"); return 0xFFFFFFFF; }
    }

    /* Setup packet */
    BYTE setup[8] = {
        req_type, req,
        (BYTE)(val & 0xFF), (BYTE)(val >> 8),
        (BYTE)(idx & 0xFF), (BYTE)(idx >> 8),
        (BYTE)(len & 0xFF), (BYTE)(len >> 8)
    };

    BYTE dummy[4] = {0};
    BYTE *pbuf = (buf && len) ? buf : dummy;
    DWORD xferred = 0;
    DWORD is_read = (req_type & 0x80) ? 1 : 0;
    DWORD r = fn(hDev, is_read, 0, pbuf, len, &xferred, setup, 3000);
    if (got) *got = xferred;
    return r;
}

static WORD eeprom_read(WDU_DEVICE_HANDLE h, WORD addr) {
    BYTE buf[2] = {0};
    DWORD got = 0;
    DWORD r = usb_ctrl(h, 0xC0, 0x90, 0, addr, buf, 2, &got);
    if (r != 0) { printf("  Read@%d failed 0x%08X\n", addr, r); return 0xFFFF; }
    return (WORD)(buf[0] | (buf[1]<<8));
}

static BOOL eeprom_write(WDU_DEVICE_HANDLE h, WORD addr, WORD val) {
    DWORD r = usb_ctrl(h, 0x40, 0x91, val, addr, NULL, 0, NULL);
    if (r != 0) printf("  Write@%d=0x%04X failed 0x%08X\n", addr, val, r);
    return (r == 0);
}

int main(void) {
    printf("=== FT232R EEPROM Programmer ===\n");
    printf("VID=0403/PID=6001 -> VID=0403/PID=6001\n\n");

    /* Load wdapi */
    HMODULE wdapi = LoadLibraryA("C:\\Windows\\SysWOW64\\wdapi1660_32.dll");
    if (!wdapi) { printf("Cannot load wdapi1660_32.dll!\n"); return 1; }
    printf("wdapi loaded\n");

    /* WDC_DriverOpen */
    typedef DWORD (__cdecl *FN_OPEN)(DWORD, const char*);
    FN_OPEN WDC_Open = (FN_OPEN)GetProcAddress(wdapi, "WDC_DriverOpen");
    if (!WDC_Open) { printf("No WDC_DriverOpen\n"); return 1; }
    DWORD r = WDC_Open(0, "12345abcde1234.license");
    printf("WDC_DriverOpen = 0x%08X %s\n", r, r==0?"OK":"FAIL");
    if (r != 0) return 1;

    /* WDU_Init */
    typedef DWORD (__cdecl *FN_INIT)(PVOID*, WDU_MATCH_TABLE*, DWORD, WDU_EVENT_TABLE*, const char*, DWORD);
    FN_INIT WDU_Init = (FN_INIT)GetProcAddress(wdapi, "WDU_Init");
    if (!WDU_Init) { printf("No WDU_Init\n"); return 1; }

    g_event = CreateEventA(NULL, FALSE, FALSE, NULL);

    WDU_MATCH_TABLE match = {0x0403, 0x6001, 0, 0, 0, 0, 0};
    WDU_EVENT_TABLE evts;
    memset(&evts, 0, sizeof(evts));
    evts.pfDeviceAttach = on_attach;

    PVOID hDrv = NULL;
    r = WDU_Init(&hDrv, &match, 1, &evts, "12345abcde1234.license", 0);
    printf("WDU_Init = 0x%08X %s\n", r, r==0?"OK":"FAIL");
    if (r != 0) return 1;

    printf("Waiting for device...\n");
    WaitForSingleObject(g_event, 5000);

    if (!g_dev) { printf("Device not found!\n"); return 1; }
    printf("Device: %p\n\n", g_dev);

    /* Read EEPROM */
    printf("Reading EEPROM...\n");
    WORD words[64] = {0};
    int nw = 0;
    for (int i = 0; i < 64; i++) {
        words[i] = eeprom_read(g_dev, (WORD)i);
        if (words[i] == 0xFFFF && i > 4) break;
        nw = i + 1;
    }
    printf("Read %d words. VID=0x%04X PID=0x%04X\n\n", nw, words[1], words[2]);
    if (nw < 3) { printf("Read too few words!\n"); return 1; }

    /* Program new values */
    WORD new_vid = 0x0547, new_pid = 0x3000;
    words[1] = new_vid;
    words[2] = new_pid;

    WORD chk = 0xAAAA;
    for (int i = 0; i < nw-1; i++) {
        chk ^= words[i];
        chk = (WORD)((chk<<1)|(chk>>15));
    }
    words[nw-1] = chk;

    printf("Programming VID=0x%04X PID=0x%04X...\n", new_vid, new_pid);
    printf("  VID: %s\n", eeprom_write(g_dev, 1, new_vid) ? "OK" : "FAIL");
    printf("  PID: %s\n", eeprom_write(g_dev, 2, new_pid) ? "OK" : "FAIL");
    printf("  CHK: %s\n", eeprom_write(g_dev, (WORD)(nw-1), chk) ? "OK" : "FAIL");

    Sleep(100);

    printf("\nVerify: VID=0x%04X PID=0x%04X\n",
           eeprom_read(g_dev, 1), eeprom_read(g_dev, 2));

    typedef DWORD (__cdecl *FN_UNINIT)(PVOID);
    FN_UNINIT WDU_Uninit = (FN_UNINIT)GetProcAddress(wdapi, "WDU_Uninit");
    if (WDU_Uninit) WDU_Uninit(hDrv);

    printf("\nDone! Reconnect the TTL adapter now.\n");
    printf("Press Enter...\n");
    getchar();
    return 0;
}

