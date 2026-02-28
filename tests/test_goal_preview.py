from mitra_app.main import _truncate_goal_preview


def test_truncate_goal_preview_long_text() -> None:
    long_goal = "x" * 600

    preview = _truncate_goal_preview(long_goal)

    assert preview.endswith("…")
    assert len(preview) == 501


def test_truncate_goal_preview_short_text() -> None:
    short_goal = "Ship hotfix"

    preview = _truncate_goal_preview(short_goal)

    assert preview == short_goal
