#!/usr/bin/env python3
"""
trigger_config_ok.py - Trigger WinOLS Config dialog and click OK.

WinOLS only starts EP6 polling when WDU_Init is called, which only happens
when the user opens Configuration -> Hardware -> Simulator -> USB (OLS300) -> OK.

This script automates that sequence using Win32 API:
1. Find WinOLS main window
2. Navigate menu to Configuration dialog
3. Find OK button and click it
"""

import ctypes, ctypes.wintypes as wt, time, subprocess, sys

user32 = ctypes.windll.user32
k32    = ctypes.windll.kernel32

HWND_TOP = 0
SW_SHOW = 5
SWP_NOSIZE = 0x0001; SWP_NOMOVE = 0x0002

WM_COMMAND   = 0x0111
WM_KEYDOWN   = 0x0100
WM_KEYUP     = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP   = 0x0105
WM_SYSCOMMAND = 0x0112
SC_KEYMENU    = 0xF100
VK_ALT        = 0x12
VK_RETURN     = 0x0D
VK_ESCAPE     = 0x1B
VK_F4         = 0x73

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]

class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]
    _anonymous_ = ("_input",)
    _fields_  = [("type", wt.DWORD), ("_input", _INPUT)]

def send_key(vk, up=False):
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

def key_tap(vk):
    send_key(vk, False)
    time.sleep(0.05)
    send_key(vk, True)
    time.sleep(0.05)

def key_alt_tap(vk):
    send_key(VK_ALT, False)
    time.sleep(0.02)
    send_key(vk, False)
    time.sleep(0.02)
    send_key(vk, True)
    time.sleep(0.02)
    send_key(VK_ALT, True)
    time.sleep(0.1)

# ── Window helpers ─────────────────────────────────────────────────────────
def enum_windows():
    results = []
    def cb(hwnd, lp):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        title = buf.value
        if title: results.append((hwnd, title))
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return results

def find_winols():
    for hwnd, title in enum_windows():
        if 'WinOLS' in title or 'OLS' in title or 'ols_32on32' in title.lower():
            return hwnd, title
    return None, None

def find_child_button(parent_hwnd, btn_text):
    """Find a child button by partial text."""
    found = [None]
    def cb(hwnd, lp):
        buf = ctypes.create_unicode_buffer(128)
        user32.GetWindowTextW(hwnd, buf, 128)
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if btn_text.lower() in buf.value.lower() and 'button' in cls.value.lower():
            found[0] = hwnd
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    user32.EnumChildWindows(parent_hwnd, WNDENUMPROC(cb), 0)
    return found[0]

def find_dialog_with_ok():
    """Find a dialog window that has an OK button."""
    best = [None, None]
    def cb(hwnd, lp):
        buf = ctypes.create_unicode_buffer(128)
        user32.GetWindowTextW(hwnd, buf, 128)
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        title = buf.value
        # Check for dialog-like windows with Config/Konfiguration/Options titles
        is_config = any(k in title for k in ['Konfiguration', 'Config', 'Option', 'Setup', 'Einstellung'])
        if is_config:
            ok = find_child_button(hwnd, 'OK')
            if ok: best[0] = hwnd; best[1] = ok
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return best[0], best[1]

def click_button(hwnd):
    BM_CLICK = 0x00F5
    user32.SendMessageW(hwnd, BM_CLICK, 0, 0)

def menu_id_for_item(menu_hwnd, text_contains):
    """Walk a menu handle looking for an item containing text_contains, return ID."""
    count = user32.GetMenuItemCount(menu_hwnd)
    MF_STRING = 0; MIIM_STRING = 0x40; MIIM_ID = 0x2; MIIM_SUBMENU = 0x4

    class MENUITEMINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wt.UINT), ("fMask", wt.UINT), ("fType", wt.UINT),
            ("fState", wt.UINT), ("wID", wt.UINT), ("hSubMenu", wt.HMENU),
            ("hbmpChecked", wt.HBITMAP), ("hbmpUnchecked", wt.HBITMAP),
            ("dwItemData", ctypes.c_ulong), ("dwTypeData", wt.LPWSTR),
            ("cch", wt.UINT), ("hbmpItem", wt.HBITMAP),
        ]
    for i in range(count):
        buf = ctypes.create_unicode_buffer(256)
        mii = MENUITEMINFOW()
        mii.cbSize = ctypes.sizeof(mii)
        mii.fMask  = MIIM_STRING | MIIM_ID | MIIM_SUBMENU
        mii.dwTypeData = buf
        mii.cch = 256
        if user32.GetMenuItemInfoW(menu_hwnd, i, True, ctypes.byref(mii)):
            if text_contains.lower() in buf.value.lower():
                return mii.wID, mii.hSubMenu
    return None, None

