import socket
import threading
import time

import pytest
import uvicorn


class ServerThread:
    """Run a FastAPI app in a background uvicorn server for e2e tests."""

    def __init__(self, app, port: int):
        self.port = port
        config = uvicorn.Config(app, host="127.0.0.1", port=port,
                                log_level="error")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self):
        self.thread.start()
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", self.port), 0.1):
                    return self
            except OSError:
                time.sleep(0.05)
        raise RuntimeError(f"server on :{self.port} failed to start")

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=3)


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GAIT_DATA_DIR", str(tmp_path))
    return tmp_path
