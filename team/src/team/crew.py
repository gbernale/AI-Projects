import importlib
import subprocess
import sys
from typing import Dict


def _ensure_pip() -> None:
    """Bootstrap pip when running inside minimal uv environments."""
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
        subprocess.check_call([sys.executable, "-m", "ensurepip", "--upgrade"])
        importlib.invalidate_caches()

    if importlib.util.find_spec("pip") is None:
        raise RuntimeError(
            "pip bootstrap failed; please install pip into this Python environment manually."
        )


def _install_missing_packages(packages: Dict[str, str]) -> None:
    """Install missing third-party dependencies on first import."""
    missing = []
    for package, import_name in packages.items():
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(package)

    if not missing:
        return

    _ensure_pip()

    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"Unable to install required packages: {', '.join(missing)}"
        ) from exc


_install_missing_packages(
    {
        "crewai": "crewai",
        "pydantic": "pydantic",
        "gradio": "gradio",
        "anthropic": "anthropic",
        "openai": "openai",
    }
)

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task



@CrewBase
class EngineeringTeam():
    """EngineeringTeam crew"""

    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    @agent
    def engineering_lead(self) -> Agent:
        return Agent(
            config=self.agents_config['engineering_lead'],
            verbose=True,
        )

    @agent
    def backend_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config['backend_engineer'],
            verbose=True,
            allow_code_execution=False,
            max_execution_time=1500, 
            max_retry_limit=3 
        )
    
    @agent
    def frontend_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config['frontend_engineer'],
            verbose=True,
        )
    
    @agent
    def test_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config['test_engineer'],
            verbose=True,
            allow_code_execution=False,
            max_execution_time=1500, 
            max_retry_limit=3 
        )

    @task
    def design_task(self) -> Task:
        return Task(
            config=self.tasks_config['design_task']
        )

    @task
    def code_task(self) -> Task:
        return Task(
            config=self.tasks_config['code_task'],
        )

    @task
    def frontend_task(self) -> Task:
        return Task(
            config=self.tasks_config['frontend_task'],
        )

    @task
    def test_task(self) -> Task:
        return Task(
            config=self.tasks_config['test_task'],
        )   

    @crew
    def crew(self) -> Crew:
        """Creates the research crew"""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
