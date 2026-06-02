Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public class MemR3 {
    [DllImport("kernel32.dll")] public static extern IntPtr OpenProcess(uint a, bool b, uint c);
    [DllImport("kernel32.dll")] public static extern bool ReadProcessMemory(IntPtr h, IntPtr a, byte[] b, int s, out int r);
    [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
}
"@

$pids = (Get-Process "ols_32on32" -ErrorAction SilentlyContinue)
$pid1 = ($pids | Sort-Object CPU -Descending | Select-Object -First 1).Id
Write-Host "PID: $pid1"

$h = [MemR3]::OpenProcess(0x10, $false, [uint32]$pid1)
$buf = New-Object byte[] 64
$read = 0

# Read IAT entry
[MemR3]::ReadProcessMemory($h, [IntPtr]0x0426D66C, $buf, 4, [ref]$read) | Out-Null
$target = [BitConverter]::ToUInt32($buf, 0)
Write-Host ("IAT[0x0426D66C] -> 0x{0:X8}" -f $target)

# Read function bytes
if ($target -gt 0x10000) {
    $fbuf = New-Object byte[] 48
    [MemR3]::ReadProcessMemory($h, [IntPtr][uint64]$target, $fbuf, 48, [ref]$read) | Out-Null
    $hex = ($fbuf[0..($read-1)] | ForEach-Object { '{0:X2}' -f $_ }) -join ' '
    Write-Host ("Function at 0x{0:X8}: {1}" -f $target, $hex)
}

# Check what module contains the target
$modules = (Get-Process -Id $pid1).Modules | Sort-Object BaseAddress
foreach ($m in $modules) {
    $base = [uint64]$m.BaseAddress
    $size = [uint64]$m.ModuleMemorySize
    if ($target -ge $base -and $target -lt ($base + $size)) {
        Write-Host ("In module: {0} base=0x{1:X8} offset=0x{2:X}" -f $m.ModuleName, $base, ($target - $base))
        break
    }
}

[MemR3]::CloseHandle($h) | Out-Null