def get_winols_menu(hwnd):
    return user32.GetMenu(hwnd)

# ── Main logic ─────────────────────────────────────────────────────────────
def find_and_print_menus():
    """Debug: print WinOLS menu structure to find Config item."""
    hwnd, title = find_winols()
    if not hwnd:
        print("WinOLS not found")
        return
    print(f"WinOLS window: {hwnd} = '{title}'")

    menu = get_winols_menu(hwnd)
    if not menu:
        print("No menu found (maybe WinOLS uses custom menu?)")
        return

    print(f"Menu handle: {menu}")
    top_count = user32.GetMenuItemCount(menu)
    print(f"Top-level items: {top_count}")

    class MENUITEMINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wt.UINT), ("fMask", wt.UINT), ("fType", wt.UINT),
            ("fState", wt.UINT), ("wID", wt.UINT), ("hSubMenu", wt.HMENU),
            ("hbmpChecked", wt.HBITMAP), ("hbmpUnchecked", wt.HBITMAP),
            ("dwItemData", ctypes.c_ulong), ("dwTypeData", wt.LPWSTR),
            ("cch", wt.UINT), ("hbmpItem", wt.HBITMAP),
        ]

    MIIM_STRING = 0x40; MIIM_ID = 0x2; MIIM_SUBMENU = 0x4

    for i in range(top_count):
        buf = ctypes.create_unicode_buffer(256)
        mii = MENUITEMINFOW()
        mii.cbSize = ctypes.sizeof(mii)
        mii.fMask  = MIIM_STRING | MIIM_ID | MIIM_SUBMENU
        mii.dwTypeData = buf
        mii.cch = 256
        if user32.GetMenuItemInfoW(menu, i, True, ctypes.byref(mii)):
            sub_count = user32.GetMenuItemCount(mii.hSubMenu) if mii.hSubMenu else 0
            print(f"  [{i}] id={mii.wID} sub={mii.hSubMenu} ({sub_count} items) '{buf.value}'")
            if mii.hSubMenu:
                for j in range(min(sub_count, 20)):
                    buf2 = ctypes.create_unicode_buffer(256)
                    mii2 = MENUITEMINFOW()
                    mii2.cbSize = ctypes.sizeof(mii2)
                    mii2.fMask  = MIIM_STRING | MIIM_ID | MIIM_SUBMENU
                    mii2.dwTypeData = buf2
                    mii2.cch = 256
                    if user32.GetMenuItemInfoW(mii.hSubMenu, j, True, ctypes.byref(mii2)):
                        sub2_count = user32.GetMenuItemCount(mii2.hSubMenu) if mii2.hSubMenu else 0
                        print(f"    [{j}] id={mii2.wID} '{buf2.value}' (sub={sub2_count})")

