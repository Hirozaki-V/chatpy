import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# Resolve caminhos para lidar com a pasta client-desktop que possui hífen
current_dir = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, current_dir)

root_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.insert(0, root_dir)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

from controllers.chat_controller import ChatController
from ui.login_dialog import LoginDialog
from ui.main_window import MainWindow
from ui.theme import get_saved_theme, get_theme_stylesheet


def main():
    app = QApplication(sys.argv)

    # Define a fonte global
    font = QFont("Segoe UI", 9)
    app.setFont(font)

    # Aplica stylesheet retrô com base no tema salvo
    saved_theme = get_saved_theme()
    app.setStyleSheet(get_theme_stylesheet(saved_theme))

    # URLs configuráveis via variáveis de ambiente (default: localhost)
    default_host = os.getenv("CHATPY_HOST", "127.0.0.1")
    default_port = os.getenv("CHATPY_PORT", "5000")
    api_url = os.getenv("CHATPY_API_URL", f"http://{default_host}:{default_port}")
    ws_url = os.getenv("CHATPY_WS_URL", f"ws://{default_host}:{default_port}/ws")

    controller = ChatController(api_url=api_url, ws_url=ws_url)

    while True:
        login_dialog = LoginDialog(controller)
        if login_dialog.exec() == LoginDialog.Accepted:
            main_window = MainWindow(controller)
            main_window.show()

            res = app.exec()

            if not getattr(main_window, "logout_requested", False):
                # Logout explícito antes de sair (revoga sessão REST)
                try:
                    controller.logout()
                except Exception:
                    pass
                sys.exit(res)
            else:
                # Logout solicitado — volta para a tela de login
                try:
                    controller.logout()
                except Exception:
                    pass
        else:
            try:
                controller.service.disconnect()
            except Exception:
                pass
            sys.exit(0)


if __name__ == "__main__":
    main()
