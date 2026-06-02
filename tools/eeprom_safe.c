/*
 * eeprom_safe.c - Safer FTDI EEPROM programmer
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>

static volatile HANDLE g_hDev = NULL;

static BOOL __cdecl on_attach(HANDLE hDev, void* pInfo, void* pData) {
    printf("  Attached! handle=%p\n", (void*)hDev);
    fflush(stdout);
    g_hDev = hDev;
    return TRUE;
}

static DWORD do_ctrl(HMODULE wdapi, HANDLE hDev,
                      BYTE rt, BYTE req, WORD val, WORD idx,
                      BYTE* buf, DWORD len, DWORD* got) {
    /* Try WDU_Transfer with pipe 0 (control endpoint) */
    typedef DWORD (__cdecl *FN)(HANDLE,DWORD,DWORD,DWORD,void*,DWORD,DWORD*,BYTE*,DWORD);
    FN fn = (FN)GetProcAddress(wdapi, "WDU_Transfer");
    if (!fn) { printf("  No WDU_Transfer!\n"); return 0xFF; }

    static BYTE setup[8];
    setup[0]=rt; setup[1]=req;
    setup[2]=(BYTE)(val&0xFF); setup[3]=(BYTE)(val>>8);
    setup[4]=(BYTE)(idx&0xFF); setup[5]=(BYTE)(idx>>8);
    setup[6]=(BYTE)(len&0xFF); setup[7]=(BYTE)(len>>8);
    static BYTE dummy[4] = {0};
    static DWORD tr;
    tr = 0;
    DWORD is_read = (rt & 0x80) ? 1 : 0;
    printf("    ctrl: rt=0x%02X req=0x%02X val=0x%04X idx=0x%04X len=%lu rd=%lu\n",
           rt, req, val, idx, len, is_read);
    fflush(stdout);
    /* For OUT transfers (write/erase) with len=0: pass len=0, dummy ptr */
    /* For IN transfers (read) with len>0: pass actual len and buf */
    BYTE* pbuf = (buf && len > 0) ? buf : dummy;
    DWORD blen = len;  /* Use exact len, not len?len:1 */
    DWORD res = fn(hDev, 0, is_read, 0, pbuf, blen, &tr, setup, 3000);
    printf("    result=0x%lX got=%lu\n", res, tr); fflush(stdout);
    return res;
}

