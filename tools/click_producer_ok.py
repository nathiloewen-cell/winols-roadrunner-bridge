import ctypes, ctypes.wintypes as wt, subprocess, time
user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

r = subprocess.run(["tasklist","/FI","IMAGENAME eq ols_32on32.exe","/FO","CSV"],capture_output=True,text=True)
pids = []
for l in r.stdout.splitlines()[1:]:
    p = l.strip('"').split('","')
    if len(p)>=2:
        try: pids.append(int(p[1]))
        except: pass

# Find Select producer dialog
wins = []
def cb(h,l):
    p=wt.DWORD(0); user32.GetWindowThreadProcessId(h, ctypes.byref(p))
    if p.value not in pids: return True
    tb=ctypes.create_unicode_buffer(256); user32.GetWindowTextW(h,tb,256)
    if 'select producer' in tb.value.lower() or 'producer' in tb.value.lower():
        wins.append((h,tb.value))
    return True
user32.EnumWindows(WNDENUMPROC(cb), 0)
print("Producer dialogs:", wins)

if not wins:
    print("No Select producer dialog found!")
    exit(1)

dlg = wins[0][0]

# Find children
children = []
def cb2(h,l):
    tb=ctypes.create_unicode_buffer(256); cl=ctypes.create_unicode_buffer(64)
    user32.GetWindowTextW(h,tb,256); user32.GetClassNameW(h,cl,64)
    children.append((h,tb.value,cl.value))
    return True
user32.EnumChildWindows(dlg, WNDENUMPROC(cb2), 0)

print(f"Children ({len(children)}):")
for h,t,c in children:
    print(f"  0x{h:08X} cls={c!r} text={t!r}")

# Try to select 16 Bit in listbox
for h,t,c in children:
    if 'listbox' in c.lower() or 'list' in c.lower():
        count = user32.SendMessageW(h, 0x018B, 0, 0)  # LB_GETCOUNT
        print(f"  Listbox 0x{h:08X}: {count} items")
        for i in range(count):
            buf = ctypes.create_unicode_buffer(100)
            user32.SendMessageW(h, 0x0189, i, ctypes.cast(buf, ctypes.c_long))  # LB_GETTEXT
            print(f"    [{i}] {buf.value!r}")
            if '16' in buf.value:
                print(f"    Selecting item {i}: {buf.value}")
                user32.SendMessageW(h, 0x0186, i, 0)  # LB_SETCURSEL
                time.sleep(0.2)

# Find and click OK button
for h,t,c in children:
    if 'button' in c.lower() and t.strip().upper() == 'OK':
        print(f"Clicking OK (0x{h:08X})")
        user32.SetForegroundWindow(h); time.sleep(0.1)
        user32.SendMessageW(h, 0x00F5, 0, 0)  # BM_CLICK
        print("OK clicked!")
        break
else:
    print("OK button not found in children, trying Enter")
    user32.SetForegroundWindow(dlg)
    time.sleep(0.1)
    ip = (type('INPUT', (ctypes.Structure,), {'_fields_': [('type',wt.DWORD),('wVk',wt.WORD),('wScan',wt.WORD),('dwFlags',wt.DWORD),('time',wt.DWORD),('dwExtraInfo',ctypes.c_ulong)]}))()
    ip.type = 1; ip.wVk = 0x0D
    user32.SendInput(1, ctypes.byref(ip), ctypes.sizeof(ip))
