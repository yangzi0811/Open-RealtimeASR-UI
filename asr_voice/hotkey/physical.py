"""Listen to physical Windows key presses without capturing text or swallowing keys."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import threading

logger = logging.getLogger(__name__)


class _KeyboardEvent(ctypes.Structure):
    _fields_ = [('vkCode', wintypes.DWORD), ('scanCode', wintypes.DWORD),
                ('flags', wintypes.DWORD), ('time', wintypes.DWORD),
                ('dwExtraInfo', ctypes.c_size_t)]


class PhysicalKeyListener:
    """Keep a non-suppressing low-level hook on its own Windows message thread.

    Windows marks SendInput/keyboard-generated events as injected. Checking that
    flag avoids ignoring real keys pressed during continuous transcript injection.
    Pause belongs to the existing toggle handler, preventing a second toggle.
    """

    def __init__(self, callback):
        self.callback = callback
        self._thread = None
        self._thread_id = None
        self._ready = threading.Event()
        self._error = None
        self._hook = None
        self._proc = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive() and bool(self._hook)

    def handle_event(self, code, message, vk, flags):
        if code < 0 or message not in (0x0100, 0x0104):
            return
        if flags & (0x10 | 0x02) or vk == 0x13:
            return
        try:
            self.callback()
        except Exception:
            logger.exception('任意键停止回调失败')

    def start(self):
        if self.running:
            return
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, name='physical-key-stop', daemon=True)
        self._thread.start()
        if not self._ready.wait(3):
            raise RuntimeError('任意键停止监听启动超时')
        if self._error is not None:
            raise RuntimeError('任意键停止监听启动失败') from self._error

    def stop(self):
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(1)

    def _run(self):
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                                      wintypes.WPARAM, wintypes.LPARAM)
        user32.SetWindowsHookExW.argtypes = (ctypes.c_int, proc_type, wintypes.HINSTANCE, wintypes.DWORD)
        user32.SetWindowsHookExW.restype = wintypes.HANDLE
        user32.CallNextHookEx.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.UnhookWindowsHookEx.argtypes = (wintypes.HANDLE,)
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
        user32.GetMessageW.restype = ctypes.c_int
        kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        def on_event(code, message, data_ptr):
            try:
                if code >= 0:
                    event = ctypes.cast(data_ptr, ctypes.POINTER(_KeyboardEvent)).contents
                    self.handle_event(code, message, event.vkCode, event.flags)
            except Exception:
                logger.exception('任意键停止监听异常')
            return user32.CallNextHookEx(self._hook, code, message, data_ptr)

        try:
            self._thread_id = kernel32.GetCurrentThreadId()
            self._proc = proc_type(on_event)
            self._hook = user32.SetWindowsHookExW(13, self._proc, kernel32.GetModuleHandleW(None), 0)
            if not self._hook:
                raise ctypes.WinError(ctypes.get_last_error())
            msg = wintypes.MSG()
            # Ensure PostThreadMessage(WM_QUIT) works even immediately after start.
            user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
            self._ready.set()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            self._error = exc
            logger.exception('任意键停止监听线程失败')
        finally:
            self._ready.set()
            if self._hook:
                user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
            self._thread_id = None