int main(void) {
    printf("=== FTDI EEPROM Safe Programmer ===\n");
    printf("VID=0547/PID=3000 -> VID=0403/PID=6001\n\n");
    fflush(stdout);

    HMODULE wdapi = LoadLibraryA("C:\\Windows\\SysWOW64\\wdapi1660_32.dll");
    if (!wdapi) { printf("Load failed: %lu\n", GetLastError()); return 1; }
    printf("DLL loaded\n"); fflush(stdout);

    typedef DWORD (__cdecl *FN_OPEN)(DWORD, const char*);
    FN_OPEN wdc_open = (FN_OPEN)GetProcAddress(wdapi, "WDC_DriverOpen");
    if (!wdc_open) { printf("No WDC_DriverOpen\n"); return 1; }

    DWORD r = wdc_open(0, "12345abcde1234.license");
    printf("WDC_DriverOpen = 0x%08lX %s\n", r, r==0?"OK":"FAIL");
    if (r) return 1;
    fflush(stdout);

    /* Match table */
    typedef struct { WORD vid,pid,dc,dsc,ic,isc,ip; } MTAB;
    MTAB mt = {0x0547, 0x3000, 0, 0, 0, 0, 0};

    /* Event table */
    typedef struct { BOOL (__cdecl *att)(HANDLE,void*,void*);
                     void (__cdecl *det)(HANDLE,void*); void* ud; } ETAB;
    ETAB et = {on_attach, NULL, NULL};

    typedef DWORD (__cdecl *FN_INIT)(void**,MTAB*,DWORD,ETAB*,const char*,DWORD);
    FN_INIT wdu_init = (FN_INIT)GetProcAddress(wdapi, "WDU_Init");
    if (!wdu_init) { printf("No WDU_Init\n"); return 1; }

    void* hDrv = NULL;
    r = wdu_init(&hDrv, &mt, 1, &et, "12345abcde1234.license", 0);
    printf("WDU_Init = 0x%08lX %s hDrv=%p\n", r, r==0?"OK":"FAIL", hDrv);
    if (r) return 1;
    fflush(stdout);

    /* Wait for attach */
    printf("Waiting for device (5s)...\n"); fflush(stdout);
    for (int i = 0; i < 50 && !g_hDev; i++) Sleep(100);

    if (!g_hDev) { printf("Not found!\n"); return 1; }
    printf("Got device: %p\n\n", (void*)g_hDev); fflush(stdout);

    /* Read EEPROM — stop at 35 words (FT232R safe limit via control transfers) */
    printf("Reading EEPROM (max 35 words)...\n"); fflush(stdout);
    WORD words[64] = {0};
    int nw = 35;  /* Stop before crash at addr 0x23 */
    for (int i = 0; i < nw; i++) {
        BYTE buf[2] = {0,0};
        DWORD got = 0;
        DWORD rv = do_ctrl(wdapi, g_hDev, 0xC0, 0x90, 0, (WORD)i, buf, 2, &got);
        if (rv != 0) { printf("  Read@%d fail 0x%08lX\n", i, rv); break; }
        words[i] = (WORD)(buf[0]|(buf[1]<<8));
    }
    printf("VID=0x%04X PID=0x%04X (all zeros=blank EEPROM)\n", words[1], words[2]);
    if (nw < 3) return 1;
    fflush(stdout);

    /* Step 1: Erase EEPROM (required before writing) */
    printf("Erasing EEPROM...\n"); fflush(stdout);
    DWORD er = do_ctrl(wdapi, g_hDev, 0x40, 0x92, 0, 0, NULL, 0, NULL);  /* SIO_ERASE_EEPROM */
    printf("  Erase result: 0x%lX %s\n", er, er==0?"OK":"FAIL"); fflush(stdout);
    Sleep(100);

    /* Step 2: Program VID and PID */
    WORD nv = 0x0403, np = 0x6001;

    /* Use original FTDI RoadRunner.xml config values */
    /* Just write the essential fields: word 0 (flags), word 1 (VID), word 2 (PID) */
    /* FT232R EEPROM format:
       Word 0: USB Config descriptor / flags
       Word 1: VID
       Word 2: PID
       Word 3: Device version
       ...checksum at last word */

    /* Load from XML values if available, otherwise use minimal set */
    WORD new_eeprom[64] = {0};
    new_eeprom[0] = 0x0000;  /* flags */
    new_eeprom[1] = nv;       /* VID */
    new_eeprom[2] = np;       /* PID */
    new_eeprom[3] = 0x0600;   /* bcdDevice */
    /* checksum at word 34 (nw-1) */
    WORD chk = 0xAAAA;
    for (int i=0; i<nw-1; i++) { chk^=new_eeprom[i]; chk=(WORD)((chk<<1)|(chk>>15)); }
    new_eeprom[nw-1] = chk;

    printf("Writing VID=0x%04X PID=0x%04X CHK=0x%04X...\n", nv, np, chk); fflush(stdout);
    DWORD w1 = do_ctrl(wdapi, g_hDev, 0x40, 0x91, nv, 1, NULL, 0, NULL);
    printf("  VID write: 0x%lX %s\n", w1, w1==0?"OK":"FAIL"); fflush(stdout);
    DWORD w2 = do_ctrl(wdapi, g_hDev, 0x40, 0x91, np, 2, NULL, 0, NULL);
    printf("  PID write: 0x%lX %s\n", w2, w2==0?"OK":"FAIL"); fflush(stdout);
    DWORD w3 = do_ctrl(wdapi, g_hDev, 0x40, 0x91, chk, (WORD)(nw-1), NULL, 0, NULL);
    printf("  CHK write: 0x%lX %s\n", w3, w3==0?"OK":"FAIL"); fflush(stdout);

    if (w1==0 && w2==0 && w3==0)
        printf("\nSUCCESS! Reconnect to get FTDI COM port (VID=0x0403/PID=0x6001).\n");
    else
        printf("\nWrite failed. Try running as admin or check WinDriver setup.\n");

    typedef DWORD (__cdecl *FN_UNINIT)(void*);
    FN_UNINIT wdu_uninit = (FN_UNINIT)GetProcAddress(wdapi, "WDU_Uninit");
    if (wdu_uninit) wdu_uninit(hDrv);
    FreeLibrary(wdapi);
    return 0;
}
