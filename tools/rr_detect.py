"""Roadrunner Erkennung - Systematischer Test mit DTR-Reset und Bootzeit"""
import sys, time
sys.stdout.reconfigure(line_buffering=True)

try:
    import serial
except ImportError:
    print("pip install pyserial"); sys.exit(1)

COM = "COM13"

def hex_s(d): return " ".join(f"{b:02X}" for b in d) if d else "(leer)"
def ts(): return f"{time.strftime('%H:%M:%S')}.{int(time.time()*1000)%1000:03d}"
def log(m): print(f"[{ts()}] {m}")

def test(baud, dtr_toggle=False, boot_wait=0, init_bytes=None, label=""):
    log(f"\n--- {baud} Baud | DTR-toggle={dtr_toggle} | wait={boot_wait}s | {label}")
    try:
        # Open with DTR=False initially (Roadrunner might reset on DTR low)
        s = serial.Serial(COM, baud, timeout=1.5, bytesize=8, parity='N',
                         stopbits=1, xonxoff=False, rtscts=False, dsrdtr=False)

        if dtr_toggle:
            log("  DTR LOW (reset Roadrunner)...")
            s.dtr = False; s.rts = False
            time.sleep(0.2)
            log("  DTR HIGH (release reset)...")
            s.dtr = True; s.rts = True
        else:
            s.dtr = True; s.rts = True

        if boot_wait > 0:
            log(f"  Warte {boot_wait}s auf Bootup...")
            time.sleep(boot_wait)

        s.reset_input_buffer()

        # Check for unsolicited bytes (Roadrunner might send version on boot)
        time.sleep(0.3)
        if s.in_waiting:
            d = s.read(s.in_waiting)
            log(f"  UNSOLICITED RX: {hex_s(d)} = '{d.decode('ascii','replace')}'")

        # Try init bytes first if specified
        if init_bytes:
            s.write(bytes(init_bytes))
            s.flush()
            log(f"  INIT TX: {hex_s(bytes(init_bytes))}")
            time.sleep(0.5)
            if s.in_waiting:
                d = s.read(s.in_waiting)
                log(f"  INIT RX: {hex_s(d)} = '{d.decode('ascii','replace')}'")

        # Try known commands
        cmds = [
            ([0x56], "CMD_GET_VERSION 'V'"),
            ([0x76], "version lowercase 'v'"),
            ([0x00], "NULL byte"),
            ([0xFF], "0xFF"),
            ([0x7F], "0x7F DEL"),
            ([0x41], "'A' passthrough?"),
            ([0x6D], "CMD_GET_EMU_MODE 'm'"),
        ]

        for cmd_bytes, cmd_name in cmds:
            s.reset_input_buffer()
            s.write(bytes(cmd_bytes))
            s.flush()
            time.sleep(0.8)
            resp = s.read(max(s.in_waiting, 1))
            if resp:
                log(f"  *** ANTWORT auf {cmd_name}: {hex_s(resp)} = '{resp.decode('ascii','replace')}' ***")
                return True, baud, cmd_bytes, resp
            else:
                log(f"  {cmd_name}: timeout")

        s.close()
        return False, baud, None, None
    except Exception as e:
        log(f"  FEHLER: {e}")
        return False, baud, None, None

def main():
    log("Roadrunner Erkennung - Systematischer Test")
    log(f"Roadrunner v12.15.R auf {COM} erwartet")

    tests = [
        # (baud, dtr_toggle, boot_wait, init_bytes, label)
        (9600,   True,  2.0, None,   "DTR-Reset + 2s Bootzeit"),
        (9600,   True,  1.0, None,   "DTR-Reset + 1s"),
        (9600,   False, 0.5, None,   "Normal 9600"),
        (9600,   True,  2.0, [0x00], "DTR-Reset + NULL init"),
        (115200, True,  2.0, None,   "DTR-Reset 115200"),
        (115200, False, 0.5, None,   "Normal 115200"),
        (57600,  True,  2.0, None,   "DTR-Reset 57600"),
        (57600,  False, 0.5, None,   "Normal 57600"),
        (19200,  True,  2.0, None,   "DTR-Reset 19200"),
    ]

    found = False
    for baud, dtr, wait, init, label in tests:
        ok, b, cmd, resp = test(baud, dtr, wait, init, label)
        if ok:
            log(f"\n*** PROTOKOLL GEFUNDEN! Baud={b} Cmd={hex_s(bytes(cmd))} ***")
            found = True
            break
        time.sleep(0.3)

    if not found:
        log("\n*** Keine Antwort bei allen Tests ***")
        log("Moegliche Ursachen:")
        log("1. TX/RX Leitungen vertauscht (RX->RX statt RX->TX)?")
        log("2. Roadrunner ist ausgeschaltet?")
        log("3. Roadrunner braucht anderes Protokoll?")
        log("Empfehlung: EmUtility mit Portmon gleichzeitig ausfuehren")

if __name__ == "__main__":
    main()
