from runtime.report_pipeline import (
    KPIThresholds,
    ResearchTask,
    TaskLifecycleRecord,
    build_periodic_audit_report_text,
    calculate_periodic_kpis,
    detect_kpi_degradation_alerts,
    process_research_task_to_drive,
    publish_periodic_audit_report,
)


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


def test_calculate_periodic_kpis() -> None:
    records = [
        TaskLifecycleRecord(
            task_id="T1",
            mitra_detected_gaps=True,
            reached_deploy_without_manual_edits=True,
            cycles_to_merge=2,
            missing_capabilities=["sandbox", "rollback"],
        ),
        TaskLifecycleRecord(
            task_id="T2",
            mitra_detected_gaps=False,
            reached_deploy_without_manual_edits=True,
            cycles_to_merge=4,
            missing_capabilities=["sandbox"],
        ),
        TaskLifecycleRecord(
            task_id="T3",
            mitra_detected_gaps=True,
            reached_deploy_without_manual_edits=False,
            cycles_to_merge=6,
            missing_capabilities=["observability"],
        ),
    ]

    kpis = calculate_periodic_kpis(records, top_n=2)

    assert kpis.tasks_total == 3
    assert kpis.pct_mitra_detected_gaps == 66.67
    assert kpis.pct_telegram_to_deploy_without_manual_edits == 66.67
    assert kpis.median_cycles_to_merge == 4.0
    assert kpis.top_recurring_missing_capabilities == [("sandbox", 2), ("rollback", 1)]


def test_detect_kpi_degradation_alerts() -> None:
    records = [
        TaskLifecycleRecord(
            task_id="T1",
            mitra_detected_gaps=False,
            reached_deploy_without_manual_edits=False,
            cycles_to_merge=8,
            missing_capabilities=["sandbox"],
        )
    ]
    kpis = calculate_periodic_kpis(records)

    alerts = detect_kpi_degradation_alerts(
        kpis,
        KPIThresholds(
            min_pct_mitra_detected_gaps=50.0,
            min_pct_telegram_to_deploy_without_manual_edits=50.0,
            max_median_cycles_to_merge=3.0,
        ),
    )

    assert len(alerts) == 3
    assert "self-detected gaps" in alerts[0]
    assert "Telegram→Deploy" in alerts[1]
    assert "median cycles-to-merge" in alerts[2]


def test_build_periodic_audit_report_text_uses_template(tmp_path) -> None:
    template = tmp_path / "template.md"
    template.write_text(
        "Period <YYYY-MM-DD .. YYYY-MM-DD>\n"
        "At <timestamp UTC>\n"
        "Owner <team/person>\n"
        "Gap <pct_mitra_detected_gaps>\n"
        "Auto <pct_telegram_to_deploy_without_manual_edits>\n"
        "Median <median_cycles_to_merge>\n"
        "Caps\n<top_recurring_missing_capabilities>\n"
        "Alerts\n<kpi_alerts>\n",
        encoding="utf-8",
    )

    report = build_periodic_audit_report_text(
        period="2026-02-01 .. 2026-02-07",
        owner="Ops",
        kpis=calculate_periodic_kpis(
            [
                TaskLifecycleRecord(
                    task_id="T1",
                    mitra_detected_gaps=True,
                    reached_deploy_without_manual_edits=True,
                    cycles_to_merge=1,
                    missing_capabilities=["sandbox"],
                )
            ]
        ),
        alerts=["⚠️ degraded"],
        template_path=str(template),
    )

    assert "2026-02-01 .. 2026-02-07" in report
    assert "Gap 100.0%" in report
    assert "- sandbox: 1" in report
    assert "- ⚠️ degraded" in report


def test_publish_periodic_audit_report(tmp_path) -> None:
    template = tmp_path / "template.md"
    template.write_text(
        "Period <YYYY-MM-DD .. YYYY-MM-DD>\n"
        "Gap <pct_mitra_detected_gaps>\n"
        "Alerts\n<kpi_alerts>",
        encoding="utf-8",
    )
    drive = FakeDriveClient()
    tg = FakeTelegramClient()

    artifact = publish_periodic_audit_report(
        period="2026-02",
        owner="Ops",
        records=[
            TaskLifecycleRecord(
                task_id="T1",
                mitra_detected_gaps=False,
                reached_deploy_without_manual_edits=False,
                cycles_to_merge=8,
                missing_capabilities=["sandbox"],
            )
        ],
        drive_client=drive,
        telegram_client=tg,
        telegram_chat_id="chat-1",
        template_path=str(template),
    )

    assert artifact.file_id == "file-123"
    assert drive.shareable_called is True
    assert drive.content is not None
    file_name, content, _mime = drive.content
    assert file_name.startswith("periodic-audit-report-")
    assert "Gap 0.0%" in content
    assert tg.messages and "Alerts:" in tg.messages[0][1]
