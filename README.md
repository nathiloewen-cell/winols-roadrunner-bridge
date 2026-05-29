# WinOLS Roadrunner Bridge

A `ftd2xx.dll` proxy that makes WinOLS transparently communicate with a
**Moates Roadrunner** EPROM emulator (VID 0403:B471) instead of the native
Batronix programmer — including full **live data tracing**.

## Architecture

```
WinOLS
  └─► ftd2xx.dll  (our proxy, placed in WinOLS app dir)
        ├─ intercepts Batronix protocol calls
        ├─ translates to MoatesWare protocol
        └─► Real ftd2xx.dll (System32) → Roadrunner USB
```

## Features (planned)
- [x] Protocol analysis (Batronix + MoatesWare)
- [ ] ftd2xx.dll proxy skeleton
- [ ] Device spoofing (Roadrunner as Batronix)
- [ ] Read bridge
- [ ] Write bridge
- [ ] Live trace / address monitoring
- [ ] OLC profile for Roadrunner chip types

## Sprints
| Sprint | Goal | Status |
|--------|------|--------|
| S1 | Batronix protocol analysis (BSL100.dll) | ⏳ |
| S2 | MoatesWare protocol documentation (EmUtility) | ⏳ |
| S3 | ftd2xx.dll proxy skeleton + logging | ⏳ |
| S4 | Device spoofing | ⏳ |
| S5 | Read bridge | ⏳ |
| S6 | Write bridge | ⏳ |
| S7 | Trace bridge | ⏳ |
| S8 | OLC profile | ⏳ |
| S9 | End-to-end test | ⏳ |

## Hardware
- **Emulator:** Moates Roadrunner (VID 0403 / PID B471)
- **Target:** WinOLS 2.24 / 3.18 (EVC electronic)
- **Platform:** Windows 10 x64

## Tools on this machine
- `C:\Program Files\EmUtility\EmUtility.exe` — Roadrunner reference CLI
- `C:\Program Files (x86)\TunerPro RT\TPMoatesEmulatorPlugin.dll` — TunerPro Moates plugin
- `C:\Program Files\EVC\WinOLS\BSL100.dll` — Batronix simulator library (Frieling-Racing)
- `C:\Program Files\EVC\WinOLS\ftd2xx.dll` — FTDI D2XX (32-bit, to be proxied)
