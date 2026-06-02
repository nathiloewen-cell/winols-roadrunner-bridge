"""Liest die Bytes bei 0x005FA822+ aus der WinOLS .exe Datei"""
import struct

EXE = r"C:\Users\Nates\WinOLS_Bridge\ols_32on32.exe"

# WinOLS base = 0x00400000 for packed Delphi
# File offset = VA - ImageBase
# 0x005FA822 - 0x00400000 = 0x1FA822

VA = 0x005FA822
IMAGE_BASE = 0x00400000
file_offset = VA - IMAGE_BASE

with open(EXE, 'rb') as f:
    f.seek(file_offset - 5)  # also show bytes before
    data = f.read(40)

print(f"Bytes at VA 0x{VA:08X} (file offset 0x{file_offset:X}):")
for i in range(0, len(data), 8):
    row = data[i:i+8]
    va_row = VA - 5 + i
    hex_str = ' '.join(f'{b:02X}' for b in row)
    print(f"  0x{va_row:08X}: {hex_str}")

# Show what's at 0x005FA82B (after JZ 0x0B at offset +7 from 0x005FA822)
# 0x005FA822 + 7 = 0x005FA829 (JZ 0B)
# 0x005FA82B = after JZ, the FF instruction
print(f"\nAt 0x005FA82B (the FF... instruction):")
offset_82b = file_offset + 9  # 0x005FA82B - 0x005FA822 = 9
with open(EXE, 'rb') as f:
    f.seek(offset_82b)
    d = f.read(10)
    print(f"  {' '.join(f'{b:02X}' for b in d)}")
    # Decode FF xx instruction
    if d[0] == 0xFF:
        if d[1] == 0x15:  # CALL [mem32]
            addr = struct.unpack_from('<I', d, 2)[0]
            print(f"  → CALL [0x{addr:08X}] (indirect call through IAT/memory)")
            # Read what's at that address
        elif d[1] == 0x10:  # CALL [EAX]
            print("  → CALL [EAX]")
        elif d[1] == 0xD0:  # CALL EAX
            print("  → CALL EAX")
        elif d[1] == 0x50:  # CALL [EAX+disp8]
            print(f"  → CALL [EAX+0x{d[2]:02X}]")
        elif d[1] == 0x90:  # CALL [EAX+disp8] variant
            print(f"  → variant")

# Also look at 0x005FA836 (where JZ jumps to = "success path")
print(f"\nAt 0x005FA836 (JZ target = success path):")
offset_836 = file_offset + 0x14  # 0x005FA836 - 0x005FA822 = 0x14
with open(EXE, 'rb') as f:
    f.seek(offset_836)
    d2 = f.read(16)
    print(f"  {' '.join(f'{b:02X}' for b in d2)}")
