"""debug_config.py - Debug what windows appear after Config WM_COMMAND"""
import ctypes, ctypes.wintypes as wt, time, subprocess

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
WM_CMD_CONF = 32827

def get_pids():
    r = subprocess.run(["tasklist","/FI","IMAGENAME eq ols_32on32.exe","/FO","CSV"],
                       capture_output=True, text=True)
    pids = []
    for line in r.stdout.splitlines()[1:]:
        p = line.strip('"').split('","')
        if len(p)>=2:
            try: pids.append(int(p[1]))
            except: pass
    return pids

def get_wins(pids, vis=True, min_area=0):
    wins = []
    def cb(h,l):
        p=wt.DWORD(0); user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value not in pids: return True
        if vis and not user32.IsWindowVisible(h): return True
        tb=ctypes.create_unicode_buffer(256); cl=ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(h,tb,256); user32.GetClassNameW(h,cl,64)
        r2=wt.RECT(); user32.GetWindowRect(h,ctypes.byref(r2))
        area=(r2.right-r2.left)*(r2.bottom-r2.top)
        wins.append((h,tb.value,cl.value,area))
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return sorted(wins, key=lambda x: x[3], reverse=True)

def list_children(parent, depth=0):
    def cb(h,l):
        tb=ctypes.create_unicode_buffer(256); cl=ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(h,tb,256); user32.GetClassNameW(h,cl,64)
        r2=wt.RECT(); user32.GetWindowRect(h,ctypes.byref(r2))
        vis = user32.IsWindowVisible(h)
        print(f"{'  '*depth}  [{cl.value}] '{tb.value}' vis={vis} rect=({r2.left},{r2.top},{r2.right},{r2.bottom})")
        return True
    user32.EnumChildWindows(parent, WNDENUMPROC(cb), 0)

pids = get_pids()
print(f"PIDs: {pids}")

wins = [w for w in get_wins(pids, vis=False, min_area=400000)]
main_win = wins[0][0] if wins else None
print(f"Main: 0x{main_win:08X} '{wins[0][1]}'" if wins else "No main")

print("\nSending WM_COMMAND Config (32827)...")
user32.PostMessageW(main_win, 0x0111, WM_CMD_CONF, 0)

for wait in range(8):
    time.sleep(0.5)
    all_wins = get_wins(pids, vis=True, min_area=0)
    print(f"\n--- t={0.5*(wait+1):.1f}s: {len(all_wins)} visible windows ---")
    for h,t,c,a in all_wins:
        if a < 10000 and a > 0:  # Small dialogs
            print(f"  SMALL: 0x{h:08X} cls={c} title='{t}' area={a}")
            list_children(h)
        elif a > 400000:
            print(f"  MAIN:  0x{h:08X} title='{t}' area={a}")
        else:
            print(f"  DLG:   0x{h:08X} cls={c} title='{t}' area={a}")
            list_children(h)
