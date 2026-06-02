"""
Phase 1 Manueller Tester.
Du startest WinOLS, drückst Config OK (oder Load).
Dieses Script:
1. Schreibt den naechsten Test-Wert in die Config-Datei
2. Wartet auf ENTER von dir
3. Misst CPU 8 Sekunden nach deinem Klick
4. Zeigt das Ergebnis
5. Bereitet naechsten Test vor
"""
import os, time, json, subprocess, struct, sys

RESP_FILE = os.path.join(os.environ.get("TEMP","C:\\Temp"), "ols300_2030_resp.bin")
LOG = r"C:\Users\Nates\AppData\Local\Temp\winols_wdapi.log"
RESULTS = r"C:\dev\winols-roadrunner-bridge\tools\phase1_results.json"

def get_log_size():
    try: return os.path.getsize(LOG)
    except: return 0

def get_cpu():
    r = subprocess.run(
        ["wmic","process","where","name='ols_32on32.exe'","get","KernelModeTime,UserModeTime"],
        capture_output=True, text=True, timeout=5)
    total = 0
    for line in r.stdout.strip().split('\n')[1:]:
        parts = line.strip().split()
        if len(parts)==2:
            try: total += int(parts[0])+int(parts[1])
            except: pass
    return total/10000000.0

def check_2030(log_before):
    try:
        with open(LOG,'r',errors='replace') as f: c=f.read()
        return "EP2 IN 8b (20 30) FUZZER:" in c[log_before:]
    except: return False

def write_resp(resp):
    with open(RESP_FILE,'wb') as f: f.write(bytes(resp))

def load_results():
    try:
        with open(RESULTS) as f: return json.load(f)
    except: return {"results":[],"successes":[]}

def save_results(data):
    with open(RESULTS,'w') as f: json.dump(data,f,indent=2)

# Test candidates
CANDIDATES = []
# byte[0] sweep
for b0 in [0x00,0x01,0x02,0x03,0x04,0x05,0x06,0x07,0x08,
           0x0A,0x0C,0x0F,0x10,0x14,0x18,0x1C,0x20,
           0x40,0x42,0x44,0x48,0x4F,0x55,0x80,0xAA,0xFF]:
    CANDIDATES.append([b0,0,0,0,0,0,0,0])
# Special patterns
CANDIDATES += [
    [0x01,0x01,0,0,0,0,0,0],
    [0x01,0x02,0,0,0,0,0,0],
    [0x01,0x04,0,0,0,0,0,0],
    [0x01,0x08,0,0,0,0,0,0],
    [0x01,0x10,0,0,0,0,0,0],
    [0x01,0x40,0,0,0,0,0,0],
    [0x01,0xFF,0,0,0,0,0,0],
    [0x02,0x01,0,0,0,0,0,0],
    [0x04,0x01,0,0,0,0,0,0],
    [0x52,0x01,0x04,0x55,0x01,0x01,0x0F,0xBD],  # UART init response
    [0x01,0x00,0x08,0,0,0,0,0],
    [0x01,0x00,0x01,0,0,0,0,0],
    [0x01,0x00,0,0,0x01,0,0,0],
]

