import os
import sqlite3
from datetime import datetime, date, time, timedelta
from typing import Any, Dict, List, Optional

import gradio as gr

from accounts import Account, BUSINESS_DAY_CHOICES

DEFAULT_ADMIN_EMAIL = "admin@example.com"
DEFAULT_ADMIN_PASSWORD = "admin123"

REPORT_TABLE_HEADERS = [
    "Report ID",
    "Technician",
    "Project",
    "Location",
    "Date Begin",
    "Time Begin",
    "Date End",
    "Time End",
    "Hours",
    "Comments",
    "Created At",
    "Updated At"
]

COMPANY_PROFILE_HEADERS = ["Field", "Value"]
DEFAULT_BUSINESS_DAYS = BUSINESS_DAY_CHOICES[:5]
DEFAULT_COMPANY_PROFILE = {
    "company_name": "",
    "physical_address": "",
    "country": "",
    "email": "",
    "contact_person": "",
    "business_days": DEFAULT_BUSINESS_DAYS,
    "start_time": "08:00",
    "end_time": "18:00",
    "lunch_minutes": 60,
    "time_zone": "UTC",
    "minimum_wage": 15.0
}

CUSTOM_CSS = """
:root {
    --section-spacing: 0.75rem;
}
#app-title {
    text-align: center;
    margin-bottom: 0.5rem;
}
.gradio-container {
    max-width: 1200px !important;
    margin: 0 auto;
    position: relative;
}
.compact-row {
    gap: 0.5rem !important;
}
#logout-button {
    position: absolute;
    top: 0.75rem;
    right: 0.75rem;
    width: auto !important;
    z-index: 10;
}
#logout-button button {
    font-size: 0.85rem;
    padding: 0.25rem 0.75rem;
}
@media (max-width: 768px) {
    .gradio-container {
        padding: 0.5rem !important;
    }
    .compact-row {
        flex-direction: column !important;
    }
    #print-btn {
        width: 100%;
    }
}
"""


def ensure_default_admin() -> None:
    try:
        Account.create_root_admin(
            first_name="Root",
            last_name="Admin",
            email=DEFAULT_ADMIN_EMAIL,
            job_position="Administrator",
            hour_salary=0.0,
            can_drive=False,
            password=DEFAULT_ADMIN_PASSWORD
        )
    except ValueError:
        pass


ensure_default_admin()


