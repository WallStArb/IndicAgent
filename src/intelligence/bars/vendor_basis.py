"""The basis tolerance unit (phase 185 plan 33; data layer integrity design section 6).

The vendor basis run check (`alpaca_basis_run`, Alpaca against IBKR) is retired (todo 623): IBKR
is removed, Massive is the yardstick and Alpaca the continuation, and a level break at the
Massive to Alpaca seam is judged by `unexplained_seam` and `split_continuity`.
"""

from __future__ import annotations

BP = 1e4  # the basis tolerance unit; the single definition (todo 527)
