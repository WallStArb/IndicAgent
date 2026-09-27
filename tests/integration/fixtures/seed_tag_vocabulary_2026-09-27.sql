--
-- PostgreSQL database dump
--

\restrict Ray5YeLWMAIxwg7vUNzHqAcpscgSsClbclblXmViZrDXk80uwFTftH31XhPermw

-- Dumped from database version 18.4
-- Dumped by pg_dump version 18.6 (Ubuntu 18.6-0ubuntu0.26.04.1)

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
-- Data for Name: tag_vocabulary; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.tag_vocabulary VALUES ('vol_proxy', 'exposure', 'Instrument whose primary exposure IS equity-index implied volatility (a VIX-futures-linked ETF/ETN). Distinct from the sensitivity-category `volatility` tag, which is an empirically-measured beta against a volatility factor_series and can be contradicted/expired by TagCalibrator -- this is a definitional exposure claim, a permanent human seed prior, never measured or auto-expired.', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('single_name_equity', 'exposure', 'Individual company stock, not a diversified basket -- carries idiosyncratic earnings/M&A/litigation risk that basket-level exposure tags do not capture. Soft behavioral flag, not GICS scheme membership.', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('wireless_infrastructure', 'macro_driver', 'Wireless/telecom network buildout demand -- carrier capex, 5G rollout, subscriber/data-usage growth. Links cell-tower REITs, wireless carriers, and mobile-chip designers on a shared economic driver that neither real_estate nor communication_services sector strings capture as a cross-sectional tag.', 'IYZ', 'beta_regression', 252, 0.2, 180);
INSERT INTO public.tag_vocabulary VALUES ('commodity_uranium', 'exposure', 'Uranium/nuclear fuel cycle exposure -- distinct commodity complex from industrial or precious metals, driven by nuclear power buildout and fuel-supply-chain geopolitics (Russian/Kazakh production share), not the industrial-production or China-demand cycle that industrial metals share.', 'URA', 'beta_regression', 252, 0.2, 180);
INSERT INTO public.tag_vocabulary VALUES ('eq_low_vol', 'exposure', 'Equity minimum/low-volatility factor tilt -- split out of the coarse eq_factor tag (Phase 174 D-06) so low-vol exposure is individually identifiable for factor-specific IC stratification. eq_factor is retained as the parent-level label; this tag refines, not replaces, it.', 'USMV', 'beta_regression', 252, 0.2, 180);
INSERT INTO public.tag_vocabulary VALUES ('eq_momentum', 'exposure', 'Equity momentum factor tilt -- split out of the coarse eq_factor tag (Phase 174 D-06) so momentum exposure is individually identifiable for factor-specific IC stratification. eq_factor is retained as the parent-level label; this tag refines, not replaces, it.', 'MTUM', 'beta_regression', 252, 0.2, 180);
INSERT INTO public.tag_vocabulary VALUES ('eq_quality', 'exposure', 'Equity quality factor tilt -- split out of the coarse eq_factor tag (Phase 174 D-06) so quality exposure is individually identifiable for factor-specific IC stratification. eq_factor is retained as the parent-level label; this tag refines, not replaces, it.', 'QUAL', 'beta_regression', 252, 0.2, 180);
INSERT INTO public.tag_vocabulary VALUES ('fi_mbs', 'exposure', 'Agency mortgage-backed securities', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('fi_intl', 'exposure', 'Non-US developed-market bonds', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('rate_sensitive', 'sensitivity', 'Price moves meaningfully with interest rate changes', 'TLT', 'beta_regression', 252, 0.2, 180);
INSERT INTO public.tag_vocabulary VALUES ('dollar_strength', 'macro_driver', 'Inversely or directly correlated to USD index', 'UUP', 'beta_regression', 252, 0.2, 180);
INSERT INTO public.tag_vocabulary VALUES ('fi_treasury', 'exposure', 'US Treasury bonds', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('china_demand', 'macro_driver', 'Sensitive to Chinese economic activity and demand', 'FXI', 'beta_regression', 252, 0.2, 180);
INSERT INTO public.tag_vocabulary VALUES ('credit_risk', 'sensitivity', 'Signals credit spread widening and tightening cycles', 'HYG-IEF', 'beta_regression', 252, 0.2, 180);
INSERT INTO public.tag_vocabulary VALUES ('inflation', 'sensitivity', 'Proxy for inflation expectations or real rate shifts', 'TIP-IEF', 'beta_regression', 252, 0.2, 180);
INSERT INTO public.tag_vocabulary VALUES ('yield_curve', 'sensitivity', 'Sensitive to yield curve shape — steepening or flattening', 'IEF-SHY', 'beta_regression', 252, 0.2, 180);
INSERT INTO public.tag_vocabulary VALUES ('oil_price', 'macro_driver', 'Correlated to crude oil price direction', 'XLE-SPY', 'beta_regression', 252, 0.2, 180);
INSERT INTO public.tag_vocabulary VALUES ('volatility', 'sensitivity', 'Tracks or proxies VIX and implied volatility term structure', 'SPY_REALIZED_VOL', 'beta_regression', 252, 0.2, 180);
INSERT INTO public.tag_vocabulary VALUES ('equity_beta', 'sensitivity', 'Sensitivity (OLS beta) of the instrument''s daily returns to the broad equity market (SPY); general equity-market-beta, empirically measured.', 'SPY', 'beta_regression', 252, 0.2, 180);
INSERT INTO public.tag_vocabulary VALUES ('semi_cycle', 'macro_driver', 'Tracks semiconductor inventory and capex cycle', 'SMH', 'beta_regression', 252, 0.2, 180);
INSERT INTO public.tag_vocabulary VALUES ('yen_carry', 'macro_driver', 'Influenced by JPY carry trade positioning', 'FXY', 'beta_regression', 252, 0.2, 180);
INSERT INTO public.tag_vocabulary VALUES ('em_flows', 'macro_driver', 'Driven by institutional capital flows into and out of emerging markets', 'EEM', 'beta_regression', 252, 0.2, 180);
INSERT INTO public.tag_vocabulary VALUES ('eq_broad', 'exposure', 'Broad equity market index', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('eq_sector', 'exposure', 'Single GICS sector equity basket', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('eq_growth', 'exposure', 'Growth-tilted equity factor', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('eq_value', 'exposure', 'Value-tilted equity factor', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('eq_factor', 'exposure', 'Systematic factor tilt — momentum, quality, low-vol', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('eq_small_cap', 'exposure', 'Small-cap equity market segment', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('eq_sub_sector', 'exposure', 'Focused equity sub-sector within a GICS sector', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('fi_credit_ig', 'exposure', 'Investment grade corporate bonds', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('fi_credit_hy', 'exposure', 'High yield corporate bonds', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('fi_em', 'exposure', 'Emerging market debt', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('fi_tips', 'exposure', 'Inflation-linked Treasury bonds', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('fi_muni', 'exposure', 'Municipal bonds', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('fi_preferred', 'exposure', 'Preferred stock — hybrid debt/equity capital', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('fi_short_duration', 'exposure', 'Short-duration or cash-equivalent fixed income', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('commodity_energy', 'exposure', 'Energy commodity — oil, gas, pipeline', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('commodity_metals', 'exposure', 'Metals commodity — gold, silver, copper', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('real_estate', 'exposure', 'Real estate investment trust basket', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('crypto', 'exposure', 'Cryptocurrency spot or futures exposure', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('intl_em', 'exposure', 'Emerging market equities, broad or single-country', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('intl_developed', 'exposure', 'Developed market equities outside the US', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('commodity_energy_crude', 'exposure', 'Crude oil futures or equity proxy — WTI/Brent price beta', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('commodity_energy_pipeline', 'exposure', 'Midstream energy infrastructure — income, not crude spot beta', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('commodity_metals_precious', 'exposure', 'Precious metals — gold, silver, platinum; monetary/inflation store of value', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('benchmark', 'signal_role', 'Reference instrument for an asset class or market segment', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('sector_rotation', 'signal_role', 'Captures institutional sector allocation flows', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('factor_rotation', 'signal_role', 'Captures systematic factor tilt shifts', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('leading_indicator', 'signal_role', 'Historically leads the broader market at inflection points', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('regime_classifier', 'signal_role', 'Used to classify the prevailing macro or market regime', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('stress_indicator', 'signal_role', 'Signals financial stress or liquidity deterioration', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('spread_leg', 'signal_role', 'One leg of a monitored spread or ratio pair', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('sentiment', 'signal_role', 'Measures risk appetite or speculative positioning', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('risk_on', 'factor_regime', 'Outperforms in risk-on and expansion regimes', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('risk_off', 'factor_regime', 'Outperforms in risk-off, contraction, and flight-to-quality', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('defensive', 'factor_regime', 'Low-beta — attracts flows in late-cycle and drawdown environments', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('growth', 'factor_regime', 'Outperforms when growth factor dominates', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('value', 'factor_regime', 'Outperforms when value factor dominates', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('momentum', 'factor_regime', 'Outperforms when trend-following regime is active', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('breadth', 'signal_role', 'Measures participation width across the market', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('eq_income', 'exposure', 'Income-oriented equity strategy — high dividend yield, quality screen', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('early_cycle', 'cycle_position', 'Outperforms in early economic expansion — credit-driven, domestically exposed', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('mid_cycle', 'cycle_position', 'Outperforms in mid-cycle growth — earnings-driven, capex and tech spending', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('late_cycle', 'cycle_position', 'Outperforms in late expansion — commodity prices elevated, margins peak', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('recession', 'cycle_position', 'Outperforms in contraction — defensive cash flows, flight to quality', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('commodity_metals_industrial', 'exposure', 'Industrial base metals — copper, aluminum, zinc; global demand proxy', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('commodity_agri', 'exposure', 'Agricultural commodities — grains, softs, livestock', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('commodity_broad', 'exposure', 'Broad commodity index — diversified across energy, metals, agriculture', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('fx_usd', 'exposure', 'US dollar index — long USD vs basket of major currencies', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('fx_major', 'exposure', 'Major developed-market currency vs USD — EUR, JPY, GBP, CHF', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('fx_em', 'exposure', 'Emerging market currency basket vs USD', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('fx_commodity', 'exposure', 'Commodity-linked currency vs USD — AUD, CAD, NZD; proxy for China/metals/agri demand', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('transports', 'exposure', 'Transportation sector — rails, trucking, air freight, marine; leading-indicator cyclical', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('defensive_yield', 'exposure', 'High-dividend-yield equity — contrarian/mean-reversion factor distinct from dividend-quality (SCHD)', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('factor_market_neutral', 'exposure', 'Long-short, dollar-neutral factor exposure — near-zero equity beta by construction (e.g. anti-beta)', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('high_beta', 'exposure', 'Liquid, non-leveraged high-volatility equity factor — elevated beta without structural rebalancing decay', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('convertible', 'exposure', 'Convertible bonds — hybrid equity-optionality/credit/duration exposure', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('fed_policy', 'macro_driver', 'Driven by Fed funds rate expectations and FOMC decisions [Owner: project_owner]', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('geopolitical', 'macro_driver', 'Driven by geopolitical risk — defense budgets, conflict escalation, sanctions [Owner: project_owner]', NULL, 'definitional', 252, NULL, 180);
INSERT INTO public.tag_vocabulary VALUES ('clean_energy', 'exposure', 'Renewable/clean-tech energy exposure -- driven by interest rates, capital costs, and climate policy, structurally the opposite macro driver from commodity_energy_crude''s oil/gas price beta, not a sub-category of it.', 'ICLN', 'beta_regression', 252, 0.2, 180);


--
-- PostgreSQL database dump complete
--

\unrestrict Ray5YeLWMAIxwg7vUNzHqAcpscgSsClbclblXmViZrDXk80uwFTftH31XhPermw

