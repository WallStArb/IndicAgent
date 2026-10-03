--
-- PostgreSQL database dump
--

\restrict gIq1Mrp9gdE2WiRfTrWY9dMzepuelhpNxm9TSESPrNXwPHzfBEWHzddqUAmH2C9

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
-- Data for Name: controlled_vocabulary; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.controlled_vocabulary VALUES ('regime_hmm', 'trending_down', 'Trending Down', 'Strong sustained downward price movement (lowest emission-mean HMM state)', 1, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_hmm', 'transition_down', 'Transition Down', 'Weakening or early-stage downward movement between ranging and trending_down', 2, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_hmm', 'ranging', 'Ranging', 'No sustained directional movement; mean-reverting price action', 3, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_hmm', 'transition_up', 'Transition Up', 'Weakening or early-stage upward movement between ranging and trending_up', 4, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_hmm', 'trending_up', 'Trending Up', 'Strong sustained upward price movement (highest emission-mean HMM state)', 5, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_cross_sectional_equity', 'low_bull', 'Low Vol / Bull', 'Low cross-sectional volatility, bullish breadth', 1, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_cross_sectional_equity', 'low_neutral', 'Low Vol / Neutral', 'Low cross-sectional volatility, neutral breadth', 2, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_cross_sectional_equity', 'low_bear', 'Low Vol / Bear', 'Low cross-sectional volatility, bearish breadth', 3, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_cross_sectional_equity', 'mid_bull', 'Mid Vol / Bull', 'Mid cross-sectional volatility, bullish breadth', 4, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_cross_sectional_equity', 'mid_neutral', 'Mid Vol / Neutral', 'Mid cross-sectional volatility, neutral breadth', 5, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_cross_sectional_equity', 'mid_bear', 'Mid Vol / Bear', 'Mid cross-sectional volatility, bearish breadth', 6, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_cross_sectional_equity', 'high_bull', 'High Vol / Bull', 'High cross-sectional volatility, bullish breadth', 7, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_cross_sectional_equity', 'high_neutral', 'High Vol / Neutral', 'High cross-sectional volatility, neutral breadth', 8, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_cross_sectional_equity', 'high_bear', 'High Vol / Bear', 'High cross-sectional volatility, bearish breadth', 9, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_cross_sectional_rates', 'flat_tight', 'Flat / Tight', 'Flat yield curve, tight credit spreads', 1, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_cross_sectional_rates', 'flat_wide', 'Flat / Wide', 'Flat yield curve, wide credit spreads', 2, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_cross_sectional_rates', 'steep_tight', 'Steep / Tight', 'Steep yield curve, tight credit spreads', 3, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_cross_sectional_rates', 'steep_wide', 'Steep / Wide', 'Steep yield curve, wide credit spreads', 4, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_cross_sectional_rates', 'inverted_tight', 'Inverted / Tight', 'Inverted yield curve, tight credit spreads', 5, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_cross_sectional_rates', 'inverted_wide', 'Inverted / Wide', 'Inverted yield curve, wide credit spreads', 6, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('timeframe', '1m', '1 Minute', 'One-minute bar timeframe', 1, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('timeframe', '5m', '5 Minute', 'Five-minute bar timeframe', 2, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('timeframe', '15m', '15 Minute', 'Fifteen-minute bar timeframe', 3, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('timeframe', '1h', '1 Hour', 'One-hour bar timeframe', 4, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('asset_class', 'equity', 'Equity', 'Exchange-traded equity/ETF instrument', 1, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('asset_class', 'futures', 'Futures', 'Exchange-traded futures contract', 2, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('asset_class', 'fx', 'FX', 'Foreign exchange spot/forward instrument', 3, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('tier', '0_atomic', 'Atomic', 'Base-level computed feature with no dependency on other features', 1, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('tier', '1_interaction', 'Interaction', 'Feature derived from an interaction between two or more atomic features', 2, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('tier', '2_theory', 'Theory', 'Feature encoding a higher-level theoretical construct', 3, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_volatility', 'calm', 'Calm', 'Lowest realized-vol / vol-of-vol HMM state', 1, false, '2026-08-09 10:48:53.545033+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_volatility', 'elevated', 'Elevated', 'Middle realized-vol / vol-of-vol HMM state (K=3 only)', 2, false, '2026-08-09 10:48:53.545033+00');
INSERT INTO public.controlled_vocabulary VALUES ('regime_volatility', 'turbulent', 'Turbulent', 'Highest realized-vol / vol-of-vol HMM state', 3, false, '2026-08-09 10:48:53.545033+00');
INSERT INTO public.controlled_vocabulary VALUES ('timeframe', '1d', '1 Day', 'One-day bar timeframe', 6, false, '2026-07-18 00:15:48.608099+00');
INSERT INTO public.controlled_vocabulary VALUES ('timeframe', '4h', '4 Hour', 'Four-hour bar timeframe', 5, false, '2026-08-16 02:16:12.73381+00');


