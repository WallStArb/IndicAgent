<!-- generated-by: gsd-doc-writer -->
# External Links & Resources

**Version:** 2.8
**Status:** current
**Last Updated:** 2026-05-27

Curated reference links for libraries, APIs, trading theory, and research relevant to IndicAgent.
Add new links here as you discover useful resources — keeps everything in one place.

---

## Infrastructure & Data Storage

| Resource | URL | Notes |
|----------|-----|-------|
| TimescaleDB Docs | https://docs.timescale.com/ | Hypertables, continuous aggregates, compression |
| TimescaleDB Hyperfunctions | https://docs.timescale.com/use-timescale/latest/hyperfunctions/ | time_bucket, candlestick_agg, etc. |
| PostgreSQL Docs | https://www.postgresql.org/docs/ | JSONB, GIN indexes, partitioning |
| asyncpg Docs | https://magicstack.github.io/asyncpg/current/ | JSONB codec registration, connection pools |
| Redpanda Docs | https://docs.redpanda.com/ | Kafka-compatible stream broker (used in production) |
| Redis Streams (concepts) | https://redis.io/docs/latest/develop/data-types/streams/ | XREAD, XREADGROUP, consumer groups (conceptual reference) |

---

## Python Libraries

| Resource | URL | Notes |
|----------|-----|-------|
| Pydantic V2 Docs | https://docs.pydantic.dev/latest/ | Models, validators, Field aliases |
| Pydantic Validation Errors | https://github.com/pydantic/pydantic/blob/main/docs/errors/validation_errors.md | Error reference |
| structlog Docs | https://www.structlog.org/en/stable/ | Structured logging, processors, context vars |
| FastAPI Docs | https://fastapi.tiangolo.com/ | Endpoints, SSE, background tasks, deps |
| FastAPI SSE | https://fastapi.tiangolo.com/advanced/custom-response/ | StreamingResponse for SSE |
| Pytest Docs | https://docs.pytest.org/en/stable/ | Fixtures, parametrize, conftest |
| pytest-asyncio | https://pytest-asyncio.readthedocs.io/en/latest/ | Async test patterns |
| httpx Docs | https://www.python-httpx.org/ | Async HTTP client (used in tests) |
| Ruff Docs | https://docs.astral.sh/ruff/ | Linter/formatter rules reference |
| OpenTelemetry Python | https://opentelemetry-python.readthedocs.io/ | OTel SDK — replaces prometheus_client (Phase 83+) |

---

## AI / LLM

| Resource | URL | Notes |
|----------|-----|-------|
| Ollama API Docs | https://github.com/ollama/ollama/blob/main/docs/api.md | REST API, generate, chat endpoints |
| Ollama Docker Image | https://hub.docker.com/r/ollama/ollama | `ollama/ollama:rocm` used in production |
| OpenRouter Docs | https://openrouter.ai/docs | Fallback multi-model API (when Ollama disabled) |
| OpenRouter Models | https://openrouter.ai/models | Browse available models + context limits |
| LiteLLM | https://github.com/BerriAI/litellm | Unified LLM interface (reference; Phase 094 target) |
| Mixture of Agents (paper) | https://arxiv.org/abs/2406.04692 | Multi-agent synthesis patterns |
| Qwen3 Model Card | https://huggingface.co/Qwen/Qwen3-8B | Thinking mode, /no_think, num_predict behavior |

---

## IBKR / Broker APIs

| Resource | URL | Notes |
|----------|-----|-------|
| TWS API Docs | https://interactivebrokers.github.io/tws-api/ | Main reference — reqHistoricalData, reqMktData |
| TWS API GitHub | https://github.com/InteractiveBrokers/tws-api | Python client source |
| ib_async Docs | https://ib-api-reloaded.github.io/ib_async/ | Asyncio wrapper — IB(), Contract, util.run() (replaced ib_insync 2026-08-03, unmaintained since 2021) |
| ib_async GitHub | https://github.com/ib-api-reloaded/ib_async | Source + examples |
| IBKR Contract Search | https://interactivebrokers.github.io/tws-api/basic_contracts.html | Futures, FX, Crypto contract specs |
| IBKR Generic Tick Types | https://interactivebrokers.github.io/tws-api/tick_types.html | Tick 233 = RTVolume (futures only) |
| IBKR Gateway Docker | https://github.com/gnzsnz/ib-gateway | `ghcr.io/gnzsnz/ib-gateway:stable` — used in production |
| CME Group Specs | https://www.cmegroup.com/markets/equities/s-p/e-mini-s-p500.contractSpecs.html | ES contract specs |
| CME Group Product Finder | https://www.cmegroup.com/trading/products/ | All futures products, specs, hours |

