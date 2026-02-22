from runtime.report_pipeline import ResearchTask, process_research_task_to_drive


class FakeDriveClient:
    def __init__(self) -> None:
        self.content = None
        self.shareable_called = False

    def create_text_file(self, *, name: str, content: str, mime_type: str = "text/markdown") -> str:
        self.content = (name, content, mime_type)
        return "file-123"

    def make_shareable(self, *, file_id: str) -> None:
        assert file_id == "file-123"
        self.shareable_called = True

    def get_web_view_link(self, *, file_id: str) -> str:
        assert file_id == "file-123"
        return "https://drive.google.com/file/d/file-123/view"


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages = []

    def send_message(self, *, chat_id: str, text: str) -> None:
        self.messages.append((chat_id, text))


def test_process_research_task_to_drive() -> None:
    task = ResearchTask(
        task_id="TASK-42",
        topic="Рынок embedded AI",
        findings=["Спрос растет", "Нужна оптимизация затрат"],
        audience="C-level",
    )
    drive = FakeDriveClient()
    tg = FakeTelegramClient()

    artifact = process_research_task_to_drive(
        task=task,
        drive_client=drive,
        telegram_client=tg,
        telegram_chat_id="chat-1",
    )

    assert artifact.file_id == "file-123"
    assert artifact.web_view_link.endswith("file-123/view")
    assert drive.shareable_called is True
    assert drive.content is not None
    assert tg.messages
    assert "Ссылка на артефакт" in tg.messages[0][1]
