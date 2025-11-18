#!/usr/bin/env python
import importlib
import os
import subprocess
import sys
import warnings
from datetime import datetime


def _ensure_pip() -> None:
    """Bootstrap pip inside minimal environments created without it."""
    if importlib.util.find_spec("pip") is not None:
        return

    try:
        import ensurepip
    except ImportError as exc:
        raise RuntimeError(
            "pip is required to install dependencies but is not available in this Python installation."
        ) from exc

    ensurepip.bootstrap(upgrade=True)
    importlib.invalidate_caches()

    if importlib.util.find_spec("pip") is None:
        # Some environments need the CLI invocation to place pip in site-packages.
        subprocess.check_call([sys.executable, "-m", "ensurepip", "--upgrade"])
        importlib.invalidate_caches()

    if importlib.util.find_spec("pip") is None:
        raise RuntimeError(
            "pip bootstrap failed; please install pip into this Python environment manually."
        )


def _install_missing_packages() -> None:
    required = {
        "crewai": "crewai",
        "pydantic": "pydantic",
        "gradio": "gradio",
        "anthropic": "anthropic",
        "openai": "openai",
        "pysbd": "pysbd",
    }

    missing = [
        package for package, import_name in required.items()
        if importlib.util.find_spec(import_name) is None
    ]
    if not missing:
        return

    _ensure_pip()

    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"Unable to install required packages: {', '.join(missing)}"
        ) from exc


_install_missing_packages()

from team.crew import EngineeringTeam

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# Create output directory if it doesn't exist
os.makedirs('output', exist_ok=True)

requirements = """
Name: Job Time Report system.
A very easy and intuitive system that allow techniciens to report the daily time worked in projects.
The system should allow the creation of two types of users: 1. Administrator,  2. Technician.
The system should allow Admin to create other admin and technicien users. Technicien users will be available to fill up the form -job hours report-
Each user should have the following information: ID, First name, last Name, email address, job position, hour salary, drive [yes/no], status [active/inactive] 
The form or screen to report hours should have the following information: User Id is current user, name, project, location, date begin, time begin, date end, time end, number of hours
should be calculated, comments. The user should see by default the last 5 reports.
The admin can see the report of all the techniciens, however, the technicien can only see his own records.
The system should be able to allow users to select a range of dates and then present the results in the screen and also alow the user to print, download or export the data as Excel file.
The system should be  present a dashboard with activity all all technicien during the last 6 days.  Users should be able to edit and update job report records of the last 5 days.
The UI should be Responsive Web Design, mobile-optimized. Use a free database.
"""
module_name = "accounts.py"
class_name = "Account"


def run():
    """ce
    Run the research crew.
    """
    inputs = {
        'requirements': requirements,
        'module_name': module_name,
        'class_name': class_name
    }

    # Create and run the crew
    result = EngineeringTeam().crew().kickoff(inputs=inputs)


if __name__ == "__main__":
    run()
