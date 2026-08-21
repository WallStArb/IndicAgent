--
-- PostgreSQL database dump
--

\restrict FgWa0OL1DcfDyZHnHUqneKHftGzXPovB7MEoLiTl6iO9AEJ8XMGD9E8MM31GaXx

-- Dumped from database version 18.4
-- Dumped by pg_dump version 18.4 (Ubuntu 18.4-0ubuntu0.26.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: tag_vocabulary; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.tag_vocabulary (tag, category, description, factor_series, measurement_type, lookback_days, loading_threshold, half_life_days) FROM stdin;
wireless_infrastructure	macro_driver	Wireless/telecom network buildout demand -- carrier capex, 5G rollout, subscriber/data-usage growth. Links cell-tower REITs, wireless carriers, and mobile-chip designers on a shared economic driver that neither real_estate nor communication_services sector strings capture as a cross-sectional tag.	\N	beta_regression	252	\N	180
rate_sensitive	sensitivity	Price moves meaningfully with interest rate changes	TLT	beta_regression	252	0.2	180
dollar_strength	macro_driver	Inversely or directly correlated to USD index	UUP	beta_regression	252	0.2	180
fi_treasury	exposure	US Treasury bonds	\N	definitional	252	\N	180
china_demand	macro_driver	Sensitive to Chinese economic activity and demand	FXI	beta_regression	252	0.2	180
credit_risk	sensitivity	Signals credit spread widening and tightening cycles	HYG-IEF	beta_regression	252	0.2	180
inflation	sensitivity	Proxy for inflation expectations or real rate shifts	TIP-IEF	beta_regression	252	0.2	180
yield_curve	sensitivity	Sensitive to yield curve shape — steepening or flattening	IEF-SHY	beta_regression	252	0.2	180
oil_price	macro_driver	Correlated to crude oil price direction	XLE-SPY	beta_regression	252	0.2	180
volatility	sensitivity	Tracks or proxies VIX and implied volatility term structure	SPY_REALIZED_VOL	beta_regression	252	0.2	180
equity_beta	sensitivity	Sensitivity (OLS beta) of the instrument's daily returns to the broad equity market (SPY); general equity-market-beta, empirically measured.	SPY	beta_regression	252	0.2	180
semi_cycle	macro_driver	Tracks semiconductor inventory and capex cycle	SMH	beta_regression	252	0.2	180
yen_carry	macro_driver	Influenced by JPY carry trade positioning	FXY	beta_regression	252	0.2	180
em_flows	macro_driver	Driven by institutional capital flows into and out of emerging markets	EEM	beta_regression	252	0.2	180
eq_broad	exposure	Broad equity market index	\N	definitional	252	\N	180
eq_sector	exposure	Single GICS sector equity basket	\N	definitional	252	\N	180
eq_growth	exposure	Growth-tilted equity factor	\N	definitional	252	\N	180
eq_value	exposure	Value-tilted equity factor	\N	definitional	252	\N	180
eq_factor	exposure	Systematic factor tilt — momentum, quality, low-vol	\N	definitional	252	\N	180
eq_small_cap	exposure	Small-cap equity market segment	\N	definitional	252	\N	180
eq_sub_sector	exposure	Focused equity sub-sector within a GICS sector	\N	definitional	252	\N	180
fi_credit_ig	exposure	Investment grade corporate bonds	\N	definitional	252	\N	180
fi_credit_hy	exposure	High yield corporate bonds	\N	definitional	252	\N	180
fi_em	exposure	Emerging market debt	\N	definitional	252	\N	180
fi_tips	exposure	Inflation-linked Treasury bonds	\N	definitional	252	\N	180
fi_muni	exposure	Municipal bonds	\N	definitional	252	\N	180
fi_preferred	exposure	Preferred stock — hybrid debt/equity capital	\N	definitional	252	\N	180
fi_short_duration	exposure	Short-duration or cash-equivalent fixed income	\N	definitional	252	\N	180
commodity_energy	exposure	Energy commodity — oil, gas, pipeline	\N	definitional	252	\N	180
commodity_metals	exposure	Metals commodity — gold, silver, copper	\N	definitional	252	\N	180
real_estate	exposure	Real estate investment trust basket	\N	definitional	252	\N	180
crypto	exposure	Cryptocurrency spot or futures exposure	\N	definitional	252	\N	180
intl_em	exposure	Emerging market equities, broad or single-country	\N	definitional	252	\N	180
intl_developed	exposure	Developed market equities outside the US	\N	definitional	252	\N	180
commodity_energy_crude	exposure	Crude oil futures or equity proxy — WTI/Brent price beta	\N	definitional	252	\N	180
commodity_energy_pipeline	exposure	Midstream energy infrastructure — income, not crude spot beta	\N	definitional	252	\N	180
commodity_metals_precious	exposure	Precious metals — gold, silver, platinum; monetary/inflation store of value	\N	definitional	252	\N	180
benchmark	signal_role	Reference instrument for an asset class or market segment	\N	definitional	252	\N	180
sector_rotation	signal_role	Captures institutional sector allocation flows	\N	definitional	252	\N	180
factor_rotation	signal_role	Captures systematic factor tilt shifts	\N	definitional	252	\N	180
leading_indicator	signal_role	Historically leads the broader market at inflection points	\N	definitional	252	\N	180
regime_classifier	signal_role	Used to classify the prevailing macro or market regime	\N	definitional	252	\N	180
stress_indicator	signal_role	Signals financial stress or liquidity deterioration	\N	definitional	252	\N	180
spread_leg	signal_role	One leg of a monitored spread or ratio pair	\N	definitional	252	\N	180
sentiment	signal_role	Measures risk appetite or speculative positioning	\N	definitional	252	\N	180
single_name_equity	exposure	Individual company stock, not a diversified basket -- carries idiosyncratic earnings/M&A/litigation risk that basket-level exposure tags do not capture. Soft behavioral flag, not GICS scheme membership.	\N	beta_regression	252	\N	180
risk_on	factor_regime	Outperforms in risk-on and expansion regimes	\N	definitional	252	\N	180
risk_off	factor_regime	Outperforms in risk-off, contraction, and flight-to-quality	\N	definitional	252	\N	180
defensive	factor_regime	Low-beta — attracts flows in late-cycle and drawdown environments	\N	definitional	252	\N	180
growth	factor_regime	Outperforms when growth factor dominates	\N	definitional	252	\N	180
value	factor_regime	Outperforms when value factor dominates	\N	definitional	252	\N	180
momentum	factor_regime	Outperforms when trend-following regime is active	\N	definitional	252	\N	180
breadth	signal_role	Measures participation width across the market	\N	definitional	252	\N	180
eq_income	exposure	Income-oriented equity strategy — high dividend yield, quality screen	\N	definitional	252	\N	180
commodity_uranium	exposure	Uranium/nuclear fuel cycle exposure -- distinct commodity complex from industrial or precious metals, driven by nuclear power buildout and fuel-supply-chain geopolitics (Russian/Kazakh production share), not the industrial-production or China-demand cycle that industrial metals share.	\N	beta_regression	252	\N	180
early_cycle	cycle_position	Outperforms in early economic expansion — credit-driven, domestically exposed	\N	definitional	252	\N	180
mid_cycle	cycle_position	Outperforms in mid-cycle growth — earnings-driven, capex and tech spending	\N	definitional	252	\N	180
late_cycle	cycle_position	Outperforms in late expansion — commodity prices elevated, margins peak	\N	definitional	252	\N	180
recession	cycle_position	Outperforms in contraction — defensive cash flows, flight to quality	\N	definitional	252	\N	180
commodity_metals_industrial	exposure	Industrial base metals — copper, aluminum, zinc; global demand proxy	\N	definitional	252	\N	180
commodity_agri	exposure	Agricultural commodities — grains, softs, livestock	\N	definitional	252	\N	180
commodity_broad	exposure	Broad commodity index — diversified across energy, metals, agriculture	\N	definitional	252	\N	180
fx_usd	exposure	US dollar index — long USD vs basket of major currencies	\N	definitional	252	\N	180
fx_major	exposure	Major developed-market currency vs USD — EUR, JPY, GBP, CHF	\N	definitional	252	\N	180
fx_em	exposure	Emerging market currency basket vs USD	\N	definitional	252	\N	180
fx_commodity	exposure	Commodity-linked currency vs USD — AUD, CAD, NZD; proxy for China/metals/agri demand	\N	definitional	252	\N	180
transports	exposure	Transportation sector — rails, trucking, air freight, marine; leading-indicator cyclical	\N	definitional	252	\N	180
defensive_yield	exposure	High-dividend-yield equity — contrarian/mean-reversion factor distinct from dividend-quality (SCHD)	\N	definitional	252	\N	180
factor_market_neutral	exposure	Long-short, dollar-neutral factor exposure — near-zero equity beta by construction (e.g. anti-beta)	\N	definitional	252	\N	180
high_beta	exposure	Liquid, non-leveraged high-volatility equity factor — elevated beta without structural rebalancing decay	\N	definitional	252	\N	180
convertible	exposure	Convertible bonds — hybrid equity-optionality/credit/duration exposure	\N	definitional	252	\N	180
fed_policy	macro_driver	Driven by Fed funds rate expectations and FOMC decisions [Owner: project_owner]	\N	definitional	252	\N	180
geopolitical	macro_driver	Driven by geopolitical risk — defense budgets, conflict escalation, sanctions [Owner: project_owner]	\N	definitional	252	\N	180
clean_energy	exposure	Renewable/clean-tech energy exposure -- driven by interest rates, capital costs, and climate policy, structurally the opposite macro driver from commodity_energy_crude's oil/gas price beta, not a sub-category of it.	\N	beta_regression	252	\N	180
\.


--
-- PostgreSQL database dump complete
--

\unrestrict FgWa0OL1DcfDyZHnHUqneKHftGzXPovB7MEoLiTl6iO9AEJ8XMGD9E8MM31GaXx

