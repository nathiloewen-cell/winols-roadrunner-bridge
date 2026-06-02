"""
click_simulator_ok.py
Finds the WinOLS Configuration dialog, clicks "Simulator" in the tree,
then clicks OK. Uses cross-process memory for TreeView item reading.
"""
import ctypes, ctypes.wintypes as wt, subprocess, time, sys

user32  = ctypes.windll.user32
k32     = ctypes.windll.kernel32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

TVM_GETNEXTITEM = 0x110A
TVM_GETITEM     = 0x100C
TVM_SELECTITEM  = 0x110B
TVM_ENSUREVISIBLE = 0x1114
TVGN_ROOT   = 0
TVGN_NEXT   = 1
TVGN_CHILD  = 4
TVGN_CARET  = 9
TVIF_TEXT   = 0x0001
TVIF_HANDLE = 0x0010
MEM_COMMIT  = 0x1000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04

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

def enum_wins(pids, visible_only=False):
    wins = []
    def cb(h,l):
        p=wt.DWORD(0); user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value not in pids: return True
        if visible_only and not user32.IsWindowVisible(h): return True
        tb=ctypes.create_unicode_buffer(256); cl=ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(h,tb,256); user32.GetClassNameW(h,cl,64)
        r2=wt.RECT(); user32.GetWindowRect(h, ctypes.byref(r2))
        area=(r2.right-r2.left)*(r2.bottom-r2.top)
        wins.append((h,tb.value,cl.value,area))
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return wins

def find_child(parent, cls_contains=None, text_contains=None):
    found = [None]
    def cb(h,l):
        tb=ctypes.create_unicode_buffer(256); cl=ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(h,tb,256); user32.GetClassNameW(h,cl,64)
        ok = True
        if cls_contains and cls_contains.lower() not in cl.value.lower(): ok=False
        if text_contains and text_contains.lower() not in tb.value.lower(): ok=False
        if ok: found[0]=h
        return True
    user32.EnumChildWindows(parent, WNDENUMPROC(cb), 0)
    return found[0]

def click_hwnd(hwnd):
    user32.SetForegroundWindow(hwnd); time.sleep(0.1)
    user32.SendMessageW(hwnd, 0x00F5, 0, 0)