def main():
    data = load_results()
    tested = {r['resp'] if isinstance(r['resp'], str) else ' '.join(f'{b:02X}' for b in r['resp'])
              for r in data['results']}

    print("=" * 60)
    print("Phase 1 Manueller Tester")
    print("=" * 60)
    print(f"Bisher getestet: {len(data['results'])} Werte")
    print(f"Erfolge: {len(data['successes'])}")
    print()
    print("Anleitung:")
    print("1. Starte WinOLS (aus WinOLS_Bridge Ordner)")
    print("2. Warte bis Load-Button aktiv ist")
    print("3. Druecke ENTER hier wenn bereit")
    print("4. Klicke SOFORT auf: Hardware -> OK  ODER  Load")
    print("5. Warte 8 Sekunden (nicht klicken)")
    print("6. Ergebnis wird automatisch gespeichert")
    print()

    for resp in CANDIDATES:
        resp_hex = ' '.join(f'{b:02X}' for b in resp)
        if resp_hex in tested:
            print(f"  Ueberspringe (bereits getestet): [{resp_hex}]")
            continue

        write_resp(resp)
        print(f"\n{'='*60}")
        print(f"Naechster Test: [{resp_hex}]")
        print(f"Response-Datei geschrieben: {RESP_FILE}")
        print()
        print("  >> Starte WinOLS neu (oder lass ihn laufen)")
        print(f"  >> Druecke ENTER wenn WinOLS bereit ist")

        inp = input("  ENTER = bereit | 'skip' = ueberspringen | 'quit' = beenden: ").strip().lower()
        if inp == 'quit': break
        if inp == 'skip':
            print("  Uebersprungen.")
            continue

        # Record state before click
        log_before = get_log_size()
        cpu_before = get_cpu()
        print()
        print("  >> JETZT KLICKEN: Miscellaneous -> Config -> Hardware -> OK")
        print("  >>  ODER: Load Button")
        print()
        print("  Warte 8 Sekunden...")

        # Wait 8 seconds
        for s in range(8, 0, -1):
            print(f"  {s}...", end='\r', flush=True)
            time.sleep(1)
        print("  Messe...")

        # Measure
        cpu_after = get_cpu()
        cpu_delta = (cpu_after - cpu_before) / 8.0
        got_2030 = check_2030(log_before)

        # Check if WinOLS still running
        r2 = subprocess.run(["tasklist","/FI","IMAGENAME eq ols_32on32.exe"],
                            capture_output=True, text=True)
        running = "ols_32on32.exe" in r2.stdout

        no_hang = cpu_delta < 0.35

        result = {
            "resp": resp_hex,
            "resp_bytes": resp,
            "cpu_per_sec": round(cpu_delta, 2),
            "no_hang": no_hang,
            "got_2030": got_2030,
            "still_running": running,
            "success": no_hang and got_2030,
            "note": ""
        }

        # Print result
        print()
        print(f"  Ergebnis fuer [{resp_hex}]:")
        print(f"    CPU/s:     {cpu_delta:.2f}  {'✓ KEIN HANG' if no_hang else '✗ HANG (CPU hoch)'}")
        print(f"    20 30:     {'✓ Empfangen' if got_2030 else '✗ Nicht empfangen'}")
        print(f"    Laeuft:    {'Ja' if running else 'Nein'}")
        if result['success']:
            print(f"    *** ERFOLG! Kein Hang + 20 30 empfangen ***")
        elif no_hang and not got_2030:
            print(f"    >> Kein Hang aber 20 30 nicht empfangen (Config nicht geoeffnet?)")
        elif not no_hang:
            print(f"    >> Hang erkannt (Reconnect-Schleife aktiv)")

        # Ask for manual note
        note = input("  Notiz (Status-Bar Text oder leer): ").strip()
        result['note'] = note

        # Check for configured keywords
        result['configured'] = any(kw in note.lower()
            for kw in ['geladen','loaded','konfiguriert','configured','ready','bereit'])

        data['results'].append(result)
        if result['success'] or result['configured']:
            data['successes'].append(result)
            print(f"\n  *** KANDIDAT GEFUNDEN: [{resp_hex}] ***")

        save_results(data)
        print(f"  Gespeichert. ({len(data['results'])} Tests insgesamt)")

        # Kill WinOLS for next test
        if running:
            kill = input("  WinOLS beenden fuer naechsten Test? [J/n]: ").strip().lower()
            if kill != 'n':
                subprocess.run(["taskkill","/F","/IM","ols_32on32.exe"], capture_output=True)
                print("  WinOLS beendet.")

    # Final summary
    print("\n" + "="*60)
    print(f"ZUSAMMENFASSUNG: {len(data['results'])} Tests")
    print(f"Erfolge: {len(data['successes'])}")
    for s in data['successes']:
        print(f"  [{s['resp']}] cpu={s['cpu_per_sec']} notiz='{s.get('note','')}'")

    no_hangs = [r for r in data['results'] if r.get('no_hang') and r.get('got_2030')]
    if no_hangs:
        print(f"\nKein-Hang + 20_30 Kandidaten:")
        for r in no_hangs:
            print(f"  [{r['resp']}] cpu={r['cpu_per_sec']}")

    print(f"\nErgebnisse: {RESULTS}")

if __name__ == "__main__":
    main()
