"""
Phase 1 Lern-Modus.
Beobachtet deine Mausklicks bei WinOLS-Dialogen und merkt sich was du klickst.
Beim naechsten Durchlauf werden diese Klicks automatisch wiederholt.

Modi:
  --learn  : Aufzeichnung (du klickst, Skript lernt)
  --run    : Automatischer Ablauf (Skript klickt was du gelernt hast)
  --test   : Einen Test-Wert setzen und Ergebnis messen
"""
import sys, os, time, json, subprocess, ctypes, ctypes.wintypes
import threading
from pathlib import Path

RESP_FILE = os.path.join(os.environ.get("TEMP","C:\\Temp"), "ols300_2030_resp.bin")
LOG    = r"C:\Users\Nates\AppData\Local\Temp\winols_wdapi.log"
LEARN_FILE = r"C:\dev\winols-roadrunner-bridge\tools\phase1_clicks.json"
RESULTS    = r"C:\dev\winols-roadrunner-bridge\tools\phase1_results.json"
WINOLS     = r"C:\Users\Nates\WinOLS_Bridge\ols_32on32.exe"

user32   = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# ── Klick-Aufzeichnung ────────────────────────────────────────────────────────

clicks_recorded = []
recording = False

WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))

class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", ctypes.wintypes.POINT),
        ("mouseData", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

def get_window_at(x, y):
    """Get window title + button text under cursor."""
    import win32gui
    hw = user32.WindowFromPoint(ctypes.wintypes.POINT(x, y))
    if not hw: return None, None
    # Walk up to find dialog
    parent = win32gui.GetParent(hw) or hw
    dialog_title = win32gui.GetWindowText(parent) or win32gui.GetWindowText(hw)
    btn_text = win32gui.GetWindowText(hw)
    return dialog_title, btn_text

def mouse_hook_proc(nCode, wParam, lParam):
    global recording, clicks_recorded
    if nCode >= 0 and wParam == WM_LBUTTONDOWN and recording:
        ms = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
        x, y = ms.pt.x, ms.pt.y
        try:
            dialog, btn = get_window_at(x, y)
            if dialog and ("WinOLS" in dialog or btn):
                click = {"dialog": dialog, "btn": btn, "x": x, "y": y}
                clicks_recorded.append(click)
                print(f"  [LERNEN] Dialog='{dialog}' Btn='{btn}' @ ({x},{y})")
        except: pass
    return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

def start_recording():
    global recording, clicks_recorded
    recording = True
    clicks_recorded = []
    print("  [AUFZEICHNUNG AKTIV] - Klicke auf WinOLS-Fenster...")
    hook_proc = HOOKPROC(mouse_hook_proc)
    hook = user32.SetWindowsHookExW(WH_MOUSE_LL, hook_proc, None, 0)
    msg = ctypes.wintypes.MSG()
    return hook, hook_proc, msg

def stop_recording(hook, msg):
    global recording
    recording = False
    user32.UnhookWindowsHookEx(hook)
    return clicks_recorded.copy()

# ── Klick-Wiedergabe ─────────────────────────────────────────────────────────

def replay_click(click):
    """Replay a recorded click."""
    import win32gui, win32con
    dialog_name = click.get("dialog","")
    btn_name    = click.get("btn","")
    x, y        = click.get("x",0), click.get("y",0)

    # Try to find button by name first
    found = False
    def find_dlg(h, _):
        nonlocal found
        if not win32gui.IsWindowVisible(h): return
        t = win32gui.GetWindowText(h)
        if dialog_name in t or t in dialog_name:
            def find_btn(bh, _):
                nonlocal found
                bt = win32gui.GetWindowText(bh)
                if btn_name and btn_name in bt or bt in btn_name:
                    win32gui.SetForegroundWindow(h)
                    win32gui.PostMessage(bh, win32con.WM_LBUTTONDOWN, 0, 0)
                    win32gui.PostMessage(bh, win32con.WM_LBUTTONUP, 0, 0)
                    found = True
                    print(f"  [REPLAY] '{bt}' in '{t}'")
            try: win32gui.EnumChildWindows(h, find_btn, None)
            except: pass
    win32gui.EnumWindows(find_dlg, None)

    # Fallback: click by coordinates
    if not found and x and y:
        user32.SetCursorPos(x, y)
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
        user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
        print(f"  [REPLAY coord] @ ({x},{y}) for '{dialog_name}'")
    time.sleep(0.5)

# ── Lern-Sequenz aufzeichnen ─────────────────────────────────────────────────

def learn_sequence():
    """Record a full startup+test sequence."""
    print("=" * 60)
    print("LERN-MODUS")
    print("=" * 60)
    print()
    print("Ich zeichne deine Klicks auf waehrend du WinOLS bedienst.")
    print("Starte WinOLS, klicke alle Dialoge durch und mache dann")
    print("den Config-Test (Hardware -> OK oder Load).")
    print()
    input("Druecke ENTER um die Aufzeichnung zu starten...")

    hook, hook_proc, msg = start_recording()

    print("Aufzeichnung laeuft. Bediene WinOLS jetzt.")
    print("Druecke ENTER wenn du fertig bist...")

    # Run message loop in background thread
    stop_event = threading.Event()
    def msg_loop():
        while not stop_event.is_set():
            user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)
            time.sleep(0.01)
    t = threading.Thread(target=msg_loop, daemon=True)
    t.start()

    input()
    stop_event.set()
    recorded = stop_recording(hook, msg)

    print(f"\n{len(recorded)} Klicks aufgezeichnet:")
    for i, c in enumerate(recorded):
        print(f"  {i+1}. Dialog='{c['dialog']}'  Btn='{c['btn']}'  @ ({c['x']},{c['y']})")

    # Separate startup clicks from test click
    print()
    idx = input("Ab welchem Klick beginnt der eigentliche Test (20 30 Trigger)? [Nummer, z.B. 5]: ").strip()
    try:
        split = int(idx) - 1
    except:
        split = len(recorded) - 1

    startup_clicks = recorded[:split]
    test_clicks    = recorded[split:]

    data = {
        "startup_clicks": startup_clicks,
        "test_clicks":    test_clicks,
        "full_sequence":  recorded
    }
    with open(LEARN_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"\nGespeichert: {LEARN_FILE}")
    print(f"  Startup-Klicks:  {len(startup_clicks)}")
    print(f"  Test-Klicks:     {len(test_clicks)}")
    return data

