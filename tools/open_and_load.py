"""open_and_load.py - Open OLC project in WinOLS then trigger Load"""
import ctypes, ctypes.wintypes as wt, time, sys, subprocess

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
OLC_FILE = r"C:\Users\Nates\WinOLS_Bridge\olc\rr27C512.olc"

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
        if area >= min_area: wins.append((h,tb.value,cl.value,area))
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return sorted(wins, key=lambda x: x[3], reverse=True)

def find_child(parent, cls_f=None, txt_f=None):
    found=[None]
    def cb(h,l):
        tb=ctypes.create_unicode_buffer(256); cl=ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(h,tb,256); user32.GetClassNameW(h,cl,64)
        ok=True
        if cls_f and cls_f.lower() not in cl.value.lower(): ok=False
        if txt_f and txt_f.lower() not in tb.value.lower(): ok=False
        if ok: found[0]=h
        return True
    user32.EnumChildWindows(parent, WNDENUMPROC(cb), 0)
    return found[0]

def bclick(h):
    user32.SetForegroundWindow(h); time.sleep(0.15)
    user32.SendMessageW(h, 0x00F5, 0, 0)

pids = get_pids()
if not pids: print("WinOLS not running!"); sys.exit(1)
print(f"PIDs: {pids}")

wins = get_wins(pids, vis=False, min_area=400000)
main_win = wins[0][0] if wins else None
if not main_win: print("No main window!"); sys.exit(1)
print(f"Main: 0x{main_win:08X} '{wins[0][1]}'")

# Open file via Ctrl+O
print("Opening OLC file...")
user32.SetForegroundWindow(main_win); time.sleep(0.5)
user32.keybd_event(0x11, 0, 0, 0)
user32.keybd_event(0x4F, 0, 0, 0)
user32.keybd_event(0x4F, 0, 2, 0)
user32.keybd_event(0x11, 0, 2, 0)
time.sleep(2.5)

# Find open dialog and type path
for h,t,c,a in get_wins(pids, vis=True, min_area=5000):
    if any(x in t.lower() for x in ['open','ffnen','load','laden']):
        print(f"  Open dialog: '{t}'")
        edit = find_child(h, 'edit')
        if edit:
            user32.SetForegroundWindow(edit)
            user32.SendMessageW(edit, 0x000C, 0, OLC_FILE)
            time.sleep(0.3)
            user32.SendMessageW(edit, 0x0100, 0x0D, 0)  # Enter
            print(f"  Typed: {OLC_FILE}")
        break
time.sleep(2)

# Check title changed
wins2 = get_wins(pids, vis=False, min_area=400000)
if wins2:
    print(f"WinOLS title: '{wins2[0][1]}'")

# Now run full_auto for the Load part
print("\nRunning Load automation...")
import importlib.util, os
spec = importlib.util.spec_from_file_location("full_auto",
    os.path.join(os.path.dirname(__file__), "full_auto.py"))
fa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fa)
fa.main()
