"""Port interfaces (master spec §6). Interfaces ONLY — no implementations.

``driving`` ports are inbound (use-case facing, invoked by the UI/schedulers);
``driven`` ports are outbound (infrastructure facing, implemented by adapters).

These Protocols are FROZEN once Foundation completes: downstream phase agents
implement adapters against them but must not edit the port definitions.
"""