--
-- Data for Name: vocabulary_group; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.vocabulary_group VALUES ('regime_hmm', 'trending', 'Trending', 'Either trending direction (excludes transition and ranging states)', 1);
INSERT INTO public.vocabulary_group VALUES ('regime_hmm', 'transition', 'Transition', 'Either transition direction (excludes trending and ranging states)', 2);
INSERT INTO public.vocabulary_group VALUES ('regime_hmm', 'bullish_bias', 'Bullish Bias', 'States with upward directional bias (transition_up or trending_up)', 3);
INSERT INTO public.vocabulary_group VALUES ('regime_hmm', 'bearish_bias', 'Bearish Bias', 'States with downward directional bias (transition_down or trending_down)', 4);
INSERT INTO public.vocabulary_group VALUES ('regime_cross_sectional_equity', 'low_vol', 'Low Volatility', 'Low cross-sectional volatility tier (all directions)', 1);
INSERT INTO public.vocabulary_group VALUES ('regime_cross_sectional_equity', 'mid_vol', 'Mid Volatility', 'Mid cross-sectional volatility tier (all directions)', 2);
INSERT INTO public.vocabulary_group VALUES ('regime_cross_sectional_equity', 'high_vol', 'High Volatility', 'High cross-sectional volatility tier (all directions)', 3);
INSERT INTO public.vocabulary_group VALUES ('regime_cross_sectional_equity', 'bull', 'Bull', 'Bullish breadth direction (all volatility tiers)', 4);
INSERT INTO public.vocabulary_group VALUES ('regime_cross_sectional_equity', 'neutral', 'Neutral', 'Neutral breadth direction (all volatility tiers)', 5);
INSERT INTO public.vocabulary_group VALUES ('regime_cross_sectional_equity', 'bear', 'Bear', 'Bearish breadth direction (all volatility tiers)', 6);
INSERT INTO public.vocabulary_group VALUES ('regime_cross_sectional_rates', 'flat', 'Flat', 'Flat yield curve shape (both spread widths)', 1);
INSERT INTO public.vocabulary_group VALUES ('regime_cross_sectional_rates', 'steep', 'Steep', 'Steep yield curve shape (both spread widths)', 2);
INSERT INTO public.vocabulary_group VALUES ('regime_cross_sectional_rates', 'inverted', 'Inverted', 'Inverted yield curve shape (both spread widths)', 3);
INSERT INTO public.vocabulary_group VALUES ('regime_cross_sectional_rates', 'tight', 'Tight', 'Tight credit spread width (all curve shapes)', 4);
INSERT INTO public.vocabulary_group VALUES ('regime_cross_sectional_rates', 'wide', 'Wide', 'Wide credit spread width (all curve shapes)', 5);
INSERT INTO public.vocabulary_group VALUES ('timeframe', 'intraday_plus_hourly', 'Intraday + Hourly', 'The 1m/5m/15m/1h subset used by signal-coverage and feature-validation auditing; deliberately excludes 1d/4h (todo 327 preserved this pre-existing scoping without evidence it was accidental).', 1);


--
-- Data for Name: vocabulary_group_member; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.vocabulary_group_member VALUES ('regime_hmm', 'trending', 'trending_down');
INSERT INTO public.vocabulary_group_member VALUES ('regime_hmm', 'trending', 'trending_up');
INSERT INTO public.vocabulary_group_member VALUES ('regime_hmm', 'transition', 'transition_down');
INSERT INTO public.vocabulary_group_member VALUES ('regime_hmm', 'transition', 'transition_up');
INSERT INTO public.vocabulary_group_member VALUES ('regime_hmm', 'bullish_bias', 'transition_up');
INSERT INTO public.vocabulary_group_member VALUES ('regime_hmm', 'bullish_bias', 'trending_up');
INSERT INTO public.vocabulary_group_member VALUES ('regime_hmm', 'bearish_bias', 'transition_down');
INSERT INTO public.vocabulary_group_member VALUES ('regime_hmm', 'bearish_bias', 'trending_down');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_equity', 'low_vol', 'low_bull');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_equity', 'low_vol', 'low_neutral');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_equity', 'low_vol', 'low_bear');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_equity', 'mid_vol', 'mid_bull');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_equity', 'mid_vol', 'mid_neutral');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_equity', 'mid_vol', 'mid_bear');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_equity', 'high_vol', 'high_bull');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_equity', 'high_vol', 'high_neutral');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_equity', 'high_vol', 'high_bear');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_equity', 'bull', 'low_bull');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_equity', 'bull', 'mid_bull');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_equity', 'bull', 'high_bull');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_equity', 'neutral', 'low_neutral');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_equity', 'neutral', 'mid_neutral');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_equity', 'neutral', 'high_neutral');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_equity', 'bear', 'low_bear');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_equity', 'bear', 'mid_bear');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_equity', 'bear', 'high_bear');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_rates', 'flat', 'flat_tight');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_rates', 'flat', 'flat_wide');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_rates', 'steep', 'steep_tight');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_rates', 'steep', 'steep_wide');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_rates', 'inverted', 'inverted_tight');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_rates', 'inverted', 'inverted_wide');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_rates', 'tight', 'flat_tight');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_rates', 'tight', 'steep_tight');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_rates', 'tight', 'inverted_tight');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_rates', 'wide', 'flat_wide');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_rates', 'wide', 'steep_wide');
INSERT INTO public.vocabulary_group_member VALUES ('regime_cross_sectional_rates', 'wide', 'inverted_wide');
INSERT INTO public.vocabulary_group_member VALUES ('timeframe', 'intraday_plus_hourly', '1m');
INSERT INTO public.vocabulary_group_member VALUES ('timeframe', 'intraday_plus_hourly', '5m');
INSERT INTO public.vocabulary_group_member VALUES ('timeframe', 'intraday_plus_hourly', '15m');
INSERT INTO public.vocabulary_group_member VALUES ('timeframe', 'intraday_plus_hourly', '1h');


--
-- PostgreSQL database dump complete
--

\unrestrict gIq1Mrp9gdE2WiRfTrWY9dMzepuelhpNxm9TSESPrNXwPHzfBEWHzddqUAmH2C9

