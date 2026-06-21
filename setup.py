"""Fallback setup.py for legacy tooling support."""
from setuptools import setup, find_packages

setup(
    name="lexed",
    version="0.1.0",
    description="A terminal-based lexicon editor for low-resource languages",
    author="Mwadime",
    python_requires=">=3.10",
    packages=find_packages(),
    install_requires=["textual>=0.50.0"],
    entry_points={
        "console_scripts": [
            "lexed=lexed.app:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Console",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Topic :: Text Processing :: Linguistic",
    ],
)
