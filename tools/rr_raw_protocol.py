"""Sprint 3 Roadrunnerprotokoll - Raw Byte Capture auf COM13"""
import sys, time, os
sys.stdout.reconfigure(line_buffering=True)

COM_PORT = "COM13"
OUTPUT = r"C:\dev\winols-roadrunner-bridge\tools\rr_protocol_capture.txt"

lines = []
def log(msg):
    t = time.strftime("%H:%M:%S.") + f"{int(time.time()*1000)%1000:03d}"
    full = f"[{t}] {msg}"
    print(full)
    lines.append(full)

def hex_dump(label, data):
    if not data:
        log(f"  {label}: (leer)")
        return
    h = " ".join(f"{b:02X}" for b in data)
    a = "".join(chr(b) if 32<=b<127 else '.' for b in data)
    log(f"  {label} [{len(data)}B]: {h}  |{a}|")

def transact(ser, send_bytes, wait_ms=500, label=""):
    import serial
    ser.reset_input_buffer()
    ser.write(bytes(send_bytes))
    ser.flush()
    hex_dump(f"TX {label}", bytes(send_bytes))
    time.sleep(wait_ms/1000)
    resp = ser.read(max(ser.in_waiting, 1))
    if resp:
        hex_dump(f"RX {label}", resp)
    else:
        log(f"  RX {label}: TIMEOUT (keine Antwort)")
    return resp

def try_baud(baud):
    import serial
    log(f"\n{'='*55}")
    log(f"BAUD {baud}")
    log(f"{'='*55}")
    try:
        ser = serial.Serial(COM_PORT, baud, timeout=0.8,
                           bytesize=8, parity='N', stopbits=1)
        ser.dtr = True
        ser.rts = True
        time.sleep(0.15)
        ser.reset_input_buffer()

        # 1. Version request (CMD_GET_VERSION = 'V' = 0x56)
        log("\n[A] CMD_GET_VERSION 0x56")
        r = transact(ser, [0x56], 600, "GET_VERSION")
        if r and len(r) > 0:
            log(f"  *** ANTWORT bei {baud} Baud! Version-Cmd erfolgreich ***")

        # 2. Emulation mode (CMD_GET_EMU_MODE = 'm' = 0x6D)
        log("\n[B] CMD_GET_EMU_MODE 0x6D")
        r2 = transact(ser, [0x6D], 400, "GET_EMU_MODE")

        # 3. BulkRead request: R + addr(2B) + size(2B)
        log("\n[C] CMD_BULK_READ 0x52 addr=0x0000 size=0x0100")
        r3 = transact(ser, [0x52, 0x00, 0x00, 0x01, 0x00], 800, "BULK_READ hdr")
        if r3 and len(r3) >= 256:
            log(f"  *** BULK_READ erfolgreich! {len(r3)} bytes empfangen ***")
            hex_dump("  Erste 16B", r3[:16])

        # 4. SetUSBBaud ('S' = 0x53) + speed = 115200 big-endian
        log("\n[D] CMD_SET_BAUD 0x53 -> 115200")
        r4 = transact(ser, [0x53, 0x00, 0x01, 0xC2, 0x00], 500, "SET_BAUD")

        # 5. Probe with ACK byte
        log("\n[E] ACK-Probe 0x06")
        r5 = transact(ser, [0x06], 300, "ACK-probe")

        # 6. BulkWrite header test: W + addr + size (no data)
        log("\n[F] CMD_BULK_WRITE 0x57 header addr=0x0000 size=0x0100")
        r6 = transact(ser, [0x57, 0x00, 0x00, 0x01, 0x00], 500, "BULK_WRITE hdr")

        # 7. Alternate read commands
        for cmd in [0x52, 0x43, 0x41, 0x72]:
            log(f"\n[G] probe 0x{cmd:02X} ('{chr(cmd) if 32<=cmd<127 else '?'}')")
            transact(ser, [cmd, 0x00, 0x00, 0x01, 0x00], 400, f"probe-{cmd:02X}")

        ser.close()
    except Exception as e:
        log(f"  FEHLER: {e}")

def main():
    try:
        import serial
    except ImportError:
        log("FEHLER: pyserial nicht installiert.")
        log("Installiere: pip install pyserial")
        return

    log("Sprint 3 Roadrunnerprotokoll - Raw Capture")
    log(f"Port: {COM_PORT}")
    log(f"Roadrunner v12.15.R erwartet (aus Phase B)")
    log("")

    # Test at most likely baud rates first
    for baud in [9600, 115200, 57600, 19200]:
        try_baud(baud)
        time.sleep(0.3)

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    log(f"\nLog: {OUTPUT}")

if __name__ == "__main__":
    main()