---

## Trading Platforms & Learning Centers

| Resource | URL | Notes |
|----------|-----|-------|
| TrendSpider Learning Center | https://trendspider.com/learning-center/ | Comprehensive TA education — indicators, patterns, strategies, market concepts |

---

## Technical Analysis & Indicators

| Resource | URL | Notes |
|----------|-----|-------|
| TA-Lib Docs | https://ta-lib.github.io/ta-lib-python/ | Indicator formulas + Python API |
| Investopedia Indicators | https://www.investopedia.com/technical-analysis-4689657 | Conceptual reference for indicator logic |
| MACD Explained | https://www.investopedia.com/terms/m/macd.asp | Signal line, histogram, divergence |
| RSI Explained | https://www.investopedia.com/terms/r/rsi.asp | Overbought/oversold, divergence |
| Bollinger Bands | https://www.investopedia.com/terms/b/bollingerbands.asp | Squeeze, band walk |
| ATR Explained | https://www.investopedia.com/terms/a/atr.asp | Volatility measure, stop sizing |
| VWAP Explained | https://www.investopedia.com/terms/v/vwap.asp | Institutional usage, deviations |
| Anchored VWAP | https://school.stockcharts.com/doku.php?id=technical_indicators:anchored_vwap | AVWAP from swing points |
| Stochastic Oscillator | https://www.investopedia.com/terms/s/stochasticoscillator.asp | %K/%D, crossovers |
| ADX Indicator | https://www.investopedia.com/terms/a/adx.asp | Trend strength, DI+/DI- |
| Fibonacci Retracements | https://www.investopedia.com/terms/f/fibonacciretracement.asp | Key levels: 38.2, 50, 61.8 |
| Volume Profile | https://www.investopedia.com/terms/v/volume-by-price.asp | POC, VAH, VAL, HVN, LVN |
| Market Profile (Dalton) | https://www.investopedia.com/terms/m/marketprofile.asp | TPO, value area, initial balance |
| Keltner Channels | https://www.investopedia.com/terms/k/keltnerchannel.asp | ATR-based bands (used in squeeze) |

---

## Candlestick Patterns

| Resource | URL | Notes |
|----------|-----|-------|
| Candlestick Patterns (Investopedia) | https://www.investopedia.com/articles/technical/112601.asp | Overview of major patterns |
| Bullish Engulfing | https://www.investopedia.com/terms/b/bullish-engulfing-pattern.asp | Setup + reliability notes |
| Bearish Engulfing | https://www.investopedia.com/terms/b/bearish-engulfing-pattern.asp | — |
| Doji | https://www.investopedia.com/terms/d/doji.asp | Indecision, gravestone, dragonfly |
| Hammer / Hanging Man | https://www.investopedia.com/terms/h/hammer.asp | Body position relative to range |
| Morning Star / Evening Star | https://www.investopedia.com/terms/m/morningstar.asp | 3-bar reversal patterns |
| Three White Soldiers / Black Crows | https://www.investopedia.com/terms/t/three-white-soldiers.asp | Continuation/reversal |
| Shooting Star / Inverted Hammer | https://www.investopedia.com/terms/s/shootingstar.asp | Upper wick rejection |

---

## Chart Patterns

| Resource | URL | Notes |
|----------|-----|-------|
| Head & Shoulders | https://www.investopedia.com/terms/h/head-shoulders.asp | Measured move target |
| Double Top / Bottom | https://www.investopedia.com/terms/d/doubletop.asp | Neckline break trigger |
| Triangle Patterns | https://www.investopedia.com/terms/t/triangle.asp | Ascending, descending, symmetrical |
| Flag & Pennant | https://www.investopedia.com/terms/f/flag.asp | Continuation, measured move |
| Cup & Handle | https://www.investopedia.com/terms/c/cupandhandle.asp | Breakout target calculation |
| Measured Move | https://www.investopedia.com/terms/m/measured-move-down.asp | AB=CD projection |

---

## Smart Money Concepts (SMC / ICT)

