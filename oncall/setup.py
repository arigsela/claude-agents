"""
Setup configuration for oncall-agent-poc
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="oncall-agent-poc",
    version="0.1.0",
    author="Your Organization DevOps",
    author_email="devops@your-org.com",
    description="Intelligent on-call troubleshooting agent using Claude Agent SDK",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/your-org/oncall-agent-poc",
    project_urls={
        "Bug Tracker": "https://github.com/your-org/oncall-agent-poc/issues",
        "Documentation": "https://github.com/your-org/oncall-agent-poc/docs",
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: System :: Monitoring",
        "Topic :: System :: Systems Administration",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.11",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "oncall-agent=agent.oncall_agent:main",
        ],
    },
)