# ── Automatischer Ablauf ─────────────────────────────────────────────────────

def load_clicks():
    try:
        with open(LEARN_FILE) as f: return json.load(f)
    except:
        print(f"Keine gelernten Klicks! Erst --learn ausfuehren.")
        return None

def get_cpu():
    r = subprocess.run(["wmic","process","where","name='ols_32on32.exe'",
                        "get","KernelModeTime,UserModeTime"],
                       capture_output=True, text=True, timeout=5)
    total = 0
    for line in r.stdout.strip().split('\n')[1:]:
        parts = line.strip().split()
        if len(parts)==2:
            try: total += int(parts[0])+int(parts[1])
            except: pass
    return total/10000000.0

def get_log_size():
    try: return os.path.getsize(LOG)
    except: return 0

def check_2030(log_before):
    try:
        with open(LOG,'r',errors='replace') as f: c=f.read()
        return "EP2 IN 8b (20 30) FUZZER:" in c[log_before:]
    except: return False

def write_resp(resp):
    with open(RESP_FILE,'wb') as f: f.write(bytes(resp))

def graceful_kill():
    import win32gui, win32con
    wins=[]
    def cb(h,_):
        t=win32gui.GetWindowText(h)
        c=win32gui.GetClassName(h)
        if "WinOLS" in t and "Afx" in c: wins.append(h)
    win32gui.EnumWindows(cb,None)
    for h in wins: win32gui.PostMessage(h, win32con.WM_CLOSE,0,0)
    time.sleep(2)
    subprocess.run(["taskkill","/F","/IM","ols_32on32.exe"],capture_output=True)
    time.sleep(1)

def run_test(resp_bytes, clicks_data):
    """Run one test with given response bytes."""
    resp_hex = ' '.join(f'{b:02X}' for b in resp_bytes)
    print(f"\n  Testing: [{resp_hex}]")
    write_resp(resp_bytes)

    # Start WinOLS
    subprocess.Popen([WINOLS])

    # Replay startup clicks
    for i, click in enumerate(clicks_data.get("startup_clicks",[])):
        time.sleep(1.5)
        replay_click(click)

    # Wait a bit more for WinOLS to settle
    time.sleep(5)

    # Measure before test
    log_before = get_log_size()
    cpu_before = get_cpu()

    # Replay test clicks (triggers 20 30)
    for click in clicks_data.get("test_clicks",[]):
        time.sleep(0.8)
        replay_click(click)

    # Wait and measure
    time.sleep(8)
    cpu_after = get_cpu()
    cpu_delta = (cpu_after - cpu_before) / 8.0
    got_2030 = check_2030(log_before)
    no_hang  = cpu_delta < 0.35

    result = {
        "resp": resp_hex,
        "resp_bytes": list(resp_bytes),
        "cpu_per_sec": round(cpu_delta, 2),
        "no_hang": no_hang,
        "got_2030": got_2030,
        "success": no_hang and got_2030,
    }
    print(f"  CPU/s={cpu_delta:.2f} no_hang={no_hang} got_2030={got_2030}")

    graceful_kill()
    return result

def run_fuzzer():
    clicks_data = load_clicks()
    if not clicks_data: return

    # Test candidates
    candidates = []
    for b0 in [0x00,0x01,0x02,0x03,0x04,0x05,0x06,0x07,0x08,
               0x0A,0x0F,0x10,0x14,0x20,0x40,0x42,0x55,0x80,0xFF]:
        candidates.append([b0,0,0,0,0,0,0,0])
    candidates += [
        [0x01,0x01,0,0,0,0,0,0],[0x01,0x02,0,0,0,0,0,0],
        [0x02,0x01,0,0,0,0,0,0],[0x04,0x01,0,0,0,0,0,0],
        [0x52,0x01,0x04,0x55,0x01,0x01,0x0F,0xBD],
    ]

    data = {"results":[],"successes":[]}
    try:
        with open(RESULTS) as f: data = json.load(f)
    except: pass
    tested = {r['resp'] for r in data['results'] if isinstance(r['resp'],str)}

    print(f"\n{len(candidates)} Tests geplant, {len(tested)} bereits getestet")

    for resp in candidates:
        resp_hex = ' '.join(f'{b:02X}' for b in resp)
        if resp_hex in tested:
            print(f"  Skip: [{resp_hex}]")
            continue

        result = run_test(resp, clicks_data)
        data['results'].append(result)
        if result['success'] or (result['no_hang'] and result['got_2030']):
            data['successes'].append(result)
            print(f"  *** KANDIDAT: [{resp_hex}] ***")

        with open(RESULTS,'w') as f: json.dump(data,f,indent=2)

    print(f"\nFertig. {len(data['successes'])} Erfolge.")
    for s in data['successes']:
        print(f"  [{s['resp']}] cpu={s['cpu_per_sec']}")

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv)>1 else "--learn"
    if mode == "--learn":
        learn_sequence()
        print("\nJetzt mit --run starten fuer automatische Tests.")
    elif mode == "--run":
        run_fuzzer()
    else:
        print("Usage: python phase1_learn.py [--learn|--run]")
