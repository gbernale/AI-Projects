import json
import os
from datetime import datetime, timedelta

import pytest

from accounts import Account


@pytest.fixture(autouse=True)
def reset_account_initialized():
    Account._initialized_dbs.clear()
    yield
    Account._initialized_dbs.clear()


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "job_time_reports_test.db")


def create_root_admin(db_path: str) -> Account:
    return Account.create_root_admin(
        first_name="Admin",
        last_name="User",
        email="admin@example.com",
        job_position="Manager",
        hour_salary=75.0,
        can_drive=True,
        password="AdminPass123!",
        db_path=db_path,
    )


def create_and_authenticate_technician(admin: Account, email: str, password: str, first_name: str = "Tech", last_name: str = "User") -> Account:
    admin.create_user(
        user_type="technician",
        first_name=first_name,
        last_name=last_name,
        email=email,
        job_position="Field Engineer",
        hour_salary=30.0,
        can_drive=True,
        status="active",
        password=password,
    )
    return Account.authenticate(email=email, password=password, db_path=admin.db_path)


def test_create_root_admin_and_authenticate_success(db_path):
    admin = create_root_admin(db_path)
    assert admin.is_admin
    assert admin.full_name == "Admin User"

    authenticated = Account.authenticate("admin@example.com", "AdminPass123!", db_path=db_path)
    assert authenticated.is_admin
    assert authenticated.user_id == admin.user_id
    assert authenticated.email == "admin@example.com"


def test_create_root_admin_existing_admin_raises(db_path):
    create_root_admin(db_path)
    with pytest.raises(ValueError):
        create_root_admin(db_path)


def test_admin_create_user_success(db_path, monkeypatch):
    admin = create_root_admin(db_path)

    monkeypatch.setattr(Account, "_generate_temporary_password", staticmethod(lambda length=12: "TempPass!23"))

    result = admin.create_user(
        user_type="technician",
        first_name="Jane",
        last_name="Doe",
        email="jane.doe@example.com",
        job_position="Technician",
        hour_salary=28.5,
        can_drive="yes",
        status="active",
    )

    assert result is True
    credentials = admin.last_created_user_credentials
    assert credentials is not None
    assert credentials["email"] == "jane.doe@example.com"
    assert credentials["user_type"] == "technician"
    assert credentials["password"] == "TempPass!23"

    with admin._get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", ("jane.doe@example.com",)).fetchone()
        assert row is not None
        assert row["first_name"] == "Jane"
        assert row["user_type"] == "technician"
        assert row["can_drive"] == 1
        assert row["status"] == "active"


def test_admin_create_user_invalid_type_raises(db_path):
    admin = create_root_admin(db_path)
    with pytest.raises(ValueError):
        admin.create_user(
            user_type="manager",
            first_name="Invalid",
            last_name="Type",
            email="invalid@example.com",
            job_position="Unknown",
            hour_salary=20.0,
            can_drive=False,
            status="active",
        )


def test_report_job_hours_success(db_path, monkeypatch):
    admin = create_root_admin(db_path)
    technician = create_and_authenticate_technician(admin, "tech@example.com", "TechPass1!")

    fixed_timestamp = "2024-01-10T10:00:00"
    monkeypatch.setattr(Account, "_utcnow", staticmethod(lambda: fixed_timestamp))

    result = technician.report_job_hours(
        project="Project Alpha",
        location="Site A",
        date_begin="2024-01-09",
        time_begin="08:00",
        date_end="2024-01-09",
        time_end="12:30",
        comments="Completed installation tasks",
    )

    assert result is True
    report = technician.last_created_report
    assert report is not None
    assert report["project"] == "Project Alpha"
    assert report["hours"] == 4.5
    assert report["comments"] == "Completed installation tasks"
    assert report["created_at"] == fixed_timestamp
    assert report["updated_at"] == fixed_timestamp

    with technician._get_connection() as conn:
        row = conn.execute("SELECT * FROM job_reports WHERE id = ?", (report["report_id"],)).fetchone()
        assert row is not None
        assert pytest.approx(row["hours"], 0.01) == 4.5


def test_report_job_hours_only_technicians(db_path):
    admin = create_root_admin(db_path)
    with pytest.raises(PermissionError):
        admin.report_job_hours(
            project="Admin Project",
            location="HQ",
            date_begin="2024-01-01",
            time_begin="09:00",
            date_end="2024-01-01",
            time_end="11:00",
            comments="Invalid attempt",
        )


def test_view_reports_admin_filter_by_user(db_path):
    admin = create_root_admin(db_path)
    tech1 = create_and_authenticate_technician(admin, "tech1@example.com", "TechPass1!", first_name="Alice", last_name="Smith")
    tech2 = create_and_authenticate_technician(admin, "tech2@example.com", "TechPass2!", first_name="Bob", last_name="Jones")

    tech1.report_job_hours(
        project="Project X",
        location="Location X",
        date_begin="2024-01-02",
        time_begin="08:00",
        date_end="2024-01-02",
        time_end="12:00",
        comments="Tech1 report",
    )
    tech2.report_job_hours(
        project="Project Y",
        location="Location Y",
        date_begin="2024-01-03",
        time_begin="09:00",
        date_end="2024-01-03",
        time_end="11:00",
        comments="Tech2 report",
    )

    reports_for_tech1 = admin.view_reports(user_id=tech1.user_id)
    assert len(reports_for_tech1) == 1
    assert reports_for_tech1[0]["user_id"] == tech1.user_id
    assert reports_for_tech1[0]["project"] == "Project X"