def find_treeview_item_and_click(tv_hwnd, target):
    """
    Cross-process TreeView walk.
    Allocates TVITEMW + text buffer in target process, reads item text,
    finds 'Simulator', selects it.
    """
    # Get PID of TV owner to open its process
    pid_val = wt.DWORD(0)
    user32.GetWindowThreadProcessId(tv_hwnd, ctypes.byref(pid_val))
    pid = pid_val.value

    # Open target process with all access
    PROCESS_ALL = 0x001F0FFF
    hproc = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not hproc:
        print(f"  [tree] OpenProcess failed")
        return False

    # Allocate memory in target: TVITEMW(60 bytes) + text buffer(512 bytes)
    TVITEM_SIZE = 60
    TEXT_SIZE   = 512
    BUF_SIZE    = TVITEM_SIZE + TEXT_SIZE
    remote_buf = k32.VirtualAllocEx(hproc, None, BUF_SIZE, MEM_COMMIT, PAGE_READWRITE)
    if not remote_buf:
        k32.CloseHandle(hproc)
        print("  [tree] VirtualAllocEx failed")
        return False

    remote_text = remote_buf + TVITEM_SIZE

    found_item = [None]

    def walk(hitem, depth=0):
        if not hitem or depth > 15: return False

        # Build TVITEMW in local memory
        local_tvi = (ctypes.c_uint32 * (TVITEM_SIZE//4))()
        # mask = TVIF_TEXT | TVIF_HANDLE = 0x11
        local_tvi[0] = 0x11      # mask
        local_tvi[1] = hitem & 0xFFFFFFFF  # hItem (32-bit)
        # pszText offset = 40 bytes in (after mask,hItem,state,stateMask,pszText is at index 10)
        # TVITEMW layout (32-bit):
        # 0: UINT mask
        # 4: HTREEITEM hItem
        # 8: UINT state
        # 12: UINT stateMask
        # 16: LPWSTR pszText  ← pointer
        # 20: int cchTextMax
        import struct
        local_bytes = struct.pack('<IIIIPI', 0x11, hitem, 0, 0, remote_text, TEXT_SIZE//2)
        local_bytes += b'\x00' * (TVITEM_SIZE - len(local_bytes))

        # Write TVITEMW to remote buffer
        written = ctypes.c_size_t(0)
        k32.WriteProcessMemory(hproc, remote_buf,
                               ctypes.create_string_buffer(local_bytes), len(local_bytes),
                               ctypes.byref(written))

        # Send TVM_GETITEM
        user32.SendMessageW(tv_hwnd, TVM_GETITEM, 0, remote_buf)

        # Read text back
        text_buf = ctypes.create_string_buffer(TEXT_SIZE)
        rd = ctypes.c_size_t(0)
        k32.ReadProcessMemory(hproc, remote_text, text_buf, TEXT_SIZE, ctypes.byref(rd))
        try:
            item_text = text_buf.raw[:rd.value].decode('utf-16-le').rstrip('\x00')
        except:
            item_text = ""

        if item_text:
            print(f"  [tree] {'  '*depth}{repr(item_text)}")

        if target.lower() in item_text.lower():
            found_item[0] = hitem
            print(f"  [tree] FOUND: {repr(item_text)}")
            return True

        # Recurse into children
        child = user32.SendMessageW(tv_hwnd, TVM_GETNEXTITEM, TVGN_CHILD, hitem)
        if child and walk(child, depth+1):
            return True

        # Next sibling
        sib = user32.SendMessageW(tv_hwnd, TVM_GETNEXTITEM, TVGN_NEXT, hitem)
        if sib and walk(sib, depth):
            return True

        return False

    root = user32.SendMessageW(tv_hwnd, TVM_GETNEXTITEM, TVGN_ROOT, 0)
    print(f"  [tree] root={hex(root) if root else 'None'}")
    walk(root)

    k32.VirtualFreeEx(hproc, remote_buf, 0, MEM_RELEASE)
    k32.CloseHandle(hproc)

    if found_item[0]:
        # Select the item
        user32.SendMessageW(tv_hwnd, TVM_SELECTITEM, TVGN_CARET, found_item[0])
        user32.SendMessageW(tv_hwnd, TVM_ENSUREVISIBLE, 0, found_item[0])
        time.sleep(0.3)
        # Click on it
        user32.SetForegroundWindow(tv_hwnd)
        time.sleep(0.1)
        # Left-click the tree item (it should be selected now)
        user32.SendMessageW(tv_hwnd, 0x0201, 0x0001, 0)  # WM_LBUTTONDOWN
        time.sleep(0.05)
        user32.SendMessageW(tv_hwnd, 0x0202, 0, 0)       # WM_LBUTTONUP
        time.sleep(0.3)
        return True

    return False

def main():
    pids = get_pids()
    if not pids:
        print("WinOLS not running!")
        sys.exit(1)
    print(f"PIDs: {pids}")

    wins = enum_wins(pids, visible_only=True)
    wins.sort(key=lambda x: x[3], reverse=True)

    # Find Configuration dialog (large visible dialog with OK button)
    config_dlg = None
    for h,t,c,a in wins:
        if a < 50000: continue
        ok = find_child(h, 'button', 'OK')
        cancel = find_child(h, 'button', 'Abbrechen') or find_child(h, 'button', 'Cancel')
        if ok and cancel:
            config_dlg = h
            print(f"Config dialog: '{t}' 0x{h:08X} area={a}")
            break

    if not config_dlg:
        print("Configuration dialog not found!")
        print("Visible windows:", [(hex(h),t,a) for h,t,c,a in wins if a>5000])
        sys.exit(1)

    # Find TreeView
    tv = find_child(config_dlg, cls_contains='treeview')
    if not tv:
        tv = find_child(config_dlg, cls_contains='systree')
    print(f"TreeView: 0x{tv:08X}" if tv else "No TreeView found!")

    if tv:
        print("Walking tree to find 'Simulator'...")
        found = find_treeview_item_and_click(tv, 'Simulator')
        if found:
            print("Simulator selected!")
        else:
            print("Simulator not found in tree!")
    else:
        print("No TreeView - trying keyboard End key to reach Simulator")
        user32.SetForegroundWindow(config_dlg)
        time.sleep(0.2)
        # Tab to tree
        user32.SendMessageW(config_dlg, 0x0100, 0x09, 0)  # Tab
        time.sleep(0.1)
        # End to go to last item (Simulator should be near end)
        user32.SendMessageW(config_dlg, 0x0100, 0x23, 0)  # End
        time.sleep(0.2)

    # Wait a moment for right panel to update
    time.sleep(0.5)

    # Click USB (OLS300 only) radio button
    for search in ['OLS300', 'USB (OLS', 'USB']:
        radio = find_child(config_dlg, 'button', search)
        if radio:
            print(f"Clicking '{search}' radio")
            click_hwnd(radio)
            time.sleep(0.3)
            break
    else:
        print("USB radio not found, using current selection")

    # Click OK
    ok_btn = find_child(config_dlg, 'button', 'OK')
    if ok_btn:
        # Make sure the text is EXACTLY OK (not "Abbrechen" etc)
        tb = ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(ok_btn, tb, 64)
        print(f"Clicking OK button (text='{tb.value}')")
        click_hwnd(ok_btn)
        print("OK clicked!")
    else:
        print("OK button not found!")

if __name__ == '__main__':
    main()
