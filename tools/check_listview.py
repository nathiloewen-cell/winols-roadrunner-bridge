import ctypes, ctypes.wintypes as wt
user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
dlg = 0x00530C60
kids = []
def cb(h,l):
    tb=ctypes.create_unicode_buffer(64); cl=ctypes.create_unicode_buffer(64)
    user32.GetWindowTextW(h,tb,64); user32.GetClassNameW(h,cl,64)
    kids.append((h,tb.value,cl.value))
    return True
user32.EnumChildWindows(dlg, WNDENUMPROC(cb), 0)
for h,t,c in kids:
    # Try LVM_GETITEMCOUNT for all controls
    cnt = user32.SendMessageW(h, 0x1004, 0, 0)
    en = user32.IsWindowEnabled(h)
    print(f"0x{h:08X} cls={c!r} text={t!r} lvm_count={cnt} enabled={en}")
