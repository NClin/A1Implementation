"""
A1 - Agentic Smart Contract Exploit Generation System
For Defensive Cybersecurity and Vulnerability Research

This implementation is based on the research paper:
"AI Agent Smart Contract Exploit Generation" by Arthur Gervais and Liyi Zhou
"""

__version__ = "0.1.0"
__author__ = "Your Security Team"

from .agent import A1Agent
from .tools import *
from .config import Config

__all__ = [
    "A1Agent",
    "Config",
] 