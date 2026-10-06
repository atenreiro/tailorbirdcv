"""Ctrl+C on `tailorbirdcv serve`: no tracebacks for the cancellations a shutdown causes, and a Ctrl+C delivered
twice at once (terminal + `uv run`) doesn't force-quit past the clean shutdown."""

import asyncio
import logging

import uvicorn

from tailorbirdcv.cli import _QuietShutdown, _server_class


def _record(msg="", exc=None):
    return logging.LogRecord("uvicorn.error", logging.ERROR, __file__, 1, msg, None,
                             (type(exc), exc, None) if exc else None)


def test_shutdown_noise_is_filtered_but_real_errors_are_kept():
    f = _QuietShutdown()
    assert not f.filter(_record("Exception in ASGI application\n", asyncio.CancelledError()))
    assert not f.filter(_record("Exception in 'lifespan' protocol\n", KeyboardInterrupt()))
    assert not f.filter(_record("Traceback (most recent call last):\n  ...\nasyncio.exceptions.CancelledError\n"))
    assert not f.filter(_record("Cancel 1 running task(s), timeout graceful shutdown exceeded"))
    assert f.filter(_record("Exception in ASGI application\n", ValueError("boom")))
    assert f.filter(_record("Traceback (most recent call last):\n  ...\nValueError: boom\n"))


def test_a_repeated_ctrl_c_is_ignored_but_a_later_one_forces(monkeypatch, capsys):
    import signal

    from tailorbirdcv import cli
    now = [100.0]
    monkeypatch.setattr(cli.time, "monotonic", lambda: now[0])
    server = _server_class(uvicorn)(uvicorn.Config(app=None))
    server.handle_exit(signal.SIGINT, None)
    assert server.should_exit and not server.force_exit
    assert "Stopping TailorbirdCV" in capsys.readouterr().out
    now[0] += 0.05
    server.handle_exit(signal.SIGINT, None)  # the same press, delivered again
    assert not server.force_exit
    now[0] += 2
    server.handle_exit(signal.SIGINT, None)  # a deliberate second press
    assert server.force_exit
