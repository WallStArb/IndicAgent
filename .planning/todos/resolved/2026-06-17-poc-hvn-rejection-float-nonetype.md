# Bug: trad_POCRejection + trad_HVNRejection — float(NoneType) crash → 0 signals

**Discovered:** 2026-06-17 during Phase 127 re-emit replay
**Severity:** High — both plugins contribute 0 signals to training corpus

## Symptom
```
[plugin error] trad_POCRejection (RTYZ6/4h): float() argument must be a string or a real number, not 'NoneType'
[plugin error] trad_HVNRejection (ESZ6/4h): float() argument must be a string or a real number, not 'NoneType'
```
Concentrated on 4h and 1d timeframes. Plugin is registered and reaches `frame_trade()` but crashes there.

## Likely cause
`trade_framer.py:343` — `return float(poc_htf), float(vah_htf), float(val_htf)` — HTF VP fields
(`htf_1h_poc_price`, `htf_1h_vah`, `htf_1h_val`) are None on early historical bars or on
higher timeframes where HTF lookup has no data. No None guard before the float() cast.

## Fix
In `_get_htf_vp()` (trade_framer.py ~line 339-343), guard against None before casting:
```python
if poc_htf is None or vah_htf is None or val_htf is None:
    return None, None, None
return float(poc_htf), float(vah_htf), float(val_htf)
```
Then verify callers handle `(None, None, None)` return correctly.

## Impact
- 0 POCRejection signals in Phase 127 replay corpus
- 0 HVNRejection signals in Phase 127 replay corpus
- Both plugins are genuinely valuable setups; their absence is training data loss
- Fix + re-replay these two plugins only (use `--setups trad_POCRejection,trad_HVNRejection`)