def trigger_ok():
    """
    Main function: find WinOLS, navigate to Config dialog, click OK.
    Returns True if OK was clicked.
    """
    hwnd, title = find_winols()
    if not hwnd:
        print("WinOLS not found")
        return False
    print(f"WinOLS: {hwnd} '{title}'")

    # Bring to foreground
    user32.ShowWindow(hwnd, SW_SHOW)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)

    # Check if Config dialog is already open
    dlg, ok_btn = find_dialog_with_ok()
    if dlg and ok_btn:
        print(f"Config dialog already open: {dlg}, clicking OK: {ok_btn}")
        click_button(ok_btn)
        return True

    # Enumerate menu to find "Konfiguration" or "Configuration"
    menu = get_winols_menu(hwnd)
    if menu:
        top_count = user32.GetMenuItemCount(menu)
        config_cmd = None

        class MENUITEMINFOW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wt.UINT), ("fMask", wt.UINT), ("fType", wt.UINT),
                ("fState", wt.UINT), ("wID", wt.UINT), ("hSubMenu", wt.HMENU),
                ("hbmpChecked", wt.HBITMAP), ("hbmpUnchecked", wt.HBITMAP),
                ("dwItemData", ctypes.c_ulong), ("dwTypeData", wt.LPWSTR),
                ("cch", wt.UINT), ("hbmpItem", wt.HBITMAP),
            ]
        MIIM_STRING = 0x40; MIIM_ID = 0x2; MIIM_SUBMENU = 0x4

        for i in range(top_count):
            buf = ctypes.create_unicode_buffer(256)
            mii = MENUITEMINFOW()
            mii.cbSize = ctypes.sizeof(mii)
            mii.fMask  = MIIM_STRING | MIIM_ID | MIIM_SUBMENU
            mii.dwTypeData = buf; mii.cch = 256
            if not user32.GetMenuItemInfoW(menu, i, True, ctypes.byref(mii)): continue
            # Look in each top-level submenu for Config
            if not mii.hSubMenu: continue
            sub_count = user32.GetMenuItemCount(mii.hSubMenu)
            for j in range(sub_count):
                buf2 = ctypes.create_unicode_buffer(256)
                mii2 = MENUITEMINFOW()
                mii2.cbSize = ctypes.sizeof(mii2)
                mii2.fMask  = MIIM_STRING | MIIM_ID | MIIM_SUBMENU
                mii2.dwTypeData = buf2; mii2.cch = 256
                if not user32.GetMenuItemInfoW(mii.hSubMenu, j, True, ctypes.byref(mii2)): continue
                item_text = buf2.value.lower()
                if 'konfig' in item_text or 'config' in item_text or 'option' in item_text:
                    config_cmd = mii2.wID
                    print(f"Found Config menu item: id={config_cmd} '{buf2.value}' (in '{buf.value}')")
                    break
            if config_cmd: break

        if config_cmd:
            print(f"Sending WM_COMMAND({config_cmd}) to open Config dialog...")
            user32.PostMessageW(hwnd, WM_COMMAND, config_cmd, 0)
            time.sleep(1.5)
        else:
            print("Config menu item not found via menu enumeration — trying keyboard")
            # Try Alt+M / Alt+E / Alt+Z for Miscellaneous/Extras/Zusatz
            for alt_key in [ord('M'), ord('E'), ord('Z'), ord('X'), ord('S')]:
                user32.SetForegroundWindow(hwnd)
                time.sleep(0.2)
                key_alt_tap(alt_key)
                time.sleep(0.3)
                # Check if a menu appeared by looking for a dialog or changed state
                dlg, ok_btn = find_dialog_with_ok()
                if dlg:
                    break
                # Try pressing Escape to close and try next key
                key_tap(VK_ESCAPE)
                time.sleep(0.1)
    else:
        # No GetMenu result — WinOLS uses custom menu rendering
        # Try keyboard navigation
        print("Custom menu (no GetMenu) — using keyboard shortcuts")
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.2)
        # Try known shortcuts
        for seq in [
            [ord('M')],          # Alt+M
            [ord('E')],          # Alt+E (Extras)
            [ord('Z')],          # Alt+Z (Zusatz)
            [ord('S')],          # Alt+S (Sonstiges)
        ]:
            key_alt_tap(seq[0])
            time.sleep(0.4)
            # Navigate with arrow + Enter
            key_tap(0x28)  # Down
            time.sleep(0.2)
            key_tap(VK_RETURN)
            time.sleep(0.5)
            dlg, ok_btn = find_dialog_with_ok()
            if dlg: break
            key_tap(VK_ESCAPE); time.sleep(0.1)
            key_tap(VK_ESCAPE); time.sleep(0.1)

    # Now look for the Config dialog
    for attempt in range(10):
        time.sleep(0.5)
        # Look for any modal dialog
        all_wins = enum_windows()
        for h, t in all_wins:
            if h == hwnd: continue
            t_lower = t.lower()
            print(f"  Window: {h} '{t}'")
            if any(k in t_lower for k in ['config', 'konfig', 'option', 'einst', 'setup', 'simulator', 'hardware']):
                ok_btn = find_child_button(h, 'OK')
                if ok_btn:
                    print(f"  -> Found Config dialog '{t}', clicking OK (btn={ok_btn})")
                    click_button(ok_btn)
                    return True
                # Also try pressing Enter to accept
                print(f"  -> Found dialog '{t}', pressing Enter")
                user32.SetForegroundWindow(h)
                time.sleep(0.2)
                key_tap(VK_RETURN)
                return True

    print("Config dialog not found — trying Enter on any foreground window")
    key_tap(VK_RETURN)
    return False


if __name__ == '__main__':
    if '--scan' in sys.argv:
        find_and_print_menus()
    else:
        ok = trigger_ok()
        print("Result:", "OK clicked" if ok else "failed")
