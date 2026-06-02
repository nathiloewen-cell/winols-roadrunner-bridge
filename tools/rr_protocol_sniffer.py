"""
Sprint 3 Roadrunnerprotokoll - Sniffer/Tester

Phase A: TTL Adapter allein (kein Roadrunner) -> zeigt Timeouts
Phase B: TTL Adapter + Roadrunner verbunden  -> zeigt echte Protokoll-Bytes

Methode: Wir oeffnen COM13 direkt und senden bekannte MoatesWare-Befehle.
Alles wird mit Timestamp und Hex geloggt.
"""
import serial
import time
import sys
import os
sys.stdout.reconfigure(line_buffering=True)

COM_PORT = "COM13"
LOG_FILE = r"C:\dev\winols-roadrunner-bridge\tools\rr_protocol_capture.txt"

BAUD_RATES = [9600, 19200, 38400, 57600, 115200]

def hex_str(data):
    if not data: return "(empty)"
    return " ".join(f"{b:02X}" for b in data) + f"  [{len(data)} bytes]"

def ascii_safe(data):
    return "".join(chr(b) if 32 <= b < 127 else '.' for b in data)

def ts():
    return time.strftime("%H:%M:%S") + f".{int(time.time()*1000)%1000:03d}"

lines = []
def log(msg):
    full = f"[{ts()}] {msg}"
    print(full)
    lines.append(full)

def send_recv(ser, data, timeout_ms=500, label=""):
    ser.reset_input_buffer()
    ser.write(data)
    ser.flush()
    log(f"  SEND {label}: {hex_str(data)}")
    time.sleep(timeout_ms / 1000.0)
    resp = ser.read(ser.in_waiting or 1)
    if resp:
        log(f"  RECV: {hex_str(resp)} | ASCII: {ascii_safe(resp)}")
    else:
        log(f"  RECV: (timeout - keine Antwort)")
    return resp

def test_baud(baud, phase):
    log(f"\n{'='*60}")
    log(f"Teste {baud} Baud - {phase}")
    log(f"{'='*60}")
    try:
        ser = serial.Serial(COM_PORT, baud, timeout=0.5,
                           bytesize=8, parity='N', stopbits=1,
                           xonxoff=False, rtscts=False, dsrdtr=False)
        ser.dtr = True
        ser.rts = True
        time.sleep(0.1)
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        # --- Test 1: Version request ('V') ---
        log(f"\n[1] CMD_GET_VERSION = 0x56 ('V')")
        r1 = send_recv(ser, bytes([0x56]), 500, "CMD_GET_VERSION")

        # --- Test 2: Get Emulation Mode ('m') ---
        log(f"\n[2] CMD_GET_EMU_MODE = 0x6D ('m')")
        r2 = send_recv(ser, bytes([0x6D]), 500, "CMD_GET_EMU_MODE")

        # --- Test 3: BulkRead header ---
        # CMD_BULK_READ [addr_hi][addr_lo][size_hi][size_lo]
        log(f"\n[3] CMD_BULK_READ 0x52 ('R') addr=0x0000 size=0x0100")
        r3 = send_recv(ser, bytes([0x52, 0x00, 0x00, 0x01, 0x00]), 1000, "CMD_BULK_READ")

        # --- Test 4: Single byte 'S' (SetUSBBaud) ---
        log(f"\n[4] CMD_SET_BAUD = 0x53 ('S') + speed bytes")
        # Try with 115200 = 0x0001C200 big-endian
        r4 = send_recv(ser, bytes([0x53, 0x00, 0x01, 0xC2, 0x00, 0x00]), 500, "CMD_SET_BAUD 115200")

        # --- Test 5: Raw ping with common init bytes ---
        log(f"\n[5] Raw 0xAA probe (common sync byte)")
        r5 = send_recv(ser, bytes([0xAA]), 500, "probe 0xAA")

        # --- Test 6: 0x00 null probe ---
        log(f"\n[6] Null byte probe")
        r6 = send_recv(ser, bytes([0x00]), 300, "probe 0x00")

        # --- Test 7: BulkWrite header (no data) ---
        log(f"\n[7] CMD_BULK_WRITE 0x57 ('W') header only")
        r7 = send_recv(ser, bytes([0x57, 0x00, 0x00, 0x01, 0x00]), 500, "CMD_BULK_WRITE header")

        # --- Test 8: Alternate command bytes ---
        for cmd_byte in [0x01, 0x02, 0x03, 0x10, 0x20, 0x30, 0x41, 0x42, 0x43]:
            r = send_recv(ser, bytes([cmd_byte]), 200, f"probe 0x{cmd_byte:02X}")
            if r and len(r) > 0 and r != bytes([0x00]*len(r)):
                log(f"  *** RESPONSE to 0x{cmd_byte:02X}! ***")
                break

        ser.close()
        log(f"\nPort geschlossen.")

    except serial.SerialException as e:
        log(f"FEHLER beim Oeffnen {COM_PORT}: {e}")
    except Exception as e:
        log(f"FEHLER: {e}")

def main():
    log(f"Sprint 3 Roadrunnerprotokoll Capture")
    log(f"Port: {COM_PORT}")
    log(f"Datei: {LOG_FILE}")
    log("")

    # Detect phase from user input or argument
    if len(sys.argv) > 1 and sys.argv[1] == "B":
        phase = "PHASE B - Roadrunner VERBUNDEN"
    else:
        phase = "PHASE A - Nur TTL Adapter (kein Roadrunner)"

    log(f"*** {phase} ***")
    log("")

    # Test primary baud rates
    for baud in [9600, 115200]:
        test_baud(baud, phase)
        time.sleep(0.5)

    # Write log file
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    log(f"\nLog gespeichert: {LOG_FILE}")

    if "Phase A" in phase or "PHASE A" in phase:
        print("\n" + "="*60)
        print("Phase A abgeschlossen.")
        print("Schliesse jetzt den Roadrunner an den TTL Adapter an,")
        print("dann starte: python rr_protocol_sniffer.py B")
        print("="*60)

if __name__ == "__main__":
    main()
