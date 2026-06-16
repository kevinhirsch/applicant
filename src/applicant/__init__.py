"""Applicant — autonomous, human-in-the-loop job-application agent.

Hexagonal architecture: the pure core (``applicant.core``) defines the domain and
the port interfaces (``applicant.ports``); adapters (``applicant.adapters``) and
the delivery layer (``applicant.app``) live at the edges. Dependencies point
inward only (see docs/architecture.md, NFR-ARCH-1).
"""

from applicant.version import __version__

__all__ = ["__version__"]
