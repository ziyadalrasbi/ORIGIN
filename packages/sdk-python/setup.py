"""Setup for ORIGIN Python SDK."""

from setuptools import find_packages, setup

setup(
    name="origin-sdk",
    version="0.1.0",
    description="ORIGIN API Python SDK",
    packages=find_packages(),
    install_requires=[
        "requests>=2.31.0",
    ],
    python_requires=">=3.11",
)

