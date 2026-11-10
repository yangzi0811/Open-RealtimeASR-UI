import ctypes
import os
import threading
import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from asr_voice.hotkey.physical import PhysicalKeyListener
from asr_voice.core.app import VoiceApp, APP_STATE_IDLE, APP_STATE_LISTENING
from asr_voice.input.injector import TextInjector, _send_unicode_text


class PhysicalKeysTest(unittest.TestCase):
    def test_only_physical_key_downs_interrupt(self):
        callback = Mock()
        listener = PhysicalKeyListener(callback)
        # Software-generated Unicode, backspace and Ctrl+V must never stop ASR.
        for vk in (0xE7, 0x08, 0x11, 0x56):
            listener.handle_event(0, 0x100, vk, 0x10)
            listener.handle_event(0, 0x104, vk, 0x02)
        listener.handle_event(0, 0x101, 0x41, 0)
        listener.handle_event(-1, 0x100, 0x41, 0)
        listener.handle_event(0, 0x100, 0x13, 0)  # PB uses its existing toggle.
        callback.assert_not_called()
        # Includes modifiers, navigation and function keys, without a time guard.
        for vk in (0x41, 0x20, 0x0D, 0x08, 0x10, 0x25, 0x70):
            listener.handle_event(0, 0x100, vk, 0)
        listener.handle_event(0, 0x104, 0x12, 0)
        self.assertEqual(callback.call_count, 8)

    def test_real_windows_hook_can_install_and_release(self):
        listener = PhysicalKeyListener(lambda: None)
        listener.start()
        self.assertTrue(listener.running)
        listener.stop()
        self.assertFalse(listener.running)

    def test_callback_failure_cannot_break_hook(self):
        listener = PhysicalKeyListener(Mock(side_effect=RuntimeError('test')))
        with self.assertLogs('asr_voice.hotkey.physical', level='ERROR'):
            listener.handle_event(0, 0x100, 0x41, 0)


class AnyKeyStopTest(unittest.TestCase):
    def make_app(self, state):
        stopped = threading.Event()
        app = SimpleNamespace(
            cfg=SimpleNamespace(recording=SimpleNamespace(stop_on_any_key=True)),
            state=state, _discard_results=False, _session_interrupted=False,
            _lock=threading.Lock(), injector=SimpleNamespace(cancel_pending=Mock()),
            _stop_session=stopped.set,
        )
        app._stop_after_any_key = lambda: VoiceApp._stop_after_any_key(app)
        return app, stopped

    def test_idle_key_does_not_start_or_stop_recording(self):
        app, stopped = self.make_app(APP_STATE_IDLE)
        VoiceApp._on_any_key_interrupt(app)
        self.assertFalse(stopped.is_set())
        self.assertFalse(app._discard_results)

    def test_recording_stops_and_late_transcripts_are_discarded(self):
        app, stopped = self.make_app(APP_STATE_LISTENING)
        VoiceApp._on_any_key_interrupt(app)
        self.assertTrue(stopped.wait(1))
        self.assertTrue(app._discard_results)
        self.assertTrue(app._session_interrupted)
        app.injector.cancel_pending.assert_called_once()
        VoiceApp._on_any_key_interrupt(app)
        app.injector.cancel_pending.assert_called_once()

    def test_disabled_option_ignores_physical_key(self):
        app, stopped = self.make_app(APP_STATE_LISTENING)
        app.cfg.recording.stop_on_any_key = False
        VoiceApp._on_any_key_interrupt(app)
        self.assertFalse(stopped.is_set())


class InputCancellationTest(unittest.TestCase):
    def make_injector(self):
        injector = TextInjector.__new__(TextInjector)
        injector._jobs = queue.Queue()
        injector._cancel_generation = 0
        injector._active_generation = 0
        return injector

    def test_cancel_also_invalidates_running_input(self):
        injector = self.make_injector()
        self.assertFalse(injector._input_cancelled())
        injector.cancel_pending()
        self.assertTrue(injector._input_cancelled())

    def test_dequeued_old_job_is_skipped_and_new_session_can_type(self):
        injector = self.make_injector()
        old = Mock()
        injector._submit(old)
        dequeued = injector._jobs.get_nowait()
        injector.cancel_pending()
        dequeued()
        old.assert_not_called()
        new = Mock()
        injector._submit(new)
        injector._jobs.get_nowait()()
        new.assert_called_once()
        self.assertFalse(injector._input_cancelled())

    def test_cancelled_unicode_and_backspaces_send_no_more_keys(self):
        injector = self.make_injector()
        injector.cancel_pending()
        with patch('asr_voice.input.injector.keyboard.send') as send:
            injector._backspace(5)
            send.assert_not_called()
        with patch.object(ctypes.windll.user32, 'SendInput') as send_input:
            _send_unicode_text('abc', should_cancel=injector._input_cancelled)
            send_input.assert_not_called()


if __name__ == '__main__':
    unittest.main()