| Resource | URL | Notes |
|----------|-----|-------|
| ICT Trading Concepts | https://tradingfinder.com/education/forex/trade-continuations-using-order-blocks/ | Order blocks, FVG, BOS/CHoCH |
| BOS / CHoCH Explained | https://www.investopedia.com/break-of-structure-bos-7106628 | Structure breaks and trend changes |
| Fair Value Gaps | https://www.investopedia.com/fair-value-gap-7975882 | Imbalance zones, fill behavior |
| Order Blocks | https://www.investopedia.com/order-block-trading-7499949 | Institutional entry zones |
| Liquidity Sweeps | https://internationaltradinginstitute.com/blog/liquidity-sweeps-entry-exit-strategies/ | Stop hunts, sweep-and-reclaim |
| ICT Killzones | https://www.investopedia.com/ict-killzone-7972043 | London, NY open session windows |
| Premium / Discount Zones | https://www.investopedia.com/premium-and-discount-zones-7973019 | Fib-based SMC price zones |
| AMD Cycle (Accumulation/Manipulation/Distribution) | https://www.investopedia.com/amd-trading-7972892 | ICT intraday cycle |
| Supply & Demand Zones | https://www.investopedia.com/terms/s/supply-zone.asp | Institutional order zones |

---

## Statistical / Quantitative Methods

| Resource | URL | Notes |
|----------|-----|-------|
| GARCH Model | https://www.investopedia.com/terms/g/garch.asp | Conditional heteroskedasticity, volatility clustering |
| arch Python Library | https://arch.readthedocs.io/en/latest/ | GARCH(1,1) implementation (used in I4) |
| Kalman Filter Explained | https://www.kalmanfilter.net/default.aspx | State estimation, trend filtering |
| HMM (Hidden Markov Models) | https://en.wikipedia.org/wiki/Hidden_Markov_model | Regime detection (used in I6) |
| hmmlearn Library | https://hmmlearn.readthedocs.io/en/latest/ | GaussianHMM for regime detection |
| BOCPD (Bayesian Changepoint) | https://arxiv.org/abs/0710.3742 | Online changepoint detection paper |
| Regime-Adaptive Trading (QuantInsti) | https://blog.quantinsti.com/regime-adaptive-trading-python | HMM + Random Forest regime trading |
| Systematic Trading (QuantInsti) | https://www.quantinsti.com/articles/systematic-trading/ | Strategy development reference |

---

## Trading Strategy References

| Resource | URL | Notes |
|----------|-----|-------|
| Institutional VWAP Usage | https://medium.com/@steady-turtle-trading/how-professional-traders-really-use-vwap-its-not-what-you-think-cff7bfd9ecd0 | Pro VWAP application |
| Gamma Exposure & Futures | https://menthorq.com/guide/gamma-levels-for-futures-trading/ | GEX levels for futures traders |
| Liquidity Hunt Strategies | https://internationaltradinginstitute.com/blog/liquidity-sweeps-entry-exit-strategies/ | Sweep + reclaim setups |
| Jim Simons / Renaissance Principles | https://hedgefundalpha.com/strategies/jim-simons-portfolio/ | Quantitative approach philosophy |
| Jim Simons Strategy (QuantVPS) | https://www.quantvps.com/blog/jim-simons-trading-strategy | Pattern-based systematic trading |

---

## Dashboard & Frontend

| Resource | URL | Notes |
|----------|-----|-------|
| Next.js Docs | https://nextjs.org/docs | App router, SSE in API routes |
| React Docs | https://react.dev/ | Hooks, state, effects |
| Tailwind CSS | https://tailwindcss.com/docs | Utility classes reference |
| shadcn/ui | https://ui.shadcn.com/ | Component library (if used) |
| EventSource MDN | https://developer.mozilla.org/en-US/docs/Web/API/EventSource | Browser SSE client API |
| Recharts | https://recharts.org/en-US/ | Charting library for React |

---

## Observability / Monitoring

| Resource | URL | Notes |
|----------|-----|-------|
| OpenTelemetry Python | https://opentelemetry-python.readthedocs.io/ | OTel SDK — metrics, traces, spans (prometheus_client fully removed Phase 83) |
| Prometheus Docs | https://prometheus.io/docs/introduction/overview/ | Metrics model, querying (Prometheus still scrapes OTel endpoint) |
| Grafana Docs | https://grafana.com/docs/grafana/latest/ | Dashboard at :3001, alerting |
| structlog Docs | https://www.structlog.org/en/stable/ | Structured logging for Python |

---

## Research Papers

| Paper | URL | Relevance |
|-------|-----|-----------|
| Mixture of Agents | https://arxiv.org/abs/2406.04692 | Multi-agent synthesis for LLM intelligence |
| BOCPD (Adams & MacKay 2007) | https://arxiv.org/abs/0710.3742 | Bayesian online changepoint detection (I6) |
| Attention Is All You Need | https://arxiv.org/abs/1706.03762 | Transformer architecture background |

---

## Adding New Links

When you find a useful resource, add it to the appropriate section above. Format:

```
| Display Name | https://url | Brief note about why it's useful |
```

Keep notes concise — one line max. If a resource warrants more context, create a file in `docs/ideas/` and link to it from here.
