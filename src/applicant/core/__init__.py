"""Pure domain core. NO I/O, NO framework imports (NFR-ARCH-1).

Contains entities, the §7 application state machine, the load-bearing domain
rules, domain events, and domain errors. Everything here depends only on the
standard library and the port *interfaces* in ``applicant.ports``.
"""
