from __future__ import annotations

import os

from article_to_speech.browser.launch import BrowserProfileLease


def test_clear_stale_chromium_locks_removes_missing_socket_links(tmp_path) -> None:
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "SingletonLock").symlink_to("dead-host-42")
    (profile_dir / "SingletonCookie").symlink_to("123")
    (profile_dir / "SingletonSocket").symlink_to("/tmp/does-not-exist")

    lease = BrowserProfileLease(profile_dir)

    removed = lease.clear_stale_chromium_locks()

    assert removed == ["SingletonCookie", "SingletonLock", "SingletonSocket"]
    assert not any(os.path.lexists(profile_dir / name) for name in removed)
