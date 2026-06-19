import sys
import os
import unittest
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QTextEdit
from PySide6.QtCore import QObject, Signal

# Resolve paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../client-desktop")))

from models.state import ClientState
from ui.main_window import MainWindow

class DummyService:
    def __init__(self):
        self.token = "dummy_token"
        self.is_connected = True
    def disconnect(self):
        pass

class DummyController(QObject):
    state_updated = Signal()
    message_added = Signal(str, dict)
    notification_requested = Signal(str, str)
    connection_status_changed = Signal(str)
    status_message = Signal(str, int)
    error_dialog = Signal(str, str)
    typing_received = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.state = ClientState()
        self.state.username = "test_user"
        self.service = DummyService()

    def load_room_members(self, room_name):
        return []

    def change_status(self, status):
        pass

    def logout(self):
        pass

    def update_room_settings(self, room_id, **kwargs):
        pass

    def refresh_friends(self):
        pass

    def _on_event_received(self, event, payload):
        pass

class TestDesktopUiTabs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if not cls.app:
            cls.app = QApplication([])

    def test_single_geral_tab_on_state_updates(self):
        controller = DummyController()
        # Ensure #geral is the only room joined initially
        controller.state.joined_rooms = ["#geral"]
        
        window = MainWindow(controller)
        
        # Simulate initial update signal
        controller.state_updated.emit()
        
        # Verify exactly 1 tab exists and it is #geral
        self.assertEqual(window.chat_tabs.count(), 1)
        self.assertEqual(window.chat_tabs.tabText(0).replace(" ⭐", "").strip(), "#geral")
        
        # Simulate subsequent updates from loading thread finishing rooms loading
        controller.state.rooms_loaded = True
        controller.state_updated.emit()
        
        self.assertEqual(window.chat_tabs.count(), 1)
        
        # Attempt to insert '#geral' via state helper and verify duplicates prevention
        controller.state.add_joined_room("#geral")
        controller.state_updated.emit()
        
        self.assertEqual(window.chat_tabs.count(), 1)
        self.assertEqual(len(controller.state.joined_rooms), 1)

    def test_join_room_repeatedly_preserves_inputs(self):
        controller = DummyController()
        window = MainWindow(controller)
        
        # Join room
        controller.state.add_joined_room("#testroom")
        controller.state_updated.emit()
        self.assertEqual(window.chat_tabs.count(), 2)
        
        tab_widget = window.chat_tabs.widget(1)
        self.assertIsNotNone(tab_widget.findChild(QTextEdit, "ChatInput"))
        self.assertIsNotNone(tab_widget.findChild(QPushButton, "SendButton"))
        
        # Deliberately corrupt the tab by removing ChatInputEdit
        chat_input = tab_widget.findChild(QTextEdit, "ChatInput")
        chat_input.setParent(None)
        
        # Trigger update (should reconstruct tab)
        controller.state_updated.emit()
        
        # Verify tab count is still 2 and inputs are present
        self.assertEqual(window.chat_tabs.count(), 2)
        
        # Find the tab for #testroom by searching all tabs
        found_chat_input = False
        for i in range(window.chat_tabs.count()):
            tab = window.chat_tabs.widget(i)
            if tab and tab.findChild(QTextEdit, "ChatInput"):
                found_chat_input = True
                self.assertIsNotNone(tab.findChild(QPushButton, "SendButton"))
                break
        
        self.assertTrue(found_chat_input, "ChatInput widget not found in any tab after rebuild")

    def test_dm_attachment_persistence(self):
        controller = DummyController()
        window = MainWindow(controller)
        
        # Open DM with a user and add attachment message
        controller.state.add_joined_room("@user1")
        controller.state.messages["@user1"] = [
            {
                "sender": "user1",
                "content": "[Anexo: image.png]",
                "timestamp": "2026-06-14T20:00:00Z",
                "attachment": {
                    "id": "att-id-123",
                    "filename": "image.png",
                    "file_size": 2048,
                    "mime_type": "image/png",
                    "url": "/api/attachments/att-id-123/download"
                }
            }
        ]
        controller.state_updated.emit()
        
        # Check tab is present
        self.assertEqual(window.chat_tabs.count(), 2)
        self.assertEqual(window.chat_tabs.tabText(1), "@user1")
        
        # Simulate downloading image background
        window._download_image_background("@user1", "att-id-123", "image.png", "image/png")
        
        # Verify DM tab remains intact and is not cleared
        controller.state_updated.emit()
        self.assertIn("@user1", controller.state.joined_rooms)
        self.assertEqual(window.chat_tabs.count(), 2)

if __name__ == "__main__":
    unittest.main()
