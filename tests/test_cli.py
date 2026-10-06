import socket
import webbrowser

from tailorbirdcv import cli


def test_opens_browser_once_server_listens(monkeypatch):
    opened = []
    monkeypatch.setattr(webbrowser, "open", opened.append)
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        port = srv.getsockname()[1]
        cli._open_when_ready(f"http://127.0.0.1:{port}", port, timeout=5)
    assert opened == [f"http://127.0.0.1:{port}"]


def test_gives_up_quietly_if_server_never_starts(monkeypatch):
    opened = []
    monkeypatch.setattr(webbrowser, "open", opened.append)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]  # bound but not listening → connection refused
        cli._open_when_ready(f"http://127.0.0.1:{port}", port, timeout=0.5)
    assert opened == []