def test_edit_report_within_five_days(db_path, monkeypatch):
    admin = create_root_admin(db_path)
    technician = create_and_authenticate_technician(admin, "tech@example.com", "TechPass1!")

    creation_time = "2024-01-01T08:00:00"
    monkeypatch.setattr(Account, "_utcnow", staticmethod(lambda: creation_time))
    technician.report_job_hours(
        project="Initial Project",
        location="Initial Location",
        date_begin="2024-01-01",
        time_begin="08:00",
        date_end="2024-01-01",
        time_end="12:00",
        comments="Original comment",
    )
    report_id = technician.last_created_report["report_id"]

    updated_time = "2024-01-02T09:00:00"
    monkeypatch.setattr(Account, "_utcnow", staticmethod(lambda: updated_time))
    result = technician.edit_report(
        report_id=report_id,
        project="Updated Project",
        time_end="14:00",
        comments="Updated comment",
    )

    assert result is True
    row = technician._get_report_by_id(report_id)
    assert row is not None
    assert row["project"] == "Updated Project"
    assert pytest.approx(float(row["hours"]), 0.01) == 6.0
    assert row["comments"] == "Updated comment"


def test_edit_report_older_than_five_days_returns_false(db_path):
    admin = create_root_admin(db_path)
    technician = create_and_authenticate_technician(admin, "tech@example.com", "TechPass1!")

    technician.report_job_hours(
        project="Old Project",
        location="Old Location",
        date_begin="2024-01-01",
        time_begin="08:00",
        date_end="2024-01-01",
        time_end="12:00",
        comments="Old comment",
    )
    report_id = technician.last_created_report["report_id"]

    old_timestamp = (datetime.utcnow() - timedelta(days=10)).replace(microsecond=0).isoformat()
    with technician._get_connection() as conn:
        conn.execute(
            "UPDATE job_reports SET created_at = ?, updated_at = ? WHERE id = ?",
            (old_timestamp, old_timestamp, report_id),
        )

    result = technician.edit_report(
        report_id=report_id,
        comments="Attempted update",
    )
    assert result is False

    row = technician._get_report_by_id(report_id)
    assert row["comments"] == "Old comment"


def test_dashboard_activity_aggregates_recent_hours(db_path):
    admin = create_root_admin(db_path)
    technician = create_and_authenticate_technician(admin, "tech@example.com", "TechPass1!", first_name="Charlie", last_name="Delta")

    today = datetime.utcnow().date()
    start_date = today - timedelta(days=5)

    for offset in range(3):
        work_date = start_date + timedelta(days=offset)
        technician.report_job_hours(
            project=f"Project {offset}",
            location=f"Site {offset}",
            date_begin=work_date.isoformat(),
            time_begin="08:00",
            date_end=work_date.isoformat(),
            time_end="10:00",
            comments=f"Work day {offset}",
        )

    dashboard = admin.dashboard_activity()
    expected_range = [(start_date + timedelta(days=i)).isoformat() for i in range(6)]

    assert dashboard["date_range"] == expected_range
    assert dashboard["start_date"] == expected_range[0]
    assert dashboard["end_date"] == expected_range[-1]
    assert "generated_at" in dashboard

    technicians = dashboard["technicians"]
    assert len(technicians) == 1
    technician_summary = technicians[0]
    assert technician_summary["name"] == "Charlie Delta"

    total_hours = technician_summary["total_hours"]
    assert pytest.approx(total_hours, 0.01) == 6.0

    daily_hours = technician_summary["daily_hours"]
    for offset in range(3):
        work_date = expected_range[offset]
        assert pytest.approx(daily_hours[work_date], 0.01) == 2.0


def test_export_reports_json_creates_file(db_path):
    admin = create_root_admin(db_path)
    technician = create_and_authenticate_technician(admin, "tech@example.com", "TechPass1!", first_name="Dana", last_name="Echo")

    technician.report_job_hours(
        project="Export Project",
        location="Export Location",
        date_begin="2024-01-05",
        time_begin="09:00",
        date_end="2024-01-05",
        time_end="11:00",
        comments="Export test report",
    )

    reports = admin.view_reports(user_id=technician.user_id)
    file_path = admin.export_reports(reports, file_format="json")

    assert os.path.exists(file_path)
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list)
    assert data[0]["project"] == "Export Project"
    assert data[0]["user_id"] == technician.user_id


def test_export_reports_technician_cannot_export_others(db_path):
    admin = create_root_admin(db_path)
    tech1 = create_and_authenticate_technician(admin, "tech1@example.com", "TechPass1!", first_name="Frank", last_name="Green")
    tech2 = create_and_authenticate_technician(admin, "tech2@example.com", "TechPass2!", first_name="Helen", last_name="Indigo")

    tech1.report_job_hours(
        project="Sensitive Project",
        location="Restricted Site",
        date_begin="2024-01-06",
        time_begin="08:00",
        date_end="2024-01-06",
        time_end="12:00",
        comments="Confidential work",
    )

    reports = admin.view_reports(user_id=tech1.user_id)
    with pytest.raises(PermissionError):
        tech2.export_reports(reports, file_format="csv")