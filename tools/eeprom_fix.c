/*
 * eeprom_fix.c - Fix FT232R EEPROM: VID=0x0403/PID=0x3000 -> PID=0x6001
 * EEPROM was already ERASED (all 0xFFFF). Just write VID+PID+correct checksum.
 * Build: i686-w64-mingw32-gcc -o eeprom_fix.exe eeprom_fix.c -lkernel32 -luser32
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>

static volatile HANDLE g_hDev = NULL;

static BOOL __cdecl on_attach(HANDLE hDev, void* pInfo, void* pData) {
    printf("  Attached: %p\n", (void*)hDev); fflush(stdout);
    g_hDev = hDev;
    return TRUE;
}

static DWORD do_ctrl(HMODULE wdapi, HANDLE hDev,
                     BYTE rt, BYTE req, WORD val, WORD idx,
                     BYTE* buf, DWORD len) {
    typedef DWORD (__cdecl *FN)(HANDLE,DWORD,DWORD,DWORD,void*,DWORD,DWORD*,BYTE*,DWORD);
    FN fn = (FN)GetProcAddress(wdapi, "WDU_Transfer");
    if (!fn) return 0xFF;
    static BYTE setup[8];
    setup[0]=rt; setup[1]=req;
    setup[2]=(BYTE)(val&0xFF); setup[3]=(BYTE)(val>>8);
    setup[4]=(BYTE)(idx&0xFF); setup[5]=(BYTE)(idx>>8);
    setup[6]=(BYTE)(len&0xFF); setup[7]=(BYTE)(len>>8);
    static BYTE dummy[4]={0};
    static DWORD tr;
    tr=0;
    DWORD is_read=(rt&0x80)?1:0;
    BYTE* pbuf=(buf&&len)?buf:dummy;
    return fn(hDev, 0, is_read, 0, pbuf, len, &tr, setup, 3000);
}

int main(void) {
    printf("=== FT232R EEPROM Fix: PID 0x3000 -> 0x6001 ===\n\n"); fflush(stdout);

    HMODULE wdapi = LoadLibraryA("C:\\Windows\\SysWOW64\\wdapi1660_32.dll");
    if (!wdapi) { printf("DLL load failed: %lu\n", GetLastError()); return 1; }
    printf("DLL loaded\n"); fflush(stdout);

    typedef DWORD (__cdecl *FN_OPEN)(DWORD,const char*);
    FN_OPEN wdc_open=(FN_OPEN)GetProcAddress(wdapi,"WDC_DriverOpen");
    DWORD r=wdc_open(0,"12345abcde1234.license");
    printf("WDC_DriverOpen = 0x%08lX %s\n",r,r==0?"OK":"FAIL");
    if(r) return 1;

    typedef struct{WORD vid,pid,dc,dsc,ic,isc,ip;}MTAB;
    MTAB mt={0x0403,0x3000,0,0,0,0,0};
    typedef struct{BOOL(__cdecl*att)(HANDLE,void*,void*);void(__cdecl*det)(HANDLE,void*);void*ud;}ETAB;
    ETAB et={on_attach,NULL,NULL};
    typedef DWORD(__cdecl*FN_INIT)(void**,MTAB*,DWORD,ETAB*,const char*,DWORD);
    FN_INIT wdu_init=(FN_INIT)GetProcAddress(wdapi,"WDU_Init");
    void* hDrv=NULL;
    r=wdu_init(&hDrv,&mt,1,&et,"12345abcde1234.license",0);
    printf("WDU_Init = 0x%08lX %s hDrv=%p\n",r,r==0?"OK":"FAIL",hDrv);
    if(r) return 1;

    printf("Waiting for device (5s)...\n"); fflush(stdout);
    for(int i=0;i<50&&!g_hDev;i++) Sleep(100);
    if(!g_hDev){printf("Device not found!\n");return 1;}
    printf("Got device: %p\n\n",(void*)g_hDev); fflush(stdout);

    /*
     * EEPROM state after erase: ALL 64 words = 0xFFFF
     * We write only words 1 (VID) and 2 (PID).
     * Words 0 and 3-62 remain 0xFFFF.
     * We must compute checksum over all 63 words as they actually are.
     */
    WORD eeprom[64];
    for(int i=0;i<64;i++) eeprom[i]=0xFFFF; /* post-erase state */
    eeprom[1]=0x0403; /* VID */
    eeprom[2]=0x6001; /* PID */

    /* FT232R checksum: rolling XOR + rotate-left over words[0..62] */
    WORD chk=0xAAAA;
    for(int i=0;i<63;i++){
        chk^=eeprom[i];
        chk=(WORD)((chk<<1)|(chk>>15));
    }
    eeprom[63]=chk;
    printf("Computed checksum: 0x%04X\n",chk); fflush(stdout);

    /* Write VID */
    DWORD w1=do_ctrl(wdapi,g_hDev,0x40,0x91,0x0403,1,NULL,0);
    printf("VID write [1]=0x0403: %s (0x%lX)\n",w1==0?"OK":"FAIL",w1); fflush(stdout);

    /* Write PID */
    DWORD w2=do_ctrl(wdapi,g_hDev,0x40,0x91,0x6001,2,NULL,0);
    printf("PID write [2]=0x6001: %s (0x%lX)\n",w2==0?"OK":"FAIL",w2); fflush(stdout);

    /* Read back word 2 to verify write took effect */
    BYTE rb[2]={0,0};
    DWORD rbr=do_ctrl(wdapi,g_hDev,0xC0,0x90,0,2,rb,2);
    WORD rbv=(WORD)(rb[0]|(rb[1]<<8));
    printf("Read-back word[2] = 0x%04X (%s) result=0x%lX\n",rbv,rbv==0x6001?"CORRECT":"WRONG-still old",rbr); fflush(stdout);

    /* Write checksum at word 63 - device will reboot after this */
    printf("Writing checksum 0x%04X to word 63...\n",chk); fflush(stdout);
    DWORD w3=do_ctrl(wdapi,g_hDev,0x40,0x91,chk,63,NULL,0);
    printf("CHK write [63]=0x%04X: %s (0x%lX)\n",chk,w3==0?"OK":"FAIL",w3); fflush(stdout);

    if(w1==0&&w2==0&&w3==0){
        printf("\nAll writes OK!\n");
        printf(">>> Disconnect and reconnect the TTL adapter now <<<\n");
        printf("Windows should install FTDI VCP driver and show COM port.\n");
    } else {
        printf("\nSome writes FAILED. Check WinDriver setup.\n");
    }

    typedef DWORD(__cdecl*FN_UNINIT)(void*);
    FN_UNINIT wdu_uninit=(FN_UNINIT)GetProcAddress(wdapi,"WDU_Uninit");
    if(wdu_uninit) wdu_uninit(hDrv);
    FreeLibrary(wdapi);
    return (w1||w2||w3)?1:0;
}
