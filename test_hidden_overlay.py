import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import copy
import unittest
from PySide6.QtWidgets import QApplication
from asr_voice.config.defaults import DEFAULTS
from asr_voice.config.loader import _to_namespace
from asr_voice.ui.floating_bar import FloatingBar, UI_LISTENING


class HiddenOverlayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_bar(self, hidden):
        cfg = copy.deepcopy(DEFAULTS['ui'])
        cfg.update(hide_overlay=hidden, theme_name='minimal')
        bar = FloatingBar(_to_namespace(cfg))
        self.addCleanup(bar.deleteLater)
        return bar

    def test_hidden_bar_and_transcript_stay_hidden_during_recording(self):
        bar = self.make_bar(True)
        bar.show()
        bar._set_state(UI_LISTENING)
        bar._text = '测试实时输入'
        bar._sync_bubble()
        self.app.processEvents()
        self.assertFalse(bar.isVisible(), 'recording overlay must remain hidden')
        self.assertFalse(bar._bubble.isVisible(), 'transcript preview must remain hidden')
        self.assertEqual(bar._text, '测试实时输入', 'recognition state must be preserved')

    def test_default_overlay_can_still_show(self):
        bar = self.make_bar(False)
        bar.show()
        self.app.processEvents()
        self.assertTrue(bar.isVisible())
        bar.hide()


if __name__ == '__main__':
    unittest.main()