def load_account_from_state(state: Optional[Dict[str, Any]]) -> Account:
    if not state or "user_id" not in state:
        raise ValueError("Please log in first.")
    db_file = Account._ensure_db(state.get("db_path"))
    user_id = int(state["user_id"])
    with sqlite3.connect(db_file) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise ValueError("User record not found. Please log in again.")
    return Account(
        user_id=row["id"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        email=row["email"],
        job_position=row["job_position"],
        hour_salary=row["hour_salary"],
        can_drive=bool(row["can_drive"]),
        status=row["status"],
        user_type=row["user_type"],
        db_path=db_file
    )


def build_user_summary(account: Account) -> str:
    return (
        f"**Welcome {account.full_name}!**\n\n"
        f"- Role: `{account.user_type.title()}`\n"
        f"- Email: `{account.email}`\n"
        f"- Status: `{account.status.title()}`\n"
        f"- Hourly Rate: `${account.hour_salary:,.2f}`\n"
        f"- Can Drive: `{'Yes' if account.can_drive else 'No'}`"
    )


def format_display_datetime(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def build_report_rows(reports: List[Dict[str, Any]]) -> List[List[str]]:
    rows: List[List[str]] = []
    for report in reports:
        rows.append([
            str(report.get("report_id", "")),
            report.get("technician_name", ""),
            report.get("project", ""),
            report.get("location", ""),
            report.get("date_begin", ""),
            report.get("time_begin", ""),
            report.get("date_end", ""),
            report.get("time_end", ""),
            f"{float(report.get("hours", 0.0)):.2f}",
            report.get("Job Description", ""),
            format_display_datetime(report.get("created_at")),
            format_display_datetime(report.get("updated_at"))
        ])
    return rows


def build_company_profile_rows(profile: Optional[Dict[str, Any]]) -> List[List[str]]:
    if not profile:
        return []
    business_hours = profile.get("business_hours", {})
    days = ", ".join(business_hours.get("days", []))
    schedule = ""
    if business_hours.get("start_time") and business_hours.get("end_time"):
        schedule = f"{business_hours['start_time']} \u2192 {business_hours['end_time']}"
    return [
        ["Company name", profile.get("company_name", "")],
        ["Physical address", profile.get("physical_address", "")],
        ["Country", profile.get("country", "")],
        ["Email", profile.get("email", "")],
        ["Contact person", profile.get("contact_person", "")],
        ["Business days", days],
        ["Business hours", schedule],
        ["Lunch break", f"{int(profile.get('lunch_minutes', 0))} minutes"],
        ["Time zone", profile.get("time_zone", "")],
        ["Minimum wage", f"${float(profile.get('minimum_wage', 0.0)):.2f}"],
        ["Last updated", format_display_datetime(profile.get("updated_at")) or "\u2014"]
    ]


def build_company_form_defaults(profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    defaults = DEFAULT_COMPANY_PROFILE.copy()
    defaults["business_days"] = list(DEFAULT_COMPANY_PROFILE["business_days"])
    if not profile:
        return defaults
    hours = profile.get("business_hours", {})
    defaults.update(
        {
            "company_name": profile.get("company_name", ""),
            "physical_address": profile.get("physical_address", ""),
            "country": profile.get("country", ""),
            "email": profile.get("email", ""),
            "contact_person": profile.get("contact_person", ""),
            "business_days": hours.get("days", defaults["business_days"]),
            "start_time": hours.get("start_time", defaults["start_time"]),
            "end_time": hours.get("end_time", defaults["end_time"]),
            "lunch_minutes": int(profile.get("lunch_minutes", defaults["lunch_minutes"])),
            "time_zone": profile.get("time_zone", defaults["time_zone"]),
            "minimum_wage": float(profile.get("minimum_wage", defaults["minimum_wage"]))
        }
    )
    return defaults


def build_recent_report_choices(reports: List[Dict[str, Any]]) -> List[str]:
    choices: List[str] = []
    now = datetime.utcnow()
    for report in reports:
        created_at_raw = report.get("created_at")
        try:
            created_at = datetime.fromisoformat(created_at_raw) if created_at_raw else None
        except ValueError:
            created_at = None
        if created_at and now - created_at <= timedelta(days=5):
            label = (
                f"{report['report_id']} | {report['project']} "
                f"({report['date_begin']} {report['time_begin']} → "
                f"{report['date_end']} {report['time_end']})"
            )
            choices.append(label)
    return choices


def parse_report_dropdown_value(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        identifier = value.split(" | ", 1)[0]
        return int(identifier.strip())
    except (IndexError, ValueError):
        return None


def get_technician_filter_choices(account: Account) -> List[str]:
    if not account.is_admin:
        return []
    choices = ["All Technicians"]
    with account._get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, first_name, last_name, status FROM users WHERE user_type = 'technician' ORDER BY first_name, last_name"
        ).fetchall()
    for row in rows:
        label = f"{row['id']} - {row['first_name']} {row['last_name']}"
        if row["status"] != "active":
            label += " (inactive)"
        choices.append(label)
    return choices


def parse_technician_filter_value(value: Optional[str]) -> Optional[int]:
    if not value or value.lower().startswith("all"):
        return None
    parts = value.split(" ", 1)
    try:
        return int(parts[0])
    except ValueError:
        return None


def convert_date_input(value: Optional[Any]) -> Optional[str]:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def convert_time_input(value: Optional[Any]) -> Optional[str]:
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def format_dashboard_data(summary: Dict[str, Any]) -> (List[str], List[List[str]], str):
    date_labels = summary.get("date_range", [])
    headers = ["Technician", "Total Hours"] + date_labels
    rows: List[List[str]] = []
    for tech in summary.get("technicians", []):
        row = [tech.get("name", ""), f"{float(tech.get('total_hours', 0.0)):.2f}"]
        daily = tech.get("daily_hours", {})
        for label in date_labels:
            row.append(f"{float(daily.get(label, 0.0)):.2f}")
        rows.append(row)
    info = (
        f"Activity window: **{summary.get('start_date', '')} → {summary.get('end_date', '')}**. "
        f"Generated at {format_display_datetime(summary.get('generated_at'))} UTC."
    )
    if not rows:
        info = "No technician activity recorded in the last 6 days."
    return headers, rows, info


def clear_export_file() -> Dict[str, Any]:
    return gr.update(value=None, visible=False)


def load_company_profile(state: Optional[Dict[str, Any]]) -> tuple:
    default_values = build_company_form_defaults(None)
    base_field_updates = [
        gr.update(value=default_values["company_name"]),
        gr.update(value=default_values["physical_address"]),
        gr.update(value=default_values["country"]),
        gr.update(value=default_values["email"]),
        gr.update(value=default_values["contact_person"]),
        gr.update(value=default_values["business_days"]),
        gr.update(value=default_values["start_time"]),
        gr.update(value=default_values["end_time"]),
        gr.update(value=default_values["lunch_minutes"]),
        gr.update(value=default_values["time_zone"]),
        gr.update(value=default_values["minimum_wage"])
    ]
    try:
        account = load_account_from_state(state)
        if not account.is_admin:
            warning = "Only administrators can view the company profile."
            return (
                gr.update(value=[]),
                warning,
                *base_field_updates,
                warning
            )
        profile = account.get_company_profile()
        rows = build_company_profile_rows(profile)
        info = "Company profile is not set yet." if not profile else (
            f"Last updated at {format_display_datetime(profile.get('updated_at')) or 'N/A'}."
        )
        values = build_company_form_defaults(profile)
        field_updates = [
            gr.update(value=values["company_name"]),
            gr.update(value=values["physical_address"]),
            gr.update(value=values["country"]),
            gr.update(value=values["email"]),
            gr.update(value=values["contact_person"]),
            gr.update(value=values["business_days"]),
            gr.update(value=values["start_time"]),
            gr.update(value=values["end_time"]),
            gr.update(value=values["lunch_minutes"]),
            gr.update(value=values["time_zone"]),
            gr.update(value=values["minimum_wage"])
        ]
        return (
            gr.update(value=rows),
            info,
            *field_updates,
            ""
        )
    except Exception as exc:
        warning = f"⚠️ {exc}"
        no_change = gr.update()
        return (
            no_change,
            warning,
            *([no_change] * len(base_field_updates)),
            warning
        )


def save_company_profile(
    state: Optional[Dict[str, Any]],
    company_name: str,
    physical_address: str,
    country: str,
    email: str,
    contact_person: str,
    business_days: List[str],
    start_time: str,
    end_time: str,
    lunch_minutes: Optional[float],
    time_zone: str,
    minimum_wage: Optional[float]
) -> tuple:
    try:
        account = load_account_from_state(state)
        profile = account.save_company_profile(
            company_name=company_name or "",
            physical_address=physical_address or "",
            country=country or "",
            email=email or "",
            contact_person=contact_person or "",
            business_days=business_days or [],
            start_time=start_time or "",
            end_time=end_time or "",
            lunch_minutes=int(lunch_minutes) if lunch_minutes is not None else None,
            time_zone=time_zone or "",
            minimum_wage=minimum_wage
        )
        rows = build_company_profile_rows(profile)
        values = build_company_form_defaults(profile)
        field_updates = [
            gr.update(value=values["company_name"]),
            gr.update(value=values["physical_address"]),
            gr.update(value=values["country"]),
            gr.update(value=values["email"]),
            gr.update(value=values["contact_person"]),
            gr.update(value=values["business_days"]),
            gr.update(value=values["start_time"]),
            gr.update(value=values["end_time"]),
            gr.update(value=values["lunch_minutes"]),
            gr.update(value=values["time_zone"]),
            gr.update(value=values["minimum_wage"])
        ]
        info = f"Last updated at {format_display_datetime(profile.get('updated_at')) or 'N/A'}."
        return (
            gr.update(value=rows),
            info,
            *field_updates,
            "✅ Company profile saved."
        )
    except Exception as exc:
        no_change = gr.update()
        return (
            no_change,
            f"⚠️ Could not save profile: {exc}",
            *([no_change] * 11),
            f"⚠️ {exc}"
        )


def handle_login(email: str, password: str, state: Optional[Dict[str, Any]]) -> tuple:
    email = (email or "").strip()
    password = password or ""
    try:
        account = Account.authenticate(email, password)
    except Exception as exc:
        return (
            f"❌ Login failed: {exc}",
            gr.update(visible=True),
            gr.update(visible=False),
            "",
            state or {},
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(choices=[], value=None, interactive=False),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(value="")
        )
    new_state = {
        "user_id": account.user_id,
        "db_path": account.db_path,
        "user_type": account.user_type
    }
    summary = build_user_summary(account)
    technician_filter_choices = get_technician_filter_choices(account)
    return (
        "✅ Login successful.",
        gr.update(visible=False),
        gr.update(visible=True),
        summary,
        new_state,
        gr.update(visible=account.is_admin),
        gr.update(visible=(account.user_type == "technician")),
        gr.update(visible=(account.user_type == "technician")),
        gr.update(visible=account.is_admin),
        gr.update(
            choices=technician_filter_choices,
            value="All Technicians" if account.is_admin else None,
            interactive=account.is_admin
        ),
        gr.update(visible=account.is_admin),
        gr.update(visible=account.is_admin),
        gr.update(value="")
    )


def handle_logout(state: Optional[Dict[str, Any]]) -> tuple:
    return (
        "🔒 Logged out.",
        gr.update(visible=True),
        gr.update(visible=False),
        "",
        {},
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(choices=[], value=None, interactive=False),
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(value="")
    )


def refresh_reports(
    state: Optional[Dict[str, Any]],
    technician_filter_value: Optional[str],
    start_date_value: Optional[Any],
    end_date_value: Optional[Any]
) -> tuple:
    try:
        account = load_account_from_state(state)
    except Exception as exc:
        return (
            gr.update(value=[]),
            f"⚠️ {exc}",
            gr.update(choices=[], value=None),
            gr.update(),
            clear_export_file()
        )
    target_user_id = parse_technician_filter_value(technician_filter_value) if account.is_admin else None
    start_date = convert_date_input(start_date_value)
    end_date = convert_date_input(end_date_value)
    try:
        reports = account.view_reports(user_id=target_user_id, start_date=start_date, end_date=end_date)
    except Exception as exc:
        return (
            gr.update(value=[]),
            f"⚠️ {exc}",
            gr.update(choices=[], value=None),
            gr.update(),
            clear_export_file()
        )
    rows = build_report_rows(reports)
    message = f"Showing {len(reports)} report{'s' if len(reports) != 1 else ''}."
    if not reports:
        message = "No reports found for the selected filters."
    recent_choices = build_recent_report_choices(reports) if account.user_type == "technician" else []
    technician_choices = get_technician_filter_choices(account) if account.is_admin else None
    technician_dropdown_update = (
        gr.update(
            choices=technician_choices,
            value=technician_filter_value if technician_choices and technician_filter_value in technician_choices else "All Technicians",
            interactive=True
        )
        if technician_choices is not None
        else gr.update()
    )
    return (
        gr.update(value=rows),
        message,
        gr.update(choices=recent_choices, value=None),
        technician_dropdown_update,
        clear_export_file()
    )


def refresh_dashboard(state: Optional[Dict[str, Any]]) -> tuple:
    try:
        account = load_account_from_state(state)
        summary = account.dashboard_activity()
        headers, rows, info = format_dashboard_data(summary)
        return gr.update(headers=headers, value=rows), info
    except Exception as exc:
        return gr.update(value=[]), f"⚠️ {exc}"


def submit_report(
    state: Optional[Dict[str, Any]],
    project: str,
    location: str,
    date_begin_value: Optional[Any],
    time_begin_value: Optional[Any],
    date_end_value: Optional[Any],
    time_end_value: Optional[Any],
    comments: str
) -> tuple:
    try:
        account = load_account_from_state(state)
        if account.user_type != "technician":
            raise PermissionError("Only technicians can submit job reports.")
        account.report_job_hours(
            project=project or "",
            location=location or "",
            date_begin=convert_date_input(date_begin_value) or "",
            time_begin=convert_time_input(time_begin_value) or "",
            date_end=convert_date_input(date_end_value) or "",
            time_end=convert_time_input(time_end_value) or "",
            comments=comments or ""
        )
        reports = account.view_reports()
        rows = build_report_rows(reports)
        recent_choices = build_recent_report_choices(reports)
        message = "✅ Report submitted successfully."
        return (
            message,
            gr.update(value=rows),
            f"Showing {len(reports)} report{'s' if len(reports) != 1 else ''}.",
            gr.update(choices=recent_choices, value=None),
            clear_export_file()
        )
    except Exception as exc:
        return (
            f"❌ Could not submit report: {exc}",
            gr.update(),
            "",
            gr.update(),
            clear_export_file()
        )


def load_report_details(state: Optional[Dict[str, Any]], selection: Optional[str]) -> tuple:
    report_id = parse_report_dropdown_value(selection)
    if not report_id:
        empty_update = gr.update(value=None)
        return (
            gr.update(value=""),
            gr.update(value=""),
            empty_update,
            gr.update(value=None),
            empty_update,
            gr.update(value=None),
            gr.update(value=""),
            ""
        )
    try:
        account = load_account_from_state(state)
        row = account._get_report_by_id(report_id)
        if not row:
            raise ValueError("Report not found.")
        if row["user_id"] != account.user_id:
            raise PermissionError("You can only load your own reports.")
        return (
            gr.update(value=row["project"]),
            gr.update(value=row["location"]),
            gr.update(value=row["date_begin"] or ""),
            gr.update(value=row["time_begin"]),
            gr.update(value=row["date_end"] or ""),
            gr.update(value=row["time_end"]),
            gr.update(value=row["comments"] or ""),
            ""
        )
    except Exception as exc:
        empty_update = gr.update()
        return (
            empty_update,
            empty_update,
            empty_update,
            empty_update,
            empty_update,
            empty_update,
            empty_update,
            f"⚠️ {exc}"
        )


def save_report_edits(
    state: Optional[Dict[str, Any]],
    selection: Optional[str],
    project: str,
    location: str,
    date_begin_value: Optional[Any],
    time_begin_value: Optional[Any],
    date_end_value: Optional[Any],
    time_end_value: Optional[Any],
    comments: str
) -> tuple:
    report_id = parse_report_dropdown_value(selection)
    if not report_id:
        return (
            "⚠️ Select a report to edit.",
            gr.update(),
            "",
            gr.update(),
            clear_export_file()
        )
    try:
        account = load_account_from_state(state)
        success = account.edit_report(
            report_id=report_id,
            project=project,
            location=location,
            date_begin=convert_date_input(date_begin_value),
            time_begin=convert_time_input(time_begin_value),
            date_end=convert_date_input(date_end_value),
            time_end=convert_time_input(time_end_value),
            comments=comments
        )
        if not success:
            raise ValueError("Report can only be edited within 5 days of creation.")
        reports = account.view_reports()
        rows = build_report_rows(reports)
        recent_choices = build_recent_report_choices(reports)
        return (
            "✅ Report updated successfully.",
            gr.update(value=rows),
            f"Showing {len(reports)} report{'s' if len(reports) != 1 else ''}.",
            gr.update(choices=recent_choices, value=None),
            clear_export_file()
        )
    except Exception as exc:
        return (
            f"❌ Could not update report: {exc}",
            gr.update(),
            "",
            gr.update(),
            clear_export_file()
        )


def handle_create_user(
    state: Optional[Dict[str, Any]],
    user_type: Optional[str],
    first_name: str,
    last_name: str,
    email: str,
    job_position: str,
    hour_salary: Optional[float],
    can_drive: bool,
    status: Optional[str],
    password: str,
    current_filter_value: Optional[str]
) -> tuple:
    try:
        account = load_account_from_state(state)
        if not account.is_admin:
            raise PermissionError("Only administrators can create users.")
        salary_value = float(hour_salary) if hour_salary is not None else 0.0
        account.create_user(
            user_type=user_type or "",
            first_name=first_name or "",
            last_name=last_name or "",
            email=email or "",
            job_position=job_position or "",
            hour_salary=salary_value,
            can_drive=can_drive,
            status=status or "",
            password=password or None
        )
        creds = account.last_created_user_credentials or {}
        generated_password = creds.get("password") if not password else password
        message_lines = [
            f"✅ User created successfully (ID #{creds.get('user_id', 'N/A')}).",
            f"- Type: `{creds.get('user_type', user_type)}`",
            f"- Email: `{creds.get('email', email)}`"
        ]
        if generated_password:
            message_lines.append(f"- Temporary password: `{generated_password}`")
        technician_choices = get_technician_filter_choices(account)
        selected_value = (
            current_filter_value if current_filter_value in technician_choices else "All Technicians"
        )
        return (
            "\n".join(message_lines),
            gr.update(value=""),
            gr.update(choices=technician_choices, value=selected_value, interactive=True)
        )
    except Exception as exc:
        return (
            f"❌ Could not create user: {exc}",
            gr.update(),
            gr.update()
        )


def export_reports_action(
    state: Optional[Dict[str, Any]],
    technician_filter_value: Optional[str],
    start_date_value: Optional[Any],
    end_date_value: Optional[Any],
    format_choice: str
) -> tuple:
    try:
        account = load_account_from_state(state)
        target_user_id = parse_technician_filter_value(technician_filter_value) if account.is_admin else None
        start_date = convert_date_input(start_date_value)
        end_date = convert_date_input(end_date_value)
        reports = account.view_reports(user_id=target_user_id, start_date=start_date, end_date=end_date)
        if not reports:
            return ("⚠️ There are no reports to export for the selected filters.", clear_export_file())
        selected_format = (format_choice or "excel").strip().lower()
        path = account.export_reports(reports, file_format=selected_format)
        file_name = os.path.basename(path)
        icon = "📁"
        if selected_format == "csv":
            icon = "🧾"
        elif selected_format == "json":
            icon = "🗂️"
        return (
            f"{icon} Export ready: **{file_name}**",
            gr.update(value=path, visible=True)
        )
    except Exception as exc:
        return (f"❌ Export failed: {exc}", clear_export_file())


with gr.Blocks(
    title="Job Time Report system",
    css=CUSTOM_CSS,
    theme=gr.themes.Soft()
) as demo:
    app_state = gr.State({})
    gr.Markdown("# Job Time Report system", elem_id="app-title")
    login_status = gr.Markdown("")
    with gr.Column(visible=True) as login_panel:
        gr.Markdown(
            "Use the demo administrator credentials to sign in:\n\n"
            f"- Email: `{DEFAULT_ADMIN_EMAIL}`\n"
            f"- Password: `{DEFAULT_ADMIN_PASSWORD}`",
            elem_id="login-hint"
        )
        login_email = gr.Textbox(label="Email", placeholder="you@example.com")
        login_password = gr.Textbox(label="Password", type="password", placeholder="••••••")
        login_button = gr.Button("Login", variant="primary")
    with gr.Column(visible=False) as main_panel:
        user_summary = gr.Markdown("")
        logout_button = gr.Button("Logout", variant="secondary", elem_id="logout-button")
        with gr.Tabs():
            with gr.TabItem("Dashboard"):
                dashboard_refresh = gr.Button("Refresh Activity Overview", variant="secondary")
                dashboard_info = gr.Markdown("")
                dashboard_table = gr.Dataframe(
                    value=[],
                    headers=["Technician", "Total Hours"],
                    interactive=False,
                    wrap=True
                )
            with gr.TabItem("Company Profile") as company_profile_tab:
                company_profile_info = gr.Markdown("Company profile is not set yet.")
                company_profile_table = gr.Dataframe(
                    value=[],
                    headers=COMPANY_PROFILE_HEADERS,
                    interactive=False,
                    wrap=True
                )
                company_refresh_button = gr.Button("Refresh profile", variant="secondary")
                with gr.Column(visible=False) as company_form_panel:
                    gr.Markdown("### Edit company profile")
                    company_form_status = gr.Markdown("")
                    company_name_input = gr.Textbox(label="Company name")
                    company_address_input = gr.Textbox(label="Physical address", lines=2)
                    company_country_input = gr.Textbox(label="Country")
                    company_email_input = gr.Textbox(label="Email address")
                    company_contact_input = gr.Textbox(label="Contact person")
                    company_days_input = gr.CheckboxGroup(
                        label="Business days",
                        choices=BUSINESS_DAY_CHOICES,
                        value=DEFAULT_BUSINESS_DAYS
                    )
                    with gr.Row(elem_classes=["compact-row"]):
                        company_start_time_input = gr.Textbox(
                            label="Business start (HH:MM)",
                            value="08:00",
                            placeholder="08:00"
                        )
                        company_end_time_input = gr.Textbox(
                            label="Business end (HH:MM)",
                            value="18:00",
                            placeholder="18:00"
                        )
                    with gr.Row(elem_classes=["compact-row"]):
                        company_lunch_minutes_input = gr.Number(
                            label="Lunch break (minutes)",
                            value=60,
                            precision=0,
                            minimum=0
                        )
                        company_timezone_input = gr.Textbox(label="Time zone", value="UTC")
                    company_min_wage_input = gr.Number(
                        label="Minimum wage",
                        value=15.0,
                        precision=2,
                        minimum=0
                    )
                    company_save_button = gr.Button("Save profile", variant="primary")
                company_profile_outputs = [
                    company_profile_table,
                    company_profile_info,
                    company_name_input,
                    company_address_input,
                    company_country_input,
                    company_email_input,
                    company_contact_input,
                    company_days_input,
                    company_start_time_input,
                    company_end_time_input,
                    company_lunch_minutes_input,
                    company_timezone_input,
                    company_min_wage_input,
                    company_form_status
                ]
            with gr.TabItem("My Reports"):
                with gr.Row(elem_classes=["compact-row"]):
                    report_filter_start = gr.Textbox(
                        label="Start date (YYYY-MM-DD)",
                        placeholder="YYYY-MM-DD"
                    )
                    report_filter_end = gr.Textbox(
                        label="End date (YYYY-MM-DD)",
                        placeholder="YYYY-MM-DD"
                    )
                    with gr.Column(visible=False) as technician_filter_box:
                        technician_filter_dropdown = gr.Dropdown(
                            label="Technician filter",
                            choices=[],
                            value=None,
                            interactive=False
                        )
                with gr.Row(elem_classes=["compact-row"]):
                    refresh_reports_button = gr.Button("Apply Filters", variant="primary")
                    print_button = gr.Button(
                        "Print Current View",
                        elem_id="print-btn",
                        variant="secondary"
                    )
                reports_info = gr.Markdown("")
                reports_table = gr.Dataframe(
                    value=[],
                    headers=REPORT_TABLE_HEADERS,
                    interactive=False,
                    wrap=True,
                    max_height=300
                )
                with gr.Row(elem_classes=["compact-row"]):
                    export_format = gr.Radio(
                        ["Excel", "CSV", "JSON"],
                        label="Export format",
                        value="Excel"
                    )
                    export_button = gr.Button("Export Reports")
                export_status = gr.Markdown("")
                export_file = gr.File(label="Download export", visible=False)
                with gr.Accordion("Edit recent report", open=False) as edit_section:
                    with gr.Column(visible=False) as technician_edit_panel:
                        recent_reports_dropdown = gr.Dropdown(
                            label="Select report to edit (last 5 days)",
                            choices=[],
                            value=None
                        )
                        edit_status = gr.Markdown("")
                        edit_project = gr.Textbox(label="Project")
                        edit_location = gr.Textbox(label="Location")
                        with gr.Row(elem_classes=["compact-row"]):
                            edit_date_begin = gr.Textbox(
                                label="Date begin (YYYY-MM-DD)",
                                placeholder="YYYY-MM-DD"
                            )
                            edit_time_begin = gr.Textbox(
                                label="Time begin (HH:MM)",
                                placeholder="HH:MM"
                            )
                        with gr.Row(elem_classes=["compact-row"]):
                            edit_date_end = gr.Textbox(
                                label="Date end (YYYY-MM-DD)",
                                placeholder="YYYY-MM-DD"
                            )
                            edit_time_end = gr.Textbox(
                                label="Time end (HH:MM)",
                                placeholder="HH:MM"
                            )
                        edit_comments = gr.Textbox(label="Comments", lines=3)
                        edit_submit = gr.Button("Save changes", variant="primary")
            with gr.TabItem("Report Hours") as report_tab:
                with gr.Column(visible=False) as report_form_panel:
                    report_status = gr.Markdown("")
                    report_project = gr.Textbox(label="Project", placeholder="Project name")
                    report_location = gr.Textbox(label="Location", placeholder="Work site / location")
                    with gr.Row(elem_classes=["compact-row"]):
                        report_date_begin = gr.DateTime(
                            label="Date begin",
                            include_time=False,
                            type="string",
                            value=datetime.utcnow().date().isoformat(),
                            interactive=True
                        )
                        report_time_begin = gr.Textbox(
                            label="Time begin (HH:MM)",
                            value="08:00",
                            placeholder="HH:MM"
                        )
                    with gr.Row(elem_classes=["compact-row"]):
                        report_date_end = gr.DateTime(
                            label="Date end",
                            include_time=False,
                            type="string",
                            value=datetime.utcnow().date().isoformat(),
                            interactive=True
                        )
                        report_time_end = gr.Textbox(
                            label="Time end (HH:MM)",
                            value="17:00",
                            placeholder="HH:MM"
                        )
                    report_comments = gr.Textbox(label="Comments", lines=3, placeholder="Optional notes")
                    submit_report_button = gr.Button("Submit hours", variant="primary")
            with gr.TabItem("Admin tools"):
                admin_panel = gr.Column(visible=False)
                with admin_panel:
                    gr.Markdown("### Create a new user")
                    admin_create_status = gr.Markdown("")
                    admin_new_user_type = gr.Dropdown(
                        label="User type",
                        choices=["technician", "admin"],
                        value="technician"
                    )
                    with gr.Row(elem_classes=["compact-row"]):
                        admin_first_name = gr.Textbox(label="First name")
                        admin_last_name = gr.Textbox(label="Last name")
                    admin_email = gr.Textbox(label="Email")
                    admin_job_position = gr.Textbox(label="Job position", value="Technician")
                    admin_hour_salary = gr.Number(label="Hourly salary", value=25.0, precision=2, minimum=0)
                    admin_can_drive = gr.Checkbox(label="Can drive", value=True)
                    admin_status = gr.Dropdown(
                        label="Status",
                        choices=["active", "inactive"],
                        value="active"
                    )
                    admin_password = gr.Textbox(label="Password (leave blank for auto)", type="password")
                    admin_create_button = gr.Button("Create user", variant="primary")

    company_refresh_button.click(
        load_company_profile,
        inputs=[app_state],
        outputs=company_profile_outputs
    )

    company_save_button.click(
        save_company_profile,
        inputs=[
            app_state,
            company_name_input,
            company_address_input,
            company_country_input,
            company_email_input,
            company_contact_input,
            company_days_input,
            company_start_time_input,
            company_end_time_input,
            company_lunch_minutes_input,
            company_timezone_input,
            company_min_wage_input
        ],
        outputs=company_profile_outputs
    )

    login_button.click(
        handle_login,
        inputs=[login_email, login_password, app_state],
        outputs=[
            login_status,
            login_panel,
            main_panel,
            user_summary,
            app_state,
            admin_panel,
            report_form_panel,
            technician_edit_panel,
            technician_filter_box,
            technician_filter_dropdown,
            company_profile_tab,
            company_form_panel,
            company_form_status
        ]
    ).then(
        refresh_reports,
        inputs=[app_state, technician_filter_dropdown, report_filter_start, report_filter_end],
        outputs=[reports_table, reports_info, recent_reports_dropdown, technician_filter_dropdown, export_file]
    ).then(
        refresh_dashboard,
        inputs=[app_state],
        outputs=[dashboard_table, dashboard_info]
    ).then(
        load_company_profile,
        inputs=[app_state],
        outputs=company_profile_outputs
    )

    logout_button.click(
        handle_logout,
        inputs=[app_state],
        outputs=[
            login_status,
            login_panel,
            main_panel,
            user_summary,
            app_state,
            admin_panel,
            report_form_panel,
            technician_edit_panel,
            technician_filter_box,
            technician_filter_dropdown,
            company_profile_tab,
            company_form_panel,
            company_form_status
        ]
    )

    refresh_reports_button.click(
        refresh_reports,
        inputs=[app_state, technician_filter_dropdown, report_filter_start, report_filter_end],
        outputs=[reports_table, reports_info, recent_reports_dropdown, technician_filter_dropdown, export_file]
    )

    technician_filter_dropdown.change(
        refresh_reports,
        inputs=[app_state, technician_filter_dropdown, report_filter_start, report_filter_end],
        outputs=[reports_table, reports_info, recent_reports_dropdown, technician_filter_dropdown, export_file]
    )

    report_filter_start.change(
        refresh_reports,
        inputs=[app_state, technician_filter_dropdown, report_filter_start, report_filter_end],
        outputs=[reports_table, reports_info, recent_reports_dropdown, technician_filter_dropdown, export_file]
    )

    report_filter_end.change(
        refresh_reports,
        inputs=[app_state, technician_filter_dropdown, report_filter_start, report_filter_end],
        outputs=[reports_table, reports_info, recent_reports_dropdown, technician_filter_dropdown, export_file]
    )

    dashboard_refresh.click(
        refresh_dashboard,
        inputs=[app_state],
        outputs=[dashboard_table, dashboard_info]
    )

    submit_report_button.click(
        submit_report,
        inputs=[
            app_state,
            report_project,
            report_location,
            report_date_begin,
            report_time_begin,
            report_date_end,
            report_time_end,
            report_comments
        ],
        outputs=[report_status, reports_table, reports_info, recent_reports_dropdown, export_file]
    )

    recent_reports_dropdown.change(
        load_report_details,
        inputs=[app_state, recent_reports_dropdown],
        outputs=[
            edit_project,
            edit_location,
            edit_date_begin,
            edit_time_begin,
            edit_date_end,
            edit_time_end,
            edit_comments,
            edit_status
        ]
    )

    edit_submit.click(
        save_report_edits,
        inputs=[
            app_state,
            recent_reports_dropdown,
            edit_project,
            edit_location,
            edit_date_begin,
            edit_time_begin,
            edit_date_end,
            edit_time_end,
            edit_comments
        ],
        outputs=[edit_status, reports_table, reports_info, recent_reports_dropdown, export_file]
    )

    admin_create_button.click(
        handle_create_user,
        inputs=[
            app_state,
            admin_new_user_type,
            admin_first_name,
            admin_last_name,
            admin_email,
            admin_job_position,
            admin_hour_salary,
            admin_can_drive,
            admin_status,
            admin_password,
            technician_filter_dropdown
        ],
        outputs=[admin_create_status, admin_password, technician_filter_dropdown]
    )

    export_button.click(
        export_reports_action,
        inputs=[app_state, technician_filter_dropdown, report_filter_start, report_filter_end, export_format],
        outputs=[export_status, export_file]
    )

    print_button.click(js="window.print();")


if __name__ == "__main__":
    demo.launch()
