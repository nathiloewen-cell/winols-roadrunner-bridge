"""
Klick-Recorder fuer Phase 1.
Startet SOFORT mit der Aufzeichnung. Beendet nach 60 Sekunden Inaktivitaet
oder wenn du Ctrl+C drueckst.

Aufgezeichnet werden: WinOLS-Dialoge + Buttons die du klickst.
Danach kannst du mit phase1_run.py automatisch testen.
"""
import ctypes, ctypes.wintypes, time, json, threading, sys, os

LEARN_FILE = r"C:\dev\winols-roadrunner-bridge\tools\phase1_clicks.json"

user32 = ctypes.windll.user32

WH_MOUSE_LL  = 14
WM_LBUTTONDOWN = 0x0201

class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt",          ctypes.wintypes.POINT),
        ("mouseData",   ctypes.c_ulong),
        ("flags",       ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

recorded = []
last_click_time = [time.time()]

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_uint,
                               ctypes.POINTER(ctypes.c_void_p))

def get_info_at(x, y):
    try:
        import win32gui
        hw = user32.WindowFromPoint(ctypes.wintypes.POINT(x, y))
        if not hw: return "", ""
        parent = win32gui.GetParent(hw) or hw
        dtitle = win32gui.GetWindowText(parent)
        if not dtitle: dtitle = win32gui.GetWindowText(hw)
        btn    = win32gui.GetWindowText(hw)
        return dtitle, btn
    except:
        return "", ""

def hook_proc(nCode, wParam, lParam):
    if nCode >= 0 and wParam == WM_LBUTTONDOWN:
        ms = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
        x, y = ms.pt.x, ms.pt.y
        dialog, btn = get_info_at(x, y)
        if dialog or btn:
            entry = {
                "time":   round(time.time(), 2),
                "dialog": dialog,
                "btn":    btn,
                "x":      x,
                "y":      y
            }
            recorded.append(entry)
            last_click_time[0] = time.time()
            print(f"  [{len(recorded):3d}] {dialog!r:40s}  btn={btn!r}")
    return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

HOOK_PROC_REF = HOOKPROC(hook_proc)

print("=" * 60)
print("KLICK-RECORDER gestartet")
print("=" * 60)
print("Aufzeichnung laeuft sofort.")
print("Bediene WinOLS normal (alle Dialoge + Config-Test).")
print("Beendet automatisch nach 30s Inaktivitaet.")
print("Oder Ctrl+C zum manuellen Beenden.")
print()

hook = user32.SetWindowsHookExW(WH_MOUSE_LL, HOOK_PROC_REF, None, 0)
if not hook:
    print("ERROR: Hook konnte nicht gesetzt werden!")
    sys.exit(1)

msg = ctypes.wintypes.MSG()
stop = threading.Event()

def message_loop():
    while not stop.is_set():
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)
        time.sleep(0.01)

t = threading.Thread(target=message_loop, daemon=True)
t.start()

try:
    while True:
        time.sleep(1)
        idle = time.time() - last_click_time[0]
        if idle > 30 and recorded:
            print(f"\n30s Inaktivitaet erkannt — beende Aufzeichnung.")
            break
        if idle > 5 and not recorded:
            pass  # wait for first click
except KeyboardInterrupt:
    print("\nCtrl+C erkannt.")

stop.set()
user32.UnhookWindowsHookEx(hook)

print(f"\n{len(recorded)} Klicks aufgezeichnet:")
for i, c in enumerate(recorded):
    dt = ""
    if i > 0: dt = f"+{c['time']-recorded[i-1]['time']:.1f}s"
    print(f"  [{i+1:2d}] {dt:8s}  '{c['dialog'][:35]}'  btn='{c['btn']}'")

# Ask which click is the "test" click (triggers 20 30)
print()
try:
    raw = input("Ab welchem Klick ist der eigentliche Test? [ENTER = letzter]: ").strip()
    split = int(raw)-1 if raw else len(recorded)-1
except:
    split = len(recorded)-1

data = {
    "startup_clicks": recorded[:split],
    "test_clicks":    recorded[split:],
    "full":           recorded
}

with open(LEARN_FILE,'w') as f:
    json.dump(data, f, indent=2)

print(f"\nGespeichert: {LEARN_FILE}")
print(f"  Startup: {len(data['startup_clicks'])} Klicks")
print(f"  Test:    {len(data['test_clicks'])} Klicks")
print()
print("Jetzt: python phase1_run.py")
