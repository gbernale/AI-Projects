import os
import sqlite3
import json
import csv
import zipfile
import tempfile
import hashlib
import secrets
import hmac
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Dict, Any, Set
from xml.sax.saxutils import escape


class Account:
    """
    Account management class for the Job Time Report system.
    Handles user creation, authentication, job hour reporting, viewing, editing, dashboard aggregation, and data export.
    """
    DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "job_time_reports.db")
    USER_TYPES = {"admin", "technician"}
    STATUS_TYPES = {"active", "inactive"}
    _initialized_dbs: Set[str] = set()

    def __init__(
        self,
        user_id: int,
        first_name: str,
        last_name: str,
        email: str,
        job_position: str,
        hour_salary: float,
        can_drive: bool,
        status: str,
        user_type: str,
        db_path: Optional[str] = None
    ) -> None:
        self.db_path = self._ensure_db(db_path)
        self.user_id = int(user_id)
        self.first_name = first_name
        self.last_name = last_name
        self.email = email
        self.job_position = job_position
        self.hour_salary = float(hour_salary)
        self.can_drive = bool(can_drive)
        self.status = status.lower()
        self.user_type = user_type.lower()
        self.created_at: Optional[str] = None
        self.updated_at: Optional[str] = None
        self._last_created_user_credentials: Optional[Dict[str, Any]] = None
        self._last_created_report: Optional[Dict[str, Any]] = None
        self._refresh_from_db()

    # ------------------------------------------------------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------------------------------------------------------

    def create_user(
        self,
        user_type: str,
        first_name: str,
        last_name: str,
        email: str,
        job_position: str,
        hour_salary: float,
        can_drive: bool,
        status: str,
        password: Optional[str] = None
    ) -> bool:
        """
        Create a new user (admin or technician). Only administrators may create users.
        Returns True on success, False otherwise.
        """
        self._ensure_active()
        if not self.is_admin:
            raise PermissionError("Only administrators can create users.")

        normalized_user_type = user_type.strip().lower()
        if normalized_user_type not in self.USER_TYPES:
            raise ValueError("user_type must be either 'admin' or 'technician'.")

        normalized_status = status.strip().lower()
        if normalized_status not in self.STATUS_TYPES:
            raise ValueError("status must be either 'active' or 'inactive'.")

        normalized_email = email.strip().lower()
        if not normalized_email:
            raise ValueError("Email address is required.")

        if not first_name.strip():
            raise ValueError("First name is required.")
        if not last_name.strip():
            raise ValueError("Last name is required.")
        if not job_position.strip():
            raise ValueError("Job position is required.")
        if hour_salary < 0:
            raise ValueError("hour_salary must be zero or positive.")

        drive_flag = self._coerce_bool(can_drive)
        password_to_use = password or self._generate_temporary_password()
        password_hash = self._hash_password(password_to_use)

        timestamp = self._utcnow()
        with self._get_connection() as conn:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO users (
                        user_type, first_name, last_name, email,
                        job_position, hour_salary, can_drive, status,
                        password_hash, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized_user_type,
                        first_name.strip(),
                        last_name.strip(),
                        normalized_email,
                        job_position.strip(),
                        float(hour_salary),
                        1 if drive_flag else 0,
                        normalized_status,
                        password_hash,
                        timestamp,
                        timestamp
                    )
                )
                new_user_id = cursor.lastrowid
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Could not create user: {exc}") from exc

        self._last_created_user_credentials = {
            "user_id": new_user_id,
            "email": normalized_email,
            "password": password_to_use,
            "user_type": normalized_user_type
        }
        return True

    def report_job_hours(
        self,
        project: str,
        location: str,
        date_begin: str,
        time_begin: str,
        date_end: str,
        time_end: str,
        comments: str
    ) -> bool:
        """
        Submit a job hour report for the current technician.
        Calculates hours automatically.
        """
        self._ensure_active()
        if self.user_type != "technician":
            raise PermissionError("Only technicians can submit job hour reports.")

        cleaned_project = project.strip()
        cleaned_location = location.strip()
        cleaned_comments = (comments or "").strip()

        if not cleaned_project:
            raise ValueError("Project name is required.")
        if not cleaned_location:
            raise ValueError("Location is required.")

        start_date = self._normalize_date(date_begin, field_name="date_begin")
        end_date = self._normalize_date(date_end, field_name="date_end")
        start_time = self._normalize_time(time_begin, field_name="time_begin")
        end_time = self._normalize_time(time_end, field_name="time_end")

        start_dt = self._combine_datetime(start_date, start_time)
        end_dt = self._combine_datetime(end_date, end_time)

        if end_dt <= start_dt:
            raise ValueError("End date/time must be after begin date/time.")

        hours = round((end_dt - start_dt).total_seconds() / 3600, 2)
        timestamp = self._utcnow()

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO job_reports (
                    user_id, project, location,
                    date_begin, time_begin, date_end, time_end,
                    hours, comments, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.user_id,
                    cleaned_project,
                    cleaned_location,
                    start_date,
                    start_time,
                    end_date,
                    end_time,
                    hours,
                    cleaned_comments,
                    timestamp,
                    timestamp
                )
            )
            report_id = cursor.lastrowid

        row = self._get_report_by_id(report_id)
        if row:
            self._last_created_report = self._format_report_row(row)
        return True

    def view_reports(
        self,
        user_id: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        View job hour reports.
        - Administrators can view all technicians' reports (optionally filtered by user_id).
        - Technicians can view only their own reports.
        - If no filters provided, returns the last 5 reports relevant to the requester.
        """
        self._ensure_active()
        target_user_id = self.user_id if not self.is_admin else user_id

        normalized_start = self._normalize_date(start_date) if start_date else None
        normalized_end = self._normalize_date(end_date) if end_date else None
        if normalized_start and normalized_end and normalized_start > normalized_end:
            raise ValueError("start_date must be on or before end_date.")

        conditions = ["u.user_type = 'technician'"]
        params: List[Any] = []

        if target_user_id:
            conditions.append("r.user_id = ?")
            params.append(target_user_id)

        if normalized_start:
            conditions.append("date(r.date_begin) >= ?")
            params.append(normalized_start)

        if normalized_end:
            conditions.append("date(r.date_end) <= ?")
            params.append(normalized_end)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        limit_clause = ""
        if not (normalized_start or normalized_end or target_user_id != (self.user_id if not self.is_admin else user_id)):
            limit_clause = "LIMIT 5"

        query = f"""
            SELECT
                r.id AS report_id,
                r.user_id,
                u.first_name,
                u.last_name,
                u.email,
                r.project,
                r.location,
                r.date_begin,
                r.time_begin,
                r.date_end,
                r.time_end,
                r.hours,
                r.comments,
                r.created_at,
                r.updated_at
            FROM job_reports r
            JOIN users u ON u.id = r.user_id
            {where_clause}
            ORDER BY datetime(r.date_end || 'T' || r.time_end) DESC, r.created_at DESC
            {limit_clause}
        """

        with self._get_connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        reports = [self._format_report_row(row) for row in rows]
        if not reports and limit_clause:  # If no results in last 5, try without limit to check older records
            with self._get_connection() as conn:
                rows = conn.execute(query.replace(limit_clause, ""), tuple(params)).fetchall()
            reports = [self._format_report_row(row) for row in rows]
        return reports

    def edit_report(
        self,
        report_id: int,
        project: Optional[str] = None,
        location: Optional[str] = None,
        date_begin: Optional[str] = None,
        time_begin: Optional[str] = None,
        date_end: Optional[str] = None,
        time_end: Optional[str] = None,
        comments: Optional[str] = None
    ) -> bool:
        """
        Edit a previously submitted report when:
        - The current user created the report.
        - The report was created within the last 5 days.
        """
        self._ensure_active()
        report_row = self._get_report_by_id(report_id)
        if not report_row:
            raise ValueError("Report not found.")

        if report_row["user_id"] != self.user_id:
            raise PermissionError("You can only edit your own reports.")

        created_at = datetime.fromisoformat(report_row["created_at"])
        if datetime.utcnow() - created_at > timedelta(days=5):
            return False

        new_project = project.strip() if project is not None else report_row["project"]
        new_location = location.strip() if location is not None else report_row["location"]
        new_comments = comments.strip() if comments is not None else report_row["comments"]

        if not new_project:
            raise ValueError("Project name cannot be empty.")
        if not new_location:
            raise ValueError("Location cannot be empty.")

        new_date_begin = self._normalize_date(date_begin) if date_begin is not None else report_row["date_begin"]
        new_time_begin = self._normalize_time(time_begin) if time_begin is not None else report_row["time_begin"]
        new_date_end = self._normalize_date(date_end) if date_end is not None else report_row["date_end"]
        new_time_end = self._normalize_time(time_end) if time_end is not None else report_row["time_end"]

        start_dt = self._combine_datetime(new_date_begin, new_time_begin)
        end_dt = self._combine_datetime(new_date_end, new_time_end)
        if end_dt <= start_dt:
            raise ValueError("End date/time must be after begin date/time.")

        new_hours = round((end_dt - start_dt).total_seconds() / 3600, 2)
        timestamp = self._utcnow()

        updates = {
            "project": new_project,
            "location": new_location,
            "date_begin": new_date_begin,
            "time_begin": new_time_begin,
            "date_end": new_date_end,
            "time_end": new_time_end,
            "hours": new_hours,
            "comments": new_comments,
            "updated_at": timestamp
        }

        with self._get_connection() as conn:
            fields = ", ".join(f"{key} = ?" for key in updates.keys())
            params = list(updates.values()) + [report_id]
            conn.execute(f"UPDATE job_reports SET {fields} WHERE id = ?", params)

        return True

    def dashboard_activity(self) -> Dict[str, Any]:
        """
        Aggregate technician activity for the last 6 days (including today).
        Returns structured data for dashboard visualization.
        """
        self._ensure_active()
        today = datetime.utcnow().date()
        start_date = today - timedelta(days=5)
        date_labels = [(start_date + timedelta(days=i)).isoformat() for i in range(6)]

        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    r.user_id,
                    r.project,
                    r.location,
                    r.date_begin,
                    r.time_begin,
                    r.date_end,
                    r.time_end,
                    r.hours,
                    u.first_name,
                    u.last_name
                FROM job_reports r
                JOIN users u ON u.id = r.user_id
                WHERE u.user_type = 'technician'
                  AND u.status = 'active'
                  AND date(r.date_end) >= ?
                  AND date(r.date_begin) <= ?
                """,
                (start_date.isoformat(), today.isoformat())
            ).fetchall()

        technician_summary: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            user_id = row["user_id"]
            full_name = f"{row['first_name']} {row['last_name']}".strip()
            start_dt = self._combine_datetime(row["date_begin"], row["time_begin"])
            end_dt = self._combine_datetime(row["date_end"], row["time_end"])

            allocations = self._allocate_hours_by_day(start_dt, end_dt)
            filtered_allocations = {
                day: hours for day, hours in allocations.items()
                if start_date.isoformat() <= day <= today.isoformat()
            }

            if user_id not in technician_summary:
                technician_summary[user_id] = {
                    "user_id": user_id,
                    "name": full_name,
                    "daily": {label: 0.0 for label in date_labels}
                }

            for day, hours in filtered_allocations.items():
                technician_summary[user_id]["daily"][day] = round(
                    technician_summary[user_id]["daily"].get(day, 0.0) + hours, 2
                )

        technicians_output = []
        for data in technician_summary.values():
            daily_hours = {day: round(hours, 2) for day, hours in data["daily"].items()}
            total_hours = round(sum(daily_hours.values()), 2)
            technicians_output.append({
                "user_id": data["user_id"],
                "name": data["name"],
                "daily_hours": daily_hours,
                "total_hours": total_hours
            })

        technicians_output.sort(key=lambda item: item["name"].lower())

        return {
            "start_date": start_date.isoformat(),
            "end_date": today.isoformat(),
            "date_range": date_labels,
            "generated_at": self._utcnow(),
            "technicians": technicians_output
        }

    def export_reports(self, report_list: List[Dict[str, Any]], file_format: str = "excel") -> str:
        """
        Export a list of reports to the specified format (excel, csv, json).
        Returns the absolute path to the exported file.
        """
        if not isinstance(report_list, list):
            raise ValueError("report_list must be a list of report dictionaries.")

        normalized_format = file_format.strip().lower()
        if normalized_format not in {"excel", "csv", "json"}:
            raise ValueError("file_format must be one of: 'excel', 'csv', 'json'.")

        if self.user_type != "admin":
            for report in report_list:
                if report.get("user_id") != self.user_id:
                    raise PermissionError("Technicians may export only their own reports.")

        export_dir = os.path.join(os.path.dirname(self.db_path), "exports")
        os.makedirs(export_dir, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")

        columns = [
            ("report_id", "Report ID"),
            ("user_id", "Technician ID"),
            ("technician_name", "Technician"),
            ("project", "Project"),
            ("location", "Location"),
            ("date_begin", "Date Begin"),
            ("time_begin", "Time Begin"),
            ("date_end", "Date End"),
            ("time_end", "Time End"),
            ("hours", "Hours"),
            ("comments", "Comments"),
            ("created_at", "Created At"),
            ("updated_at", "Updated At")
        ]

        if normalized_format == "json":
            file_path = os.path.join(export_dir, f"job_reports_{timestamp}.json")
            with open(file_path, "w", encoding="utf-8") as json_file:
                json.dump(report_list, json_file, ensure_ascii=False, indent=2)
            return os.path.abspath(file_path)

        if normalized_format == "csv":
            file_path = os.path.join(export_dir, f"job_reports_{timestamp}.csv")
            with open(file_path, "w", encoding="utf-8", newline="") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow([header for _, header in columns])
                for report in report_list:
                    writer.writerow([self._prepare_cell(report.get(key)) for key, _ in columns])
            return os.path.abspath(file_path)

        # Excel export
        file_path = os.path.join(export_dir, f"job_reports_{timestamp}.xlsx")
        rows = [[header for _, header in columns]]
        for report in report_list:
            rows.append([self._prepare_cell(report.get(key)) for key, _ in columns])
        self._write_excel_file(rows, file_path)
        return os.path.abspath(file_path)

    # ------------------------------------------------------------------------------------------------------------------
    # Authentication and lifecycle helpers
    # ------------------------------------------------------------------------------------------------------------------

    @property
    def is_admin(self) -> bool:
        return self.user_type == "admin"

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def last_created_user_credentials(self) -> Optional[Dict[str, Any]]:
        return self._last_created_user_credentials

    @property
    def last_created_report(self) -> Optional[Dict[str, Any]]:
        return self._last_created_report

    def _ensure_active(self) -> None:
        if self.status != "active":
            raise PermissionError("Inactive accounts cannot perform this action.")

    def _refresh_from_db(self) -> None:
        row = self._get_user_by_id(self.user_id)
        if row is None:
            raise ValueError("The referenced user does not exist in the database.")
        self.first_name = row["first_name"]
        self.last_name = row["last_name"]
        self.email = row["email"]
        self.job_position = row["job_position"]
        self.hour_salary = float(row["hour_salary"])
        self.can_drive = bool(row["can_drive"])
        self.status = row["status"]
        self.user_type = row["user_type"]
        self.created_at = row["created_at"]
        self.updated_at = row["updated_at"]

    # ------------------------------------------------------------------------------------------------------------------
    # Database setup and connections
    # ------------------------------------------------------------------------------------------------------------------

    @classmethod
    def _ensure_db(cls, db_path: Optional[str] = None) -> str:
        target_path = os.path.abspath(db_path or cls.DEFAULT_DB_PATH)
        directory = os.path.dirname(target_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

        if target_path not in cls._initialized_dbs:
            with sqlite3.connect(target_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON;")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_type TEXT NOT NULL CHECK(user_type IN ('admin','technician')),
                        first_name TEXT NOT NULL,
                        last_name TEXT NOT NULL,
                        email TEXT NOT NULL UNIQUE,
                        job_position TEXT NOT NULL,
                        hour_salary REAL NOT NULL CHECK(hour_salary >= 0),
                        can_drive INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL CHECK(status IN ('active','inactive')),
                        password_hash TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS job_reports (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        project TEXT NOT NULL,
                        location TEXT NOT NULL,
                        date_begin TEXT NOT NULL,
                        time_begin TEXT NOT NULL,
                        date_end TEXT NOT NULL,
                        time_end TEXT NOT NULL,
                        hours REAL NOT NULL,
                        comments TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_users_type_status ON users(user_type, status);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_reports_user_date ON job_reports(user_id, date_end);"
                )
            cls._initialized_dbs.add(target_path)
        return target_path

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _get_user_by_id(self, user_id: int) -> Optional[sqlite3.Row]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM users WHERE id = ?",
                (int(user_id),)
            )
            return cursor.fetchone()

    def _get_report_by_id(self, report_id: int) -> Optional[sqlite3.Row]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT
                    r.id AS report_id,
                    r.user_id,
                    r.project,
                    r.location,
                    r.date_begin,
                    r.time_begin,
                    r.date_end,
                    r.time_end,
                    r.hours,
                    r.comments,
                    r.created_at,
                    r.updated_at,
                    u.first_name,
                    u.last_name,
                    u.email
                FROM job_reports r
                JOIN users u ON u.id = r.user_id
                WHERE r.id = ?
                """,
                (int(report_id),)
            )
            return cursor.fetchone()

    # ------------------------------------------------------------------------------------------------------------------
    # Static and class helpers
    # ------------------------------------------------------------------------------------------------------------------

    @staticmethod
    def _generate_temporary_password(length: int = 12) -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@$?"
        return "".join(secrets.choice(alphabet) for _ in range(length))

    @staticmethod
    def _hash_password(password: str, salt: Optional[str] = None) -> str:
        if salt is None:
            salt = secrets.token_hex(16)
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            200000
        )
        return f"{salt}${derived.hex()}"

    @staticmethod
    def _verify_password(password: str, stored_value: str) -> bool:
        try:
            salt, hashed = stored_value.split("$", 1)
        except ValueError:
            return False
        computed = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            200000
        ).hex()
        return hmac.compare_digest(computed, hashed)

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"yes", "true", "1", "y"}
        raise ValueError("Boolean value expected for can_drive.")

    @staticmethod
    def _normalize_date(value: Optional[str], field_name: str = "date") -> str:
        if value is None:
            raise ValueError(f"{field_name} is required.")
        if isinstance(value, date):
            return value.isoformat()
        value_str = value.strip()
        if not value_str:
            raise ValueError(f"{field_name} cannot be empty.")
        try:
            parsed_date = date.fromisoformat(value_str)
        except ValueError as exc:
            raise ValueError(f"Invalid date format for {field_name}. Use YYYY-MM-DD.") from exc
        return parsed_date.isoformat()

    @staticmethod
    def _normalize_time(value: Optional[str], field_name: str = "time") -> str:
        if value is None:
            raise ValueError(f"{field_name} is required.")
        if isinstance(value, time):
            return value.strftime("%H:%M")
        value_str = value.strip()
        if not value_str:
            raise ValueError(f"{field_name} cannot be empty.")
        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                parsed_time = datetime.strptime(value_str, fmt).time()
                return parsed_time.strftime("%H:%M")
            except ValueError:
                continue
        raise ValueError(f"Invalid time format for {field_name}. Use HH:MM (24-hour format).")

    @staticmethod
    def _combine_datetime(date_str: str, time_str: str) -> datetime:
        return datetime.fromisoformat(f"{date_str}T{time_str}")

    @staticmethod
    def _allocate_hours_by_day(start_dt: datetime, end_dt: datetime) -> Dict[str, float]:
        if end_dt <= start_dt:
            return {}
        allocations: Dict[str, float] = {}
        current = start_dt
        while current < end_dt:
            next_midnight = datetime.combine(current.date() + timedelta(days=1), time.min)
            period_end = min(end_dt, next_midnight)
            hours = max(0.0, (period_end - current).total_seconds() / 3600)
            day_key = current.date().isoformat()
            allocations[day_key] = allocations.get(day_key, 0.0) + hours
            current = period_end
            if hours == 0.0:
                break
        if not allocations:
            allocations[start_dt.date().isoformat()] = 0.0
        return allocations

    @staticmethod
    def _prepare_cell(value: Any) -> Any:
        if value is None:
            return ""
        if isinstance(value, float):
            return round(value, 2)
        return value

    @staticmethod
    def _utcnow() -> str:
        return datetime.utcnow().replace(microsecond=0).isoformat()

    # ------------------------------------------------------------------------------------------------------------------
    # Report formatting and export helpers
    # ------------------------------------------------------------------------------------------------------------------

    def _format_report_row(self, row: sqlite3.Row) -> Dict[str, Any]:
        technician_name = f"{row['first_name']} {row['last_name']}".strip()
        return {
            "report_id": row["report_id"],
            "user_id": row["user_id"],
            "technician_name": technician_name,
            "technician_email": row["email"],
            "project": row["project"],
            "location": row["location"],
            "date_begin": row["date_begin"],
            "time_begin": row["time_begin"],
            "date_end": row["date_end"],
            "time_end": row["time_end"],
            "hours": round(float(row["hours"]), 2),
            "comments": row["comments"] or "",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"]
        }

    def _write_excel_file(self, rows: List[List[Any]], path: str) -> None:
        if not rows:
            rows = [[]]

        num_columns = max(len(row) for row in rows) if rows else 0
        num_rows = len(rows)
        last_column_letter = self._column_letter(num_columns - 1) if num_columns else "A"
        dimension = f"A1:{last_column_letter}{num_rows}" if num_columns else "A1"

        sheet_rows_xml = []
        for row_idx, row in enumerate(rows, start=1):
            cells_xml = []
            for col_idx in range(num_columns):
                value = row[col_idx] if col_idx < len(row) else ""
                cell_reference = f"{self._column_letter(col_idx)}{row_idx}"
                cells_xml.append(self._cell_xml(cell_reference, value))
            sheet_rows_xml.append(f"<row r=\"{row_idx}\">{''.join(cells_xml)}</row>")

        sheet_xml = (
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            "<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">"
            f"<dimension ref=\"{dimension}\"/>"
            "<sheetViews><sheetView workbookViewId=\"0\"/></sheetViews>"
            "<sheetFormatPr defaultRowHeight=\"15\"/>"
            f"<sheetData>{''.join(sheet_rows_xml)}</sheetData>"
            "</worksheet>"
        )

        workbook_xml = (
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            "<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" "
            "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">"
            "<fileVersion appName=\"xl\"/>"
            "<workbookPr date1904=\"false\"/>"
            "<bookViews><workbookView xWindow=\"0\" yWindow=\"0\" windowWidth=\"24000\" windowHeight=\"12000\"/></bookViews>"
            "<sheets><sheet name=\"Reports\" sheetId=\"1\" r:id=\"rId1\"/></sheets>"
            "</workbook>"
        )

        workbook_rels_xml = (
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
            "<Relationship Id=\"rId1\" "
            "Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" "
            "Target=\"worksheets/sheet1.xml\"/>"
            "<Relationship Id=\"rId2\" "
            "Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" "
            "Target=\"styles.xml\"/>"
            "</Relationships>"
        )

        styles_xml = (
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            "<styleSheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">"
            "<fonts count=\"1\"><font><sz val=\"11\"/><color theme=\"1\"/><name val=\"Calibri\"/><family val=\"2\"/></font></fonts>"
            "<fills count=\"1\"><fill><patternFill patternType=\"none\"/></fill></fills>"
            "<borders count=\"1\"><border><left/><right/><top/><bottom/><diagonal/></border></borders>"
            "<cellStyleXfs count=\"1\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\"/></cellStyleXfs>"
            "<cellXfs count=\"1\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\"/></cellXfs>"
            "<cellStyles count=\"1\"><cellStyle name=\"Normal\" xfId=\"0\" builtinId=\"0\"/></cellStyles>"
            "</styleSheet>"
        )

        content_types_xml = (
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
            "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
            "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
            "<Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/>"
            "<Override PartName=\"/xl/worksheets/sheet1.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>"
            "<Override PartName=\"/xl/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml\"/>"
            "<Override PartName=\"/docProps/core.xml\" ContentType=\"application/vnd.openxmlformats-package.core-properties+xml\"/>"
            "<Override PartName=\"/docProps/app.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.extended-properties+xml\"/>"
            "</Types>"
        )

        rels_xml = (
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
            "<Relationship Id=\"rId1\" "
            "Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" "
            "Target=\"xl/workbook.xml\"/>"
            "<Relationship Id=\"rId2\" "
            "Type=\"http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties\" "
            "Target=\"docProps/core.xml\"/>"
            "<Relationship Id=\"rId3\" "
            "Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties\" "
            "Target=\"docProps/app.xml\"/>"
            "</Relationships>"
        )

        core_props_xml = (
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            "<cp:coreProperties xmlns:cp=\"http://schemas.openxmlformats.org/package/2006/metadata/core-properties\" "
            "xmlns:dc=\"http://purl.org/dc/elements/1.1/\" "
            "xmlns:dcterms=\"http://purl.org/dc/terms/\" "
            "xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\">"
            "<dc:creator>Job Time Report System</dc:creator>"
            "<cp:lastModifiedBy>Job Time Report System</cp:lastModifiedBy>"
            f"<dcterms:created xsi:type=\"dcterms:W3CDTF\">{datetime.utcnow().isoformat()}Z</dcterms:created>"
            f"<dcterms:modified xsi:type=\"dcterms:W3CDTF\">{datetime.utcnow().isoformat()}Z</dcterms:modified>"
            "</cp:coreProperties>"
        )

        app_props_xml = (
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            "<Properties xmlns=\"http://schemas.openxmlformats.org/officeDocument/2006/extended-properties\" "
            "xmlns:vt=\"http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes\">"
            "<Application>Job Time Report System</Application>"
            "<DocSecurity>0</DocSecurity>"
            "<ScaleCrop>false</ScaleCrop>"
            "<HeadingPairs><vt:vector size=\"2\" baseType=\"variant\">"
            "<vt:variant><vt:lpstr>Worksheets</vt:lpstr></vt:variant>"
            "<vt:variant><vt:i4>1</vt:i4></vt:variant>"
            "</vt:vector></HeadingPairs>"
            "<TitlesOfParts><vt:vector size=\"1\" baseType=\"lpstr\">"
            "<vt:lpstr>Reports</vt:lpstr>"
            "</vt:vector></TitlesOfParts>"
            "<Company></Company>"
            "<LinksUpToDate>false</LinksUpToDate>"
            "<SharedDoc>false</SharedDoc>"
            "<HyperlinksChanged>false</HyperlinksChanged>"
            "<AppVersion>16.0300</AppVersion>"
            "</Properties>"
        )

        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types_xml)
            archive.writestr("_rels/.rels", rels_xml)
            archive.writestr("docProps/app.xml", app_props_xml)
            archive.writestr("docProps/core.xml", core_props_xml)
            archive.writestr("xl/workbook.xml", workbook_xml)
            archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
            archive.writestr("xl/styles.xml", styles_xml)
            archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)

    @staticmethod
    def _column_letter(index: int) -> str:
        if index < 0:
            return "A"
        result = ""
        while index >= 0:
            index, remainder = divmod(index, 26)
            result = chr(65 + remainder) + result
            index -= 1
        return result

    @staticmethod
    def _cell_xml(reference: str, value: Any) -> str:
        if value is None or value == "":
            return f"<c r=\"{reference}\"/>"
        if isinstance(value, (int, float)):
            return f"<c r=\"{reference}\"><v>{value}</v></c>"
        text = escape(str(value))
        text = text.replace("\n", "&#10;")
        return (
            f"<c r=\"{reference}\" t=\"inlineStr\">"
            f"<is><t xml:space=\"preserve\">{text}</t></is>"
            "</c>"
        )

    # ------------------------------------------------------------------------------------------------------------------
    # Class-level utilities for authentication/bootstrap
    # ------------------------------------------------------------------------------------------------------------------

    @classmethod
    def authenticate(cls, email: str, password: str, db_path: Optional[str] = None) -> "Account":
        """
        Authenticate a user with email and password, returning an Account instance on success.
        """
        db_file = cls._ensure_db(db_path)
        normalized_email = email.strip().lower()
        with sqlite3.connect(db_file) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM users WHERE email = ?", (normalized_email,))
            row = cursor.fetchone()
        if row is None:
            raise ValueError("Invalid email or password.")
        if not cls._verify_password(password, row["password_hash"]):
            raise ValueError("Invalid email or password.")
        if row["status"] != "active":
            raise PermissionError("Account is inactive.")
        return cls(
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

    @classmethod
    def create_root_admin(
        cls,
        first_name: str,
        last_name: str,
        email: str,
        job_position: str,
        hour_salary: float,
        can_drive: bool,
        password: str,
        db_path: Optional[str] = None
    ) -> "Account":
        """
        Bootstrap helper: create the initial administrator when none exists.
        """
        db_file = cls._ensure_db(db_path)
        with sqlite3.connect(db_file) as conn:
            conn.row_factory = sqlite3.Row
            existing_admin = conn.execute(
                "SELECT id FROM users WHERE user_type = 'admin' LIMIT 1"
            ).fetchone()
            if existing_admin:
                raise ValueError("An administrator already exists. Use regular create_user.")
            timestamp = cls._utcnow()
            password_hash = cls._hash_password(password)
            cursor = conn.execute(
                """
                INSERT INTO users (
                    user_type, first_name, last_name, email,
                    job_position, hour_salary, can_drive, status,
                    password_hash, created_at, updated_at
                )
                VALUES ('admin', ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    first_name.strip(),
                    last_name.strip(),
                    email.strip().lower(),
                    job_position.strip(),
                    float(hour_salary),
                    1 if cls._coerce_bool(can_drive) else 0,
                    password_hash,
                    timestamp,
                    timestamp
                )
            )
            new_admin_id = cursor.lastrowid
        return cls(
            user_id=new_admin_id,
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            email=email.strip().lower(),
            job_position=job_position.strip(),
            hour_salary=float(hour_salary),
            can_drive=cls._coerce_bool(can_drive),
            status="active",
            user_type="admin",
            db_path=db_file
        )

    # ------------------------------------------------------------------------------------------------------------------
    # Password management
    # ------------------------------------------------------------------------------------------------------------------

    def update_password(self, current_password: str, new_password: str) -> bool:
        """
        Update the current user's password after verifying the existing password.
        """
        row = self._get_user_by_id(self.user_id)
        if row is None:
            raise ValueError("User record not found.")
        if not self._verify_password(current_password, row["password_hash"]):
            raise PermissionError("Current password is incorrect.")
        new_hash = self._hash_password(new_password)
        timestamp = self._utcnow()
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (new_hash, timestamp, self.user_id)
            )
        self._refresh_from_db()
        return True

    def reset_password_for_user(self, target_user_id: int, new_password: str) -> bool:
        """
        Administrative helper: reset password for another user.
        """
        if not self.is_admin:
            raise PermissionError("Only administrators can reset passwords for other users.")
        target_row = self._get_user_by_id(target_user_id)
        if target_row is None:
            raise ValueError("Target user not found.")
        hashed = self._hash_password(new_password)
        timestamp = self._utcnow()
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (hashed, timestamp, target_user_id)
            )
        return True