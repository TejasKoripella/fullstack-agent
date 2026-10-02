"""Read-only Windows Bluetooth radio detection. Never pairs or removes devices."""

import ctypes
from ctypes import wintypes
import os

from security import assert_not_admin


class _FindRadioParams(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD)]


def radio_available() -> bool:
    assert_not_admin()
    if os.name != "nt":
        return False
    api = ctypes.WinDLL("bthprops.cpl")
    api.BluetoothFindFirstRadio.argtypes = [ctypes.POINTER(_FindRadioParams), ctypes.POINTER(wintypes.HANDLE)]
    api.BluetoothFindFirstRadio.restype = wintypes.HANDLE
    api.BluetoothFindRadioClose.argtypes = [wintypes.HANDLE]
    api.BluetoothFindRadioClose.restype = wintypes.BOOL
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    params = _FindRadioParams(ctypes.sizeof(_FindRadioParams))
    radio = wintypes.HANDLE()
    finder = api.BluetoothFindFirstRadio(ctypes.byref(params), ctypes.byref(radio))
    if not finder:
        return False
    try:
        return bool(radio.value)
    finally:
        if radio.value:
            kernel.CloseHandle(radio)
        api.BluetoothFindRadioClose(finder)
