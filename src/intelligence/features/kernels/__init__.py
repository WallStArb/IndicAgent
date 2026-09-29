"""Feature kernels: one module per feature origin.

Origins (D-25): price dynamics, volume and flow, SMC, VP/SR, calendar, macro, regime.
Each module exports `KERNELS: tuple[Kernel, ...]` and nothing else is registered anywhere;
`registry.discover_kernels()` finds the modules by name.

Contract: kernels are pure. Declared inputs are bar fields or other kernels' outputs, aligned
on the same row grid at their availability time (a daily or higher-timeframe input is aligned
by the caller to the row at which it becomes available, never earlier). No kernels live here
until 186-12.
"""
