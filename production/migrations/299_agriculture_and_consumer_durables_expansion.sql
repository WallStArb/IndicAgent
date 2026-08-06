-- Migration 299: cross-sector single-name/basket expansion -- 153 -> 229 instruments (76 new).
--
-- Sixteen waves of gaps found after migration 296's sector-orthogonality sweep, all from one
-- continuous session (agriculture, consumer durables, staples depth, energy/clean energy,
-- crypto, transportation, mega-cap tech/media, biotech, healthcare care-delivery, telecom,
-- a new wireless_infrastructure cross-cutting tag, homebuilders, a broad growth/cyclical/
-- defensive sweep, utilities/water-utility depth, and fixed-income/FX peer-group depth) --
-- consolidated into one migration per user feedback 2026-08-05 (same "don't leave multiple
-- files for one task" guidance already applied to migration 296):
--
-- 1. Agriculture had ZERO single-name equity or equity-basket exposure -- only DBA (a futures
--    basket ETF) existed, leaving `commodity_agri` a peer group of N=1 (statistically meaningless
--    for cross_sectional_regime_model.py's breadth/dispersion computation, same class of problem
--    as the other N=1 tag_filter groups flagged 2026-08-05). Three single names picked for
--    genuinely distinct business models within ag, not redundant ones: NTR (fertilizer/potash
--    producer -- input-cost exposure), ADM (grain processing/trading -- toll-margin business,
--    distinct from fertilizer production), CTVA (seeds/crop-protection -- IP/biotech-driven).
--    BG (Bunge) deliberately excluded -- same processing/trading business model as ADM,
--    redundant. MOO added as an equity-basket ag ETF, complementing DBA's futures-basket
--    construction (same distinction already established between DIA/SPY and IYT's peer ETFs).
--    VEGI and single-commodity futures ETFs (WEAT/SOYB/CORN) excluded -- redundant with
--    MOO/DBA respectively, no single-commodity-futures precedent exists elsewhere in this
--    corpus (DBC/DBA already cover diversified commodity baskets).
--
-- 2. consumer_discretionary had only MCD, HD, TSLA -- no traditional (non-EV) auto
--    manufacturer, no appliance manufacturer, no home-furnishings retail. Added GM and F
--    (both, not just one -- two auto names gives real cross-sectional dispersion within the
--    sub-sector instead of a single point estimate, and they are not fully redundant: distinct
--    legacy fleet/commercial-truck mix and balance-sheet risk profiles). Both are genuinely
--    distinct from TSLA's EV/growth-stock behavior: legacy union labor costs, ICE-to-EV
--    transition risk, classic consumer-confidence cyclicality. WHR (Whirlpool) added as the
--    pure-play traditional appliance manufacturer -- distinct durable-goods manufacturing
--    exposure not covered by any retail name. WSM (Williams-Sonoma) added -- luxury/
--    design-conscious home-goods retail, a distinct customer/price-elasticity profile from
--    HD's DIY/contractor base, not redundant despite both being "home" themed. VCR added as
--    a broader-cap-range (small/mid/large) construction alternative to XLY's S&P-500-only
--    sector SPDR -- same category of distinction already accepted for DIA vs SPY, smaller
--    effect size but consistent with that precedent. FDIS excluded -- near-duplicate of VCR's
--    methodology (broad-cap passive discretionary basket), no second alternative-construction
--    ETF needed for one sector.
--
-- SN (SharkNinja) considered and explicitly excluded -- IPO 2023, ~2-3yr trading history.
-- Real caveat, not a hard rule: TSLA (IPO 2010, ~16yr history) is already in the corpus well
-- short of the stated 20yr depth target without objection, so short history alone doesn't
-- disqualify a name -- SN was excluded on user judgment call (2026-08-05), not a blanket policy.
--
-- 3. consumer_staples already had 5 names (PG/KO/PEP/WMT/COST) from migrations 287/296 --
--    genuinely new sub-type still missing: tobacco (litigation risk, near-monopoly pricing
--    power, extreme FCF/dividend yield -- nothing else in the corpus resembles this risk
--    profile). Added PM and MO -- despite common lineage (PM spun off from Altria in 2008),
--    the split survives as a genuine distinction: PM is international/ex-US with currency and
--    foreign-regulatory exposure plus the IQOS heated-tobacco growth story, MO is pure
--    domestic declining-volume/pricing-power. VDC added (broader cap-range construction,
--    same distinction already accepted for VCR vs XLY). RSPG added -- equal-weight, not
--    cap-weighted, the most genuinely distinct of the ETF options: staples is a mega-cap-
--    dominated sector (PG/KO/PEP/WMT/COST all huge), so equal-weighting materially changes
--    basket composition (more mid-cap exposure, no single-name dominance) rather than just
--    being another provider's cap-weighted basket. IYK excluded -- same broad-cap-range
--    approach as VDC, no second alternative-construction ETF needed for one sector (same
--    discipline as dropping FDIS in the consumer-discretionary wave above).
--
-- CL (Colgate-Palmolive) considered and EXCLUDED -- hard collision, not a judgment call.
-- `instruments.symbol` is a literal primary key (`instruments_pkey` btree(symbol)) and CL is
-- already registered as the WTI Crude Oil futures contract (asset_class='futures'). No
-- symbol-aliasing scheme exists in this schema to disambiguate a stock/futures collision on
-- the same ticker -- pending a user decision on whether that's worth building for one name.
--
-- 4. energy already had XLE/XOM/CVX/COP/SLB/AMLP (supermajors, pure-play E&P, oilfield
--    services, midstream MLP basket) -- comprehensive on the traditional side. New
--    tag_vocabulary entry `clean_energy` added -- genuinely distinct macro driver from
--    `commodity_energy_crude` (interest rates/capex costs/climate policy vs. commodity
--    prices), the same class of justification as `commodity_uranium`. EPD added as the
--    midstream single-name complement to AMLP's basket (same basket+single-name pattern as
--    GDX+NEM, URA+CCJ elsewhere in the corpus -- AMLP had zero single-name complement).
--    ICLN added as the broad clean-energy basket -- the actual orthogonality win here, since
--    renewables run on the opposite macro driver from the rest of the energy sector. FSLR
--    (utility-scale solar manufacturing/hardware), ENPH (residential solar/storage,
--    tech-software business model distinct from FSLR's hardware manufacturing), and GEV
--    (wind turbines/grid electrification, an industrial-conglomerate profile distinct from
--    both) added as genuinely distinct clean-energy sub-types. TAN excluded -- too narrow/
--    correlated with ICLN's own solar weighting, same discipline as dropping FDIS/IYK above.
--    NEE (already in the corpus, migration 296) is a regulated-utility/renewables hybrid, not
--    a pure clean-energy play -- FSLR/ENPH/GEV are the genuinely pure-play complement.
--    AMLP's `contract_details->>'sector'` backfilled to 'energy_midstream' -- it predates that
--    convention (same gap the other session's migration 296 fixed for KRE).
--
-- 5. Crypto exposure was IBIT only (spot Bitcoin ETF). Checked for the same class of ticker
--    collision that blocked CL/Colgate -- BTC and ETH are genuinely free, no existing rows.
--    Added ETHA (spot Ethereum -- a genuinely different underlying from Bitcoin, not just
--    another fee-variant wrapper: distinct smart-contract/DeFi risk profile). Skipped FBTC,
--    Grayscale's BTC and ETH minis, and FETH -- all near-perfectly-correlated fee-variant
--    wrappers around the same two spot prices IBIT/ETHA already capture; adding them creates
--    no cross-sectional signal, unlike GDX+NEM or URA+CCJ which track genuinely different
--    sub-businesses. Added MSTR (leveraged corporate Bitcoin treasury proxy -- operating
--    business + convertible-debt leverage + NAV premium/discount dynamics, a distinct
--    mechanism from spot exposure), COIN (exchange/custody -- revenue scales with trading
--    volume x volatility, not just directional price), and MARA+RIOT (industrial-scale BTC
--    mining -- hash-rate/energy-cost/halving-cycle economics, a third distinct driver; kept
--    both despite correlation to each other for the same GM+F cross-sectional-dispersion
--    reasoning). HOOD explicitly excluded -- crypto is one revenue stream among options/
--    equities trading, so it's actually a retail-brokerage/fintech proxy more than a crypto
--    pure-play; that's a different, currently-ungapped sector, not folded into crypto here.
--
-- 6. transports had IYT/UNP/UPS/DAL (basket, rail, parcel, airline) -- decent sub-type spread
--    already, extended further given genuine sub-type distinctness survives at this depth
--    (same precedent as financials' 10 names). Added XTN (equal-weight transportation basket,
--    same distinct-methodology case as RSPG vs XLP/VDC) and JETS (pure-play airline/aircraft/
--    airport basket, complements DAL the same way GDX complements NEM). Added CSX (direct UNP
--    rail competitor, but distinct: East Coast/coal-heavy vs UNP's West Coast/intermodal mix --
--    same cross-sectional-dispersion logic as GM+F), JBHT (intermodal truck-to-rail transfer,
--    an asset-lighter business model distinct from owned-rail-network capital intensity),
--    ODFL (pure LTL regional trucking, distinct again from intermodal), R/Ryder (fleet
--    leasing/rental services -- a B2B services model insulated from freight volume the way
--    carriers aren't, the most distinct of the trucking-adjacent picks), UBER (platform/
--    gig-economy take-rate model, not an asset-heavy carrier at all -- also the only
--    "platform" exposure anywhere in this corpus), and FDX (reconsidering this migration's
--    own earlier "UPS over FDX" call now that CSX+UNP/MARA+RIOT establish direct-competitor
--    pairs as an accepted pattern -- both parcel carriers now included). FTXR excluded --
--    blends freight with personal-transit/automotive names, re-importing the GM/F/TSLA signal
--    already covered elsewhere rather than adding anything new; dilutive, not additive.
--
--    Note: this brings transports-related names to 12 total (IYT/JETS/XTN + UNP/CSX/JBHT/
--    ODFL/R/UPS/FDX/DAL/UBER) -- deeper than financials or industrials (10 each), now the
--    single deepest theme in the universe. Each individual pick clears the genuine-
--    distinctness bar on its own merits; flagged for awareness of the resulting sector-depth
--    imbalance, same concern raised for discretionary/financials/industrials earlier.
--
-- 7. Mega-cap tech/media gap, found auditing absences directly (not a "thin sector," a real
--    oversight): GOOGL and META were completely absent despite AAPL/MSFT/AMZN/TSLA/NVDA all
--    being present -- two of the largest companies on earth, missing. Added both. This is also
--    the real answer to "media" exposure -- digital-advertising-driven media (GOOGL/META) is
--    structurally different from DIS/NFLX/CMCSA's subscription/content-carriage economics,
--    which were already covered. Also added ASML (semiconductor lithography equipment --
--    distinct from AVGO/NVDA's chip design and TSM's foundry manufacturing: ASML sells TO the
--    foundries, driven by fab capex cycles not end-chip demand), CRM (enterprise SaaS --
--    recurring-revenue economics distinct from every hardware/semi name in tech), and CRWD
--    (cybersecurity single-name complement to CIBR, which existed only as a basket -- same gap
--    shape as AMLP/GDX/URA before their complements were added).
--
-- 8. Biotech was VRTX only -- one name gives no cross-sectional depth in a notoriously
--    binary/high-variance sub-sector (clinical-trial-outcome-driven). Added GILD (Gilead) --
--    large, stable HIV/antiviral franchise, genuinely distinct from VRTX's concentrated-
--    single-franchise binary-catalyst risk profile (picked over REGN, which shares VRTX's
--    same concentrated-franchise shape too closely).
--
-- 9. Healthcare care-delivery layer was entirely absent -- payer (UNH), pharma majors
--    (JNJ/MRK/PFE/LLY), medtech (ISRG), and biotech (VRTX/GILD) covered, but nothing for
--    facility operators or a second payer archetype. Added ELV (second payer -- regional Blue
--    Cross Blue Shield model, distinct from UNH's Optum data-driven model, same CSX+UNP
--    dispersion logic), CVS (a genuine third payer archetype -- vertically-integrated retail
--    pharmacy + Aetna insurance + primary care, not redundant with UNH/ELV despite also being
--    "insurance"), HCA (largest hospital/acute-care operator, the care-delivery-facilities
--    sub-type missing entirely), THC (second hospital operator -- ambulatory-surgery-center-
--    concentrated vs HCA's broader acute-care network, same dispersion logic again), DOCS
--    (clinician professional-network/platform, ad/subscription revenue) and TDOC (actual
--    virtual-care-visit delivery -- genuinely distinct business model from DOCS despite both
--    being "telehealth"). IHF added as a genuinely different ETF construction from XLV -- not
--    just a cap-range variant like VHT, but a narrower payer/provider-services-only sub-index
--    (XLV blends insurers+medtech+pharma+providers together). VHT added for the same
--    broader-cap-range case already accepted for VCR/VDC.
--
--    Note: this brings healthcare-related single names to 14 total -- past every other
--    sector, including the previously-deepest transports (12) and industrials (11). Every
--    individual pick clears the genuine-distinctness bar; flagged given the size of the jump.
--
-- 10. Biotech depth, user-confirmed 2026-08-05 (AskUserQuestion) after flagging the resulting
--     concentration explicitly: healthcare goes to 19 single names (~10% of the 198-instrument
--     universe) with this wave. XBI/IBB already existed (added by the parallel session, cap-
--     weighted/mega-cap vs equal-weight/small-cap biotech basket pair) -- FBT skipped as a
--     third redundant equal-weight construction. AMGN reconsidered and kept excluded -- the
--     other session's original "VRTX over AMGN, too diversified-pharma-like" reasoning still
--     holds. Added REGN (ophthalmology/inflammatory-concentrated blockbuster -- a third
--     distinct disease-area concentration alongside VRTX's cystic fibrosis and GILD's
--     antiviral), CRSP (clinical-stage/pre-commercial gene-editing -- a genuinely distinct
--     risk tier, binary regulatory/trial risk vs every commercial-stage name above), BNTX
--     (mRNA platform -- its own distinct modality, plus a distinct capital-structure risk:
--     large net-cash position funding speculative pipeline), RVMD (second clinical-stage name,
--     targeted-oncology-small-molecule modality distinct from CRSP's gene-editing platform),
--     and EXEL (commercial-stage but single-drug-dependent -- a middle tier between GILD's
--     diversification and CRSP/RVMD's pure speculation). ARKG explicitly excluded, user-
--     confirmed: actively managed, so its returns are driven by manager discretion/turnover,
--     structurally inconsistent with every other instrument in this corpus (systematic index
--     construction or company fundamentals, never manager judgment calls).
--
-- 11. Telecom -- XLC exists but is now heavily diluted by GOOGL/META (added in wave 7 above),
--     leaving no pure-play carrier/infrastructure construction. Added IYZ (pure-play telecom,
--     excludes internet/media giants -- same narrower-sub-index case as IHF vs XLV), XTL
--     (equal-weight, shifts concentration toward mid-cap equipment providers -- same
--     distinct-methodology case as RSPG), and VOX (broader cap-range, consistent with the
--     VCR/VDC/VHT precedent applied to every other sector touched this session). Added QCOM --
--     wireless modem/5G chip design and licensing, a genuinely distinct 5th semiconductor
--     sub-type (design/AVGO, AI/NVDA, foundry/TSM, equipment/ASML, now mobile-wireless/QCOM)
--     that also bridges into telecom infrastructure.
--
-- 12. wireless_infrastructure -- new tag, user-prompted 2026-08-05 ("no AMT?" / "should it
--     also have communications tags?"). Not cosmetic: cross_sectional_regime_model.py builds
--     its peer groups entirely from instrument_tags, never from contract_details->>'sector' --
--     confirmed no telecom/wireless tag existed in tag_vocabulary at all, so AMT (cell-tower
--     REIT, migration 296) had zero tag connecting it to VZ/T/TMUS/QCOM for any
--     telecom-demand-driven cross-sectional read, despite tower-lease revenue being
--     structurally tied to carrier capex and wireless-subscriber growth -- a real economic
--     co-movement distinct from AMT's rate_sensitive/REIT mechanics. Applied to the natural
--     peer group: AMT (tower REIT), VZ/T/TMUS (carriers), QCOM (wireless chips), IYZ/XTL
--     (pure-play telecom baskets). AMT's real_estate primary sector classification is
--     unchanged -- this is an additive cross-cutting tag, not a reclassification.
--
-- 13. Homebuilders -- DHI and XHB already existed (migration 296, DHI picked as largest
--     builder by volume). Added ITB (cap-weighted, pure-play concentration in top-tier
--     builders -- complements XHB's equal-weight/supplier-diversified construction, same
--     distinction as DIA vs a broader index). Skipped PKB -- expands into commercial
--     construction/engineering, dilutes the homebuilder-specific signal rather than
--     sharpening it. Added LEN (second volume-tier builder alongside DHI, but with a real
--     distinction: integrated mortgage/title financial-services arm) -- skipped PHM as a
--     third name in the same tier, one competitor pair is the established pattern (GM+F,
--     CSX+UNP), a third is padding. Added TOL (luxury/high-margin tier -- genuinely distinct
--     price point and customer cyclicality, affluent buyers less rate-sensitive than DHI/LEN's
--     volume tier) and NVR (distinct capital model -- land-option purchasing vs land-banking,
--     reduces balance-sheet risk in a way no other homebuilder here replicates, same category
--     of distinctness as Ryder's leasing model vs JBHT/ODFL's carrier models).
--
-- 14. Broader sweep against a user-supplied sector-overview list (growth/cyclical/defensive
--     categories). Most of the list was already covered (XLF/KRE/JPM/GS/MS/XLI/CAT/GE/XLB/
--     LIN/FCX/NEE/SO/DUK/XLRE/PLD/EQIX/CIBR/CRWD/XLU/VNQ all pre-existing). Added VGT
--     (broader-cap tech basket vs XLK's S&P-500-only, same VCR/VDC pattern), AMD (direct NVDA
--     competitor -- genuinely distinct architecture/product mix, gaming/console/datacenter
--     blend vs NVDA's AI-datacenter concentration, same GM+F pattern), PANW (second
--     cybersecurity single-name alongside CRWD -- diversified platform/firewall model,
--     genuinely distinct from CRWD's cloud-native endpoint security), LMT (reconsidering this
--     migration's own earlier RTX-over-LMT reasoning now that direct-competitor pairs are an
--     accepted pattern -- LMT is a near-pure sovereign-defense play, genuinely distinct from
--     RTX's commercial-aerospace-mixed model), SHW (paint/coatings -- a real new demand driver,
--     repaint cycle/housing/auto refinish, distinct from the industrial-gas/specialty-chem
--     names already in materials_chemicals), VPU (broader-cap utilities basket vs XLU, same
--     VCR/VDC pattern), and SPG (retail/mall REIT -- genuinely distinct from PLD's industrial
--     and EQIX's data-center REITs, different secular driver: consumer foot traffic/
--     e-commerce disruption). Skipped ORCL (too close to CRM's already-covered enterprise-SaaS
--     angle), HACK (too similar a basket construction to CIBR, already covered), FTNT (would
--     be a third appliance/platform-security single name once PANW lands, one competitor pair
--     is the established depth), and VAW (materials already has 5 single names + XLB + DBB, a
--     third basket construction is a weaker case than the others in this wave).
--
-- 15. Utilities depth -- AEP/DUK/NEE/SO (regulated electric) and CEG (merchant nuclear IPP)
--     already existed. Added RSPU (equal-weight utilities basket, same construction-diversity
--     case as RSPG for staples), VST (diversified IPP mixing nuclear with retail gas
--     operations, genuinely distinct from CEG's pure-nuclear-generator model), and ETR (a
--     third distinct business model under the same AI-power-demand thesis: a *regulated*
--     utility capturing data-center upside, vs CEG's merchant-nuclear and VST's
--     diversified-IPP models -- three genuinely different regulatory/business structures under
--     one demand driver, same reasoning as the three-way homebuilder split). UTES excluded --
--     actively managed, same ARKG precedent (manager discretion is structurally inconsistent
--     with every other instrument in this corpus). Also added AWK and WTRG -- water utilities,
--     a genuinely new sub-sector with zero prior representation: water demand is non-cyclical/
--     infrastructure-driven with distinct rate-case dynamics from electric utilities entirely,
--     not a sub-flavor of the existing regulated-electric names. AWK (largest pure-play water
--     utility) and WTRG (mid-cap water+gas diversified model) give real cross-sectional
--     dispersion within the new sub-sector. D (Dominion Energy) excluded -- a fourth regulated
--     electric utility with no meaningfully distinct business model from SO/DUK/AEP/ETR,
--     diminishing-returns territory (same discipline as skipping PHM/FTNT/VAW earlier).
--
-- 16. Fixed-income/FX peer-group depth -- closes 5 of the 8 N=1 tag_filter groups flagged
--     throughout this session and captured in todo 271 (fi_muni, fi_preferred, fi_tips,
--     fi_credit_hy, fx_commodity all had exactly one ETF each: MUB, PFF, TIP, HYG, FXA).
--     Applied the same near-perfectly-correlated-wrapper discipline used for crypto (wave 5)
--     and consumer discretionary (wave 2) -- several candidate ETFs from the source list were
--     redundant with the existing benchmark and skipped rather than added reflexively.
--     Added HYD (non-investment-grade municipal debt -- a real credit-spread dimension MUB's
--     IG-only construction doesn't capture), NAD (leveraged closed-end-fund muni proxy --
--     genuinely different instrument mechanic, structural leverage + NAV premium/discount
--     dynamics, same leveraged-proxy logic as MSTR for BTC), VRP (floating/variable-rate
--     preferred -- isolates credit risk from duration risk, a real construction distinction
--     from PFF's fixed+floating blend), STIP (short-duration 1-5yr TIPS -- isolates
--     short-term inflation shocks from TIP's full-duration exposure), NLY (mortgage REIT
--     trading as equity but behaving like a levered credit portfolio -- genuinely distinct
--     instrument type from a bond ETF), and FXC (Canadian dollar -- a genuinely different
--     commodity-currency driver, oil/energy export mix, from FXA's Australian dollar/broader
--     industrial-commodity basket).
--
--     BAC.PRL (a preferred-share single-stock proxy) explicitly EXCLUDED. Correction (code
--     review, this session): the original comment here claimed a "hard architecture collision"
--     with stream_keys.py's dots-only topic-key convention -- checked and that claim is WRONG.
--     Every topic_*() in stream_keys.py returns a static dotted literal; `instruments.symbol`
--     never enters a Kafka topic key at all, only message_key()/Redis key builders, which use
--     `:` as the delimiter -- a dot there is harmless. The real (weaker) concern is IBKR
--     contract-qualification convention: class/preferred-share tickers commonly need a
--     provider-specific format (e.g. "BRK B" with a space for BRK.B, migration 296) rather than
--     the display-convention dot, unconfirmed for this specific symbol. Excluded on that
--     narrower, unconfirmed-format-risk basis plus lower priority as a niche single-name
--     proxy -- not a confirmed schema-breaking collision like the actual `instruments.symbol`
--     primary-key collision that excluded CL/Colgate earlier in this file. VTIP
--     excluded -- redundant with STIP, near-identical short-TIPS construction from a different
--     provider (same discipline as dropping FBTC/HACK/FDIS elsewhere in this file). JNK
--     excluded -- redundant with HYG, near-perfectly-correlated high-yield corporate basket
--     from a different index provider (Bloomberg vs iBoxx), not a genuine construction
--     difference.
--
--     fx_usd stays at N=1 (UUP only) -- no second dollar-index construction was offered in
--     the source list for this wave; still open per todo 271.
--
-- contract_details mirrors the existing ETF/single-name shape; sector is a loose descriptive
-- string, not a formal classification (see migration 287/296's same convention).

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Register new instruments (76 total across all 16 waves above)
-- ---------------------------------------------------------------------------

INSERT INTO tag_vocabulary (tag, category, description) VALUES
    ('clean_energy', 'exposure', 'Renewable/clean-tech energy exposure -- driven by interest rates, capital costs, and climate policy, structurally the opposite macro driver from commodity_energy_crude''s oil/gas price beta, not a sub-category of it.'),
    ('wireless_infrastructure', 'macro_driver', 'Wireless/telecom network buildout demand -- carrier capex, 5G rollout, subscriber/data-usage growth. Links cell-tower REITs, wireless carriers, and mobile-chip designers on a shared economic driver that neither real_estate nor communication_services sector strings capture as a cross-sectional tag.')
ON CONFLICT (tag) DO NOTHING;

INSERT INTO instruments (symbol, base, contract_details, is_active) VALUES
    ('NTR',  'NTR',  '{"symbol":"NTR","base":"NTR","name":"Nutrien Ltd.","asset_class":"equity","exchange":"SMART","sector":"materials_agriculture","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('ADM',  'ADM',  '{"symbol":"ADM","base":"ADM","name":"Archer-Daniels-Midland Company","asset_class":"equity","exchange":"SMART","sector":"materials_agriculture","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('CTVA', 'CTVA', '{"symbol":"CTVA","base":"CTVA","name":"Corteva, Inc.","asset_class":"equity","exchange":"SMART","sector":"materials_agriculture","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('MOO',  'MOO',  '{"symbol":"MOO","base":"MOO","name":"VanEck Agribusiness ETF","asset_class":"equity","exchange":"SMART","sector":"agribusiness","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('GM',   'GM',   '{"symbol":"GM","base":"GM","name":"General Motors Company","asset_class":"equity","exchange":"SMART","sector":"consumer_discretionary","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('F',    'F',    '{"symbol":"F","base":"F","name":"Ford Motor Company","asset_class":"equity","exchange":"SMART","sector":"consumer_discretionary","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('WHR',  'WHR',  '{"symbol":"WHR","base":"WHR","name":"Whirlpool Corporation","asset_class":"equity","exchange":"SMART","sector":"consumer_discretionary","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('WSM',  'WSM',  '{"symbol":"WSM","base":"WSM","name":"Williams-Sonoma, Inc.","asset_class":"equity","exchange":"SMART","sector":"consumer_discretionary","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('VCR',  'VCR',  '{"symbol":"VCR","base":"VCR","name":"Vanguard Consumer Discretionary ETF","asset_class":"equity","exchange":"SMART","sector":"consumer_discretionary","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('PM',   'PM',   '{"symbol":"PM","base":"PM","name":"Philip Morris International Inc.","asset_class":"equity","exchange":"SMART","sector":"consumer_staples","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('MO',   'MO',   '{"symbol":"MO","base":"MO","name":"Altria Group, Inc.","asset_class":"equity","exchange":"SMART","sector":"consumer_staples","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('VDC',  'VDC',  '{"symbol":"VDC","base":"VDC","name":"Vanguard Consumer Staples ETF","asset_class":"equity","exchange":"SMART","sector":"consumer_staples","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('RSPG', 'RSPG', '{"symbol":"RSPG","base":"RSPG","name":"Invesco S&P 500 Equal Weight Consumer Staples ETF","asset_class":"equity","exchange":"SMART","sector":"consumer_staples","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('EPD',  'EPD',  '{"symbol":"EPD","base":"EPD","name":"Enterprise Products Partners L.P.","asset_class":"equity","exchange":"SMART","sector":"energy_midstream","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('ICLN', 'ICLN', '{"symbol":"ICLN","base":"ICLN","name":"iShares Global Clean Energy ETF","asset_class":"equity","exchange":"SMART","sector":"clean_energy","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('FSLR', 'FSLR', '{"symbol":"FSLR","base":"FSLR","name":"First Solar, Inc.","asset_class":"equity","exchange":"SMART","sector":"clean_energy","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('ENPH', 'ENPH', '{"symbol":"ENPH","base":"ENPH","name":"Enphase Energy, Inc.","asset_class":"equity","exchange":"SMART","sector":"clean_energy","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('GEV',  'GEV',  '{"symbol":"GEV","base":"GEV","name":"GE Vernova Inc.","asset_class":"equity","exchange":"SMART","sector":"clean_energy","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('ETHA', 'ETHA', '{"symbol":"ETHA","base":"ETHA","name":"iShares Ethereum Trust ETF","asset_class":"equity","exchange":"SMART","sector":"crypto","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('MSTR', 'MSTR', '{"symbol":"MSTR","base":"MSTR","name":"MicroStrategy Incorporated","asset_class":"equity","exchange":"SMART","sector":"crypto","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('COIN', 'COIN', '{"symbol":"COIN","base":"COIN","name":"Coinbase Global, Inc.","asset_class":"equity","exchange":"SMART","sector":"crypto","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('MARA', 'MARA', '{"symbol":"MARA","base":"MARA","name":"MARA Holdings, Inc.","asset_class":"equity","exchange":"SMART","sector":"crypto","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('RIOT', 'RIOT', '{"symbol":"RIOT","base":"RIOT","name":"Riot Platforms, Inc.","asset_class":"equity","exchange":"SMART","sector":"crypto","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('XTN',  'XTN',  '{"symbol":"XTN","base":"XTN","name":"SPDR S&P Transportation ETF","asset_class":"equity","exchange":"SMART","sector":"transports","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('JETS', 'JETS', '{"symbol":"JETS","base":"JETS","name":"U.S. Global Jets ETF","asset_class":"equity","exchange":"SMART","sector":"transports_airline","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('CSX',  'CSX',  '{"symbol":"CSX","base":"CSX","name":"CSX Corporation","asset_class":"equity","exchange":"SMART","sector":"industrials_rail","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('JBHT', 'JBHT', '{"symbol":"JBHT","base":"JBHT","name":"J.B. Hunt Transport Services, Inc.","asset_class":"equity","exchange":"SMART","sector":"industrials_trucking","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('ODFL', 'ODFL', '{"symbol":"ODFL","base":"ODFL","name":"Old Dominion Freight Line, Inc.","asset_class":"equity","exchange":"SMART","sector":"industrials_trucking","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('R',    'R',    '{"symbol":"R","base":"R","name":"Ryder System, Inc.","asset_class":"equity","exchange":"SMART","sector":"industrials_trucking","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('UBER', 'UBER', '{"symbol":"UBER","base":"UBER","name":"Uber Technologies, Inc.","asset_class":"equity","exchange":"SMART","sector":"transports_platform","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('FDX',  'FDX',  '{"symbol":"FDX","base":"FDX","name":"FedEx Corporation","asset_class":"equity","exchange":"SMART","sector":"industrials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('GOOGL','GOOGL','{"symbol":"GOOGL","base":"GOOGL","name":"Alphabet Inc.","asset_class":"equity","exchange":"SMART","sector":"technology","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('META', 'META', '{"symbol":"META","base":"META","name":"Meta Platforms, Inc.","asset_class":"equity","exchange":"SMART","sector":"technology","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('ASML', 'ASML', '{"symbol":"ASML","base":"ASML","name":"ASML Holding N.V.","asset_class":"equity","exchange":"SMART","sector":"technology","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('CRM',  'CRM',  '{"symbol":"CRM","base":"CRM","name":"Salesforce, Inc.","asset_class":"equity","exchange":"SMART","sector":"technology","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('CRWD', 'CRWD', '{"symbol":"CRWD","base":"CRWD","name":"CrowdStrike Holdings, Inc.","asset_class":"equity","exchange":"SMART","sector":"technology","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('GILD', 'GILD', '{"symbol":"GILD","base":"GILD","name":"Gilead Sciences, Inc.","asset_class":"equity","exchange":"SMART","sector":"healthcare","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('ELV',  'ELV',  '{"symbol":"ELV","base":"ELV","name":"Elevance Health, Inc.","asset_class":"equity","exchange":"SMART","sector":"healthcare","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('CVS',  'CVS',  '{"symbol":"CVS","base":"CVS","name":"CVS Health Corporation","asset_class":"equity","exchange":"SMART","sector":"healthcare","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('HCA',  'HCA',  '{"symbol":"HCA","base":"HCA","name":"HCA Healthcare, Inc.","asset_class":"equity","exchange":"SMART","sector":"healthcare","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('THC',  'THC',  '{"symbol":"THC","base":"THC","name":"Tenet Healthcare Corporation","asset_class":"equity","exchange":"SMART","sector":"healthcare","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('DOCS', 'DOCS', '{"symbol":"DOCS","base":"DOCS","name":"Doximity, Inc.","asset_class":"equity","exchange":"SMART","sector":"healthcare","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('TDOC', 'TDOC', '{"symbol":"TDOC","base":"TDOC","name":"Teladoc Health, Inc.","asset_class":"equity","exchange":"SMART","sector":"healthcare","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('IHF',  'IHF',  '{"symbol":"IHF","base":"IHF","name":"iShares U.S. Healthcare Providers ETF","asset_class":"equity","exchange":"SMART","sector":"healthcare","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('VHT',  'VHT',  '{"symbol":"VHT","base":"VHT","name":"Vanguard Health Care ETF","asset_class":"equity","exchange":"SMART","sector":"healthcare","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('REGN', 'REGN', '{"symbol":"REGN","base":"REGN","name":"Regeneron Pharmaceuticals, Inc.","asset_class":"equity","exchange":"SMART","sector":"healthcare_biotech","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('CRSP', 'CRSP', '{"symbol":"CRSP","base":"CRSP","name":"CRISPR Therapeutics AG","asset_class":"equity","exchange":"SMART","sector":"healthcare_biotech","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('BNTX', 'BNTX', '{"symbol":"BNTX","base":"BNTX","name":"BioNTech SE","asset_class":"equity","exchange":"SMART","sector":"healthcare_biotech","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('RVMD', 'RVMD', '{"symbol":"RVMD","base":"RVMD","name":"Revolution Medicines, Inc.","asset_class":"equity","exchange":"SMART","sector":"healthcare_biotech","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('EXEL', 'EXEL', '{"symbol":"EXEL","base":"EXEL","name":"Exelixis, Inc.","asset_class":"equity","exchange":"SMART","sector":"healthcare_biotech","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('IYZ',  'IYZ',  '{"symbol":"IYZ","base":"IYZ","name":"iShares U.S. Telecommunications ETF","asset_class":"equity","exchange":"SMART","sector":"communication_services","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('XTL',  'XTL',  '{"symbol":"XTL","base":"XTL","name":"SPDR S&P Telecom ETF","asset_class":"equity","exchange":"SMART","sector":"communication_services","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('VOX',  'VOX',  '{"symbol":"VOX","base":"VOX","name":"Vanguard Communication Services ETF","asset_class":"equity","exchange":"SMART","sector":"communication_services","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('QCOM', 'QCOM', '{"symbol":"QCOM","base":"QCOM","name":"QUALCOMM Incorporated","asset_class":"equity","exchange":"SMART","sector":"technology","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('ITB',  'ITB',  '{"symbol":"ITB","base":"ITB","name":"iShares U.S. Home Construction ETF","asset_class":"equity","exchange":"SMART","sector":"consumer_discretionary","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('LEN',  'LEN',  '{"symbol":"LEN","base":"LEN","name":"Lennar Corporation","asset_class":"equity","exchange":"SMART","sector":"consumer_discretionary","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('TOL',  'TOL',  '{"symbol":"TOL","base":"TOL","name":"Toll Brothers, Inc.","asset_class":"equity","exchange":"SMART","sector":"consumer_discretionary","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('NVR',  'NVR',  '{"symbol":"NVR","base":"NVR","name":"NVR, Inc.","asset_class":"equity","exchange":"SMART","sector":"consumer_discretionary","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('VGT',  'VGT',  '{"symbol":"VGT","base":"VGT","name":"Vanguard Information Technology ETF","asset_class":"equity","exchange":"SMART","sector":"technology","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('AMD',  'AMD',  '{"symbol":"AMD","base":"AMD","name":"Advanced Micro Devices, Inc.","asset_class":"equity","exchange":"SMART","sector":"technology","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('PANW', 'PANW', '{"symbol":"PANW","base":"PANW","name":"Palo Alto Networks, Inc.","asset_class":"equity","exchange":"SMART","sector":"technology","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('LMT',  'LMT',  '{"symbol":"LMT","base":"LMT","name":"Lockheed Martin Corporation","asset_class":"equity","exchange":"SMART","sector":"industrials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('SHW',  'SHW',  '{"symbol":"SHW","base":"SHW","name":"The Sherwin-Williams Company","asset_class":"equity","exchange":"SMART","sector":"materials_chemicals","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('VPU',  'VPU',  '{"symbol":"VPU","base":"VPU","name":"Vanguard Utilities ETF","asset_class":"equity","exchange":"SMART","sector":"utilities","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('SPG',  'SPG',  '{"symbol":"SPG","base":"SPG","name":"Simon Property Group, Inc.","asset_class":"equity","exchange":"SMART","sector":"real_estate","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('RSPU', 'RSPU', '{"symbol":"RSPU","base":"RSPU","name":"Invesco S&P 500 Equal Weight Utilities ETF","asset_class":"equity","exchange":"SMART","sector":"utilities","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('VST',  'VST',  '{"symbol":"VST","base":"VST","name":"Vistra Corp.","asset_class":"equity","exchange":"SMART","sector":"utilities","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('ETR',  'ETR',  '{"symbol":"ETR","base":"ETR","name":"Entergy Corporation","asset_class":"equity","exchange":"SMART","sector":"utilities","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('AWK',  'AWK',  '{"symbol":"AWK","base":"AWK","name":"American Water Works Company, Inc.","asset_class":"equity","exchange":"SMART","sector":"utilities_water","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('WTRG', 'WTRG', '{"symbol":"WTRG","base":"WTRG","name":"Essential Utilities, Inc.","asset_class":"equity","exchange":"SMART","sector":"utilities_water","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('HYD',  'HYD',  '{"symbol":"HYD","base":"HYD","name":"VanEck High Yield Muni ETF","asset_class":"equity","exchange":"SMART","sector":"municipal_bonds","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('NAD',  'NAD',  '{"symbol":"NAD","base":"NAD","name":"Nuveen Quality Municipal Income Fund","asset_class":"equity","exchange":"SMART","sector":"municipal_bonds","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('VRP',  'VRP',  '{"symbol":"VRP","base":"VRP","name":"Invesco Variable Rate Preferred ETF","asset_class":"equity","exchange":"SMART","sector":"preferred_securities","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('STIP', 'STIP', '{"symbol":"STIP","base":"STIP","name":"iShares 0-5 Year TIPS Bond ETF","asset_class":"equity","exchange":"SMART","sector":"tips","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('NLY',  'NLY',  '{"symbol":"NLY","base":"NLY","name":"Annaly Capital Management, Inc.","asset_class":"equity","exchange":"SMART","sector":"mortgage_reit","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('FXC',  'FXC',  '{"symbol":"FXC","base":"FXC","name":"Invesco CurrencyShares Canadian Dollar Trust","asset_class":"equity","exchange":"SMART","sector":"fx","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true)
ON CONFLICT (symbol) DO NOTHING;

-- Backfill AMLP's sector field -- predates the sector-string convention (same gap the other
-- session's migration 296 fixed for KRE).
UPDATE instruments
SET contract_details = jsonb_set(coalesce(contract_details, '{}'::jsonb), '{sector}', '"energy_midstream"')
WHERE symbol = 'AMLP' AND (contract_details->>'sector' IS NULL OR contract_details->>'sector' = '');

-- ---------------------------------------------------------------------------
-- 2. Tag new instruments -- single_name_equity for every single-name stock (not the
--    basket ETFs, which get eq_sector/eq_sub_sector or a benchmark tag instead),
--    plus existing exposure/sensitivity/macro_driver tags where the fit is genuine.
-- ---------------------------------------------------------------------------

INSERT INTO instrument_tags (symbol, tag, weight, source, evidence) VALUES
    ('NTR',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('NTR',  'commodity_agri',     0.9, 'human', '{"reason": "world''s largest potash/fertilizer producer -- direct ag-input commodity price beta"}'),
    ('NTR',  'inflation',          0.6, 'human', '{"reason": "fertilizer costs are a direct input to global food price inflation"}'),

    ('ADM',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('ADM',  'commodity_agri',     0.8, 'human', '{"reason": "global grain processor/trader -- toll-margin business, distinct from fertilizer production"}'),

    ('CTVA', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('CTVA', 'commodity_agri',     0.6, 'human', '{"reason": "seeds/crop-protection -- IP/biotech-driven, more indirect commodity-price beta than NTR/ADM"}'),
    ('CTVA', 'mid_cycle',          0.5, 'human', '{"reason": "agtech R&D/IP-driven earnings, less commodity-cyclical than fertilizer or grain trading"}'),

    ('MOO',  'commodity_agri',     0.9, 'human', '{"reason": "agribusiness equity basket -- equity-beta complement to DBA''s futures-basket construction"}'),
    ('MOO',  'benchmark',          1.0, 'human', '{"reason": "diversified ag-equity basket, benchmark role for the agriculture complex"}'),

    ('GM',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('GM',   'mid_cycle',          0.7, 'human', '{"reason": "traditional auto manufacturer -- consumer-confidence/credit-driven, ICE-to-EV transition risk distinct from TSLA"}'),

    ('F',    'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('F',    'mid_cycle',          0.7, 'human', '{"reason": "traditional auto manufacturer -- commercial fleet/legacy business mix distinct from GM"}'),

    ('WHR',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('WHR',  'mid_cycle',          0.6, 'human', '{"reason": "pure-play appliance manufacturer -- durable-goods capex/housing-cycle sensitive"}'),

    ('WSM',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('WSM',  'mid_cycle',          0.5, 'human', '{"reason": "luxury/design-conscious home-goods retail -- distinct customer/price-elasticity profile from HD''s DIY/contractor base"}'),

    ('VCR',  'eq_sector',          1.0, 'human', '{"reason": "broader cap-range (small/mid/large) consumer discretionary basket, alternative construction to XLY''s S&P-500-only SPDR"}'),

    ('PM',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('PM',   'defensive_yield',    0.8, 'human', '{"reason": "tobacco -- near-monopoly pricing power, extreme FCF/dividend yield, international/ex-US currency and regulatory exposure distinct from MO"}'),
    ('PM',   'recession',          0.7, 'human', '{"reason": "inelastic demand, classic defensive cash flows"}'),

    ('MO',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('MO',   'defensive_yield',    0.8, 'human', '{"reason": "tobacco -- near-monopoly pricing power, extreme FCF/dividend yield, pure domestic declining-volume/pricing-power play distinct from PM"}'),
    ('MO',   'recession',          0.7, 'human', '{"reason": "inelastic demand, classic defensive cash flows"}'),

    ('VDC',  'eq_sector',          1.0, 'human', '{"reason": "broader cap-range (small/mid/large) consumer staples basket, alternative construction to XLP''s S&P-500-only SPDR"}'),

    ('RSPG', 'eq_sector',          1.0, 'human', '{"reason": "equal-weight (not cap-weighted) consumer staples basket -- materially different composition in a mega-cap-dominated sector, distinct construction methodology from XLP/VDC"}'),

    ('EPD',  'single_name_equity',       1.0, 'human', '{"reason": "individual company stock (MLP)"}'),
    ('EPD',  'commodity_energy_pipeline',0.9, 'human', '{"reason": "midstream pipeline MLP -- single-name complement to AMLP''s basket exposure, same pattern as GDX+NEM/URA+CCJ"}'),
    ('EPD',  'defensive_yield',          0.7, 'human', '{"reason": "midstream -- stable fee-based cash flows, bond-like dividend yield distinct from upstream/integrated commodity-price beta"}'),

    ('ICLN', 'clean_energy', 1.0, 'human', '{"reason": "diversified global clean energy basket -- solar/wind/renewables, opposite macro driver (rates/policy) from XLE''s commodity-price basket"}'),
    ('ICLN', 'benchmark',    1.0, 'human', '{"reason": "broad clean-energy basket, benchmark role for the renewable complex"}'),
    ('ICLN', 'rate_sensitive',0.7,'human', '{"reason": "capital-intensive growth projects -- NPV directly sensitive to discount-rate/capex-cost moves, same directional mechanism as REITs/utilities"}'),

    ('FSLR', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('FSLR', 'clean_energy',       0.9, 'human', '{"reason": "utility-scale solar module manufacturer -- hardware/manufacturing business model"}'),
    ('FSLR', 'rate_sensitive',     0.6, 'human', '{"reason": "capex-intensive manufacturing, project financing sensitive to rates"}'),

    ('ENPH', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('ENPH', 'clean_energy',       0.9, 'human', '{"reason": "residential solar/storage microinverter systems -- tech-software business model distinct from FSLR''s hardware manufacturing"}'),
    ('ENPH', 'rate_sensitive',     0.6, 'human', '{"reason": "residential solar financing/adoption sensitive to consumer borrowing costs"}'),

    ('GEV',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('GEV',  'clean_energy',       0.8, 'human', '{"reason": "wind turbines/grid electrification/power tech -- industrial-conglomerate profile distinct from FSLR/ENPH''s more pure-solar focus"}'),

    ('ETHA', 'crypto',    1.0, 'human', '{"reason": "spot Ethereum ETF -- genuinely different underlying from IBIT''s Bitcoin, distinct smart-contract/DeFi risk profile"}'),
    ('ETHA', 'benchmark', 1.0, 'human', '{"reason": "spot Ethereum benchmark"}'),

    ('MSTR', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('MSTR', 'crypto',             0.9, 'human', '{"reason": "leveraged corporate Bitcoin treasury proxy -- operating business + convertible-debt leverage + NAV premium/discount dynamics, distinct mechanism from spot ETF exposure"}'),
    ('MSTR', 'high_beta',          0.8, 'human', '{"reason": "leverage on top of BTC price beta -- amplified volatility vs spot exposure"}'),

    ('COIN', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('COIN', 'crypto',             0.8, 'human', '{"reason": "exchange/custody revenue model -- scales with trading volume x volatility, not just directional price exposure, distinct from MSTR/spot ETFs"}'),

    ('MARA', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('MARA', 'crypto',             0.7, 'human', '{"reason": "industrial-scale BTC mining -- hash-rate/energy-cost/halving-cycle economics, a third distinct driver from treasury-proxy or exchange models"}'),

    ('RIOT', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('RIOT', 'crypto',             0.7, 'human', '{"reason": "industrial-scale BTC mining, same driver as MARA -- pairs for cross-sectional dispersion within mining economics, same GM+F pattern"}'),

    ('XTN',  'transports',    1.0, 'human', '{"reason": "equal-weight transportation basket -- same distinct-methodology case as RSPG vs XLP/VDC, small/mid-cap inclusive vs IYT''s rail-anchored cap-weighting"}'),
    ('XTN',  'eq_sub_sector', 1.0, 'human', '{"reason": "basket ETF classification tag, same convention as XHB/KRE/SMH/OIH (migration 220)"}'),

    ('JETS', 'transports',    0.8, 'human', '{"reason": "pure-play airline/aircraft/airport basket -- complements DAL the same way GDX complements NEM"}'),
    ('JETS', 'eq_sub_sector', 1.0, 'human', '{"reason": "basket ETF classification tag, same convention as XHB/KRE/SMH/OIH (migration 220)"}'),

    ('CSX',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('CSX',  'transports',         1.0, 'human', '{"reason": "direct UNP rail competitor -- East Coast/coal-heavy vs UNP''s West Coast/intermodal mix, cross-sectional dispersion within rail"}'),
    ('CSX',  'leading_indicator',  0.9, 'human', '{"reason": "rail carload volume is a textbook leading economic indicator, same family as UNP"}'),

    ('JBHT', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('JBHT', 'transports',         0.8, 'human', '{"reason": "intermodal truck-to-rail transfer -- asset-lighter business model distinct from owned-rail-network capital intensity"}'),

    ('ODFL', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('ODFL', 'transports',         0.7, 'human', '{"reason": "pure LTL regional trucking -- distinct again from intermodal (JBHT) and rail (UNP/CSX)"}'),

    ('R',    'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('R',    'transports',         0.6, 'human', '{"reason": "fleet leasing/rental services -- B2B services model insulated from freight volume the way carriers aren''t, most distinct of the trucking-adjacent picks"}'),

    ('UBER', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('UBER', 'transports',         0.6, 'human', '{"reason": "platform/gig-economy take-rate model -- not an asset-heavy carrier, only platform-business exposure in this corpus"}'),
    ('UBER', 'high_beta',          0.6, 'human', '{"reason": "growth/platform-stock volatility profile distinct from asset-heavy carriers"}'),

    ('FDX',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('FDX',  'transports',         1.0, 'human', '{"reason": "direct UPS parcel/logistics competitor -- reconsidered from migration 296''s original UPS-over-FDX call now that CSX+UNP/MARA+RIOT establish direct-competitor pairs as an accepted pattern"}'),

    ('GOOGL', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('GOOGL', 'mid_cycle',          0.6, 'human', '{"reason": "search/advertising/cloud -- digital-ad-driven media, distinct from DIS/NFLX/CMCSA subscription/carriage economics"}'),

    ('META', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('META', 'mid_cycle',          0.6, 'human', '{"reason": "social media/advertising -- digital-ad-driven media, same distinct driver as GOOGL"}'),

    ('ASML', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('ASML', 'semi_cycle',         0.9, 'human', '{"reason": "lithography equipment monopoly -- sells to foundries, driven by fab capex cycles not end-chip demand, distinct from AVGO/NVDA design or TSM foundry manufacturing"}'),
    ('ASML', 'geopolitical',       0.6, 'human', '{"reason": "export-control-sensitive (China chip-equipment restrictions), Dutch-domiciled"}'),

    ('CRM',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('CRM',  'mid_cycle',          0.5, 'human', '{"reason": "enterprise SaaS -- recurring-revenue economics distinct from every hardware/semi name in tech"}'),

    ('CRWD', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('CRWD', 'geopolitical',       0.6, 'human', '{"reason": "cybersecurity -- single-name complement to CIBR basket, same gap shape AMLP/GDX/URA had before their complements"}'),
    ('CRWD', 'high_beta',          0.6, 'human', '{"reason": "high-growth SaaS security -- elevated volatility profile"}'),

    ('GILD', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('GILD', 'recession',          0.6, 'human', '{"reason": "large stable HIV/antiviral franchise -- distinct from VRTX''s concentrated-franchise binary-catalyst risk, cross-sectional depth within biotech"}'),

    ('ELV',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('ELV',  'recession',          0.6, 'human', '{"reason": "regional Blue Cross Blue Shield managed-care model -- second payer, distinct from UNH''s Optum data-driven model, same CSX+UNP dispersion logic"}'),

    ('CVS',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('CVS',  'recession',          0.6, 'human', '{"reason": "vertically-integrated retail pharmacy + Aetna insurance + primary care -- a third payer archetype, not redundant with UNH/ELV"}'),

    ('HCA',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('HCA',  'mid_cycle',          0.6, 'human', '{"reason": "largest acute-care hospital operator -- care-delivery-facilities sub-type missing entirely from healthcare until this addition"}'),

    ('THC',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('THC',  'mid_cycle',          0.6, 'human', '{"reason": "second hospital operator -- ambulatory-surgery-center-concentrated vs HCA''s broader acute-care network, same dispersion logic"}'),

    ('DOCS', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('DOCS', 'high_beta',          0.5, 'human', '{"reason": "clinician professional-network/platform, ad/subscription revenue -- distinct business model from TDOC despite both being telehealth-adjacent"}'),

    ('TDOC', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('TDOC', 'high_beta',          0.6, 'human', '{"reason": "actual virtual-care-visit delivery -- genuinely distinct business model from DOCS"}'),

    ('IHF',  'benchmark',     1.0, 'human', '{"reason": "pure-play payer/provider-services sub-index -- genuinely narrower construction than XLV, which blends insurers+medtech+pharma+providers together"}'),
    ('IHF',  'eq_sub_sector', 1.0, 'human', '{"reason": "same narrower-sub-index construction category as IYZ vs XLC -- code review flagged the inconsistent tagging (benchmark-only) despite the file describing them as the same case; without eq_sub_sector, IHF has no tag linking it to healthcare for cross_sectional_regime_model.py peer-group resolution"}'),

    ('VHT',  'eq_sector', 1.0, 'human', '{"reason": "broader cap-range (small/mid/large) healthcare basket, alternative construction to XLV''s S&P-500-only SPDR, same case as VCR/VDC"}'),

    ('REGN', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('REGN', 'recession',          0.6, 'human', '{"reason": "ophthalmology/inflammatory-concentrated blockbuster franchise -- third distinct disease-area concentration alongside VRTX (cystic fibrosis) and GILD (antiviral)"}'),

    ('CRSP', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('CRSP', 'high_beta',          0.8, 'human', '{"reason": "clinical-stage/pre-commercial gene-editing -- binary regulatory/trial-readout risk, no meaningful revenue yet, distinct risk tier from every commercial-stage biotech name"}'),

    ('BNTX', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('BNTX', 'high_beta',          0.6, 'human', '{"reason": "mRNA platform -- distinct modality from small-molecule/antibody/gene-editing names, plus distinct capital structure (large net-cash position funding speculative pipeline)"}'),

    ('RVMD', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('RVMD', 'high_beta',          0.8, 'human', '{"reason": "clinical-stage targeted-oncology small-molecule -- distinct modality from CRSP''s gene-editing platform despite both being pre-commercial"}'),

    ('EXEL', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('EXEL', 'high_beta',          0.5, 'human', '{"reason": "commercial-stage but single-drug-dependent (Cabometyx) -- middle tier between GILD''s diversification and CRSP/RVMD''s pure clinical-stage speculation"}'),

    ('IYZ',  'eq_sub_sector', 1.0, 'human', '{"reason": "pure-play telecom/infrastructure basket -- excludes internet/media giants, same narrower-sub-index case as IHF vs XLV"}'),

    ('XTL',  'eq_sub_sector', 1.0, 'human', '{"reason": "equal-weight telecom basket -- shifts concentration toward mid-cap equipment providers, distinct construction methodology from XLC/IYZ"}'),

    ('VOX',  'eq_sector', 1.0, 'human', '{"reason": "broader cap-range (small/mid/large) communication services basket, alternative construction to XLC''s S&P-500-only SPDR, same case as VCR/VDC/VHT"}'),

    ('QCOM', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('QCOM', 'semi_cycle',         0.8, 'human', '{"reason": "wireless modem/5G chip design and licensing -- 5th distinct semiconductor sub-type (design/AVGO, AI/NVDA, foundry/TSM, equipment/ASML, mobile-wireless/QCOM), bridges into telecom infrastructure"}'),

    ('AMT',  'wireless_infrastructure', 0.9, 'human', '{"reason": "cell-tower REIT -- tower-lease revenue structurally tied to carrier capex and wireless-subscriber growth, a real economic co-movement not captured by rate_sensitive/real_estate alone"}'),
    ('VZ',   'wireless_infrastructure', 0.9, 'human', '{"reason": "wireless carrier -- direct driver of the same capex/subscriber-growth cycle"}'),
    ('T',    'wireless_infrastructure', 0.9, 'human', '{"reason": "wireless carrier -- direct driver of the same capex/subscriber-growth cycle"}'),
    ('TMUS', 'wireless_infrastructure', 0.9, 'human', '{"reason": "wireless carrier -- direct driver of the same capex/subscriber-growth cycle"}'),
    ('QCOM', 'wireless_infrastructure', 0.7, 'human', '{"reason": "wireless modem/5G chipmaker -- supplies the carrier buildout, same demand cycle one step removed"}'),
    ('IYZ',  'wireless_infrastructure', 0.9, 'human', '{"reason": "pure-play telecom basket -- same demand cycle at the basket level"}'),
    ('XTL',  'wireless_infrastructure', 0.9, 'human', '{"reason": "equal-weight telecom basket, mid-cap-equipment-tilted -- same demand cycle at the basket level"}'),

    ('ITB',  'rate_sensitive', 0.8, 'human', '{"reason": "cap-weighted pure-play homebuilder basket -- housing starts directly rate-sensitive, complements XHB''s equal-weight/supplier-diversified construction"}'),
    ('ITB',  'eq_sub_sector',  1.0, 'human', '{"reason": "basket ETF classification tag, same convention as XHB/KRE/SMH/OIH (migration 220)"}'),

    ('LEN',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('LEN',  'rate_sensitive',     0.8, 'human', '{"reason": "second volume-tier homebuilder alongside DHI -- integrated mortgage/title financial-services arm is a real business-model distinction"}'),

    ('TOL',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('TOL',  'rate_sensitive',     0.6, 'human', '{"reason": "luxury/high-margin homebuilder -- affluent buyers less rate-sensitive than DHI/LEN''s volume tier, distinct customer cyclicality"}'),

    ('NVR',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('NVR',  'rate_sensitive',     0.7, 'human', '{"reason": "land-option purchasing model (not land-banking) -- distinct capital structure, reduces balance-sheet rate/inventory risk vs every other homebuilder here"}'),

    ('VGT',  'eq_sector', 1.0, 'human', '{"reason": "broader cap-range (small/mid/large) technology basket, alternative construction to XLK''s S&P-500-only SPDR, same case as VCR/VDC/VHT/VOX"}'),

    ('AMD',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('AMD',  'semi_cycle',         0.9, 'human', '{"reason": "direct NVDA competitor -- distinct architecture/product mix, gaming/console/datacenter blend vs NVDA''s AI-datacenter concentration, same GM+F cross-sectional-dispersion pattern"}'),

    ('PANW', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('PANW', 'geopolitical',       0.6, 'human', '{"reason": "second cybersecurity single-name alongside CRWD -- diversified platform/firewall model, genuinely distinct from CRWD''s cloud-native endpoint security"}'),

    ('LMT',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('LMT',  'geopolitical',       0.8, 'human', '{"reason": "near-pure sovereign-defense play (F-35, missiles) -- genuinely distinct from RTX''s commercial-aerospace-mixed model, reconsidered from this migration''s own earlier RTX-over-LMT call now that direct-competitor pairs are an accepted pattern"}'),

    ('SHW',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('SHW',  'mid_cycle',          0.6, 'human', '{"reason": "paint/coatings -- repaint cycle/housing/auto refinish demand driver, distinct from the industrial-gas/specialty-chem names already in materials_chemicals"}'),

    ('VPU',  'eq_sector', 1.0, 'human', '{"reason": "broader cap-range (small/mid/large) utilities basket, alternative construction to XLU''s S&P-500-only SPDR, same case as VCR/VDC/VHT/VOX/VGT"}'),

    ('SPG',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('SPG',  'real_estate',        1.0, 'human', '{"reason": "retail/mall REIT -- genuinely distinct from PLD''s industrial and EQIX''s data-center REITs, different secular driver (consumer foot traffic/e-commerce disruption)"}'),
    ('SPG',  'rate_sensitive',     0.8, 'human', '{"reason": "REIT -- cap-rate/discount-rate mechanics, same directional rate sensitivity as PLD/EQIX/AMT"}'),

    ('RSPU', 'eq_sector',      1.0, 'human', '{"reason": "sector-basket ETF classification tag, same convention as VPU/RSPG/VCR/VDC/VGT/XLU -- code review caught this was missing (rate_sensitive alone silently drops RSPU out of eq_sector peer-group resolution)"}'),
    ('RSPU', 'rate_sensitive', 0.7, 'human', '{"reason": "equal-weight utilities basket -- same construction-diversity case as RSPG for staples, distinct from XLU/VPU''s weighting methodology"}'),

    ('VST',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('VST',  'rate_sensitive',     0.5, 'human', '{"reason": "diversified IPP mixing nuclear with retail gas operations -- genuinely distinct from CEG''s pure merchant-nuclear-generator model, less regulated-utility rate-sensitivity than AEP/DUK/NEE/SO"}'),

    ('ETR',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('ETR',  'rate_sensitive',     0.7, 'human', '{"reason": "regulated Southern-US utility capturing AI/data-center power demand upside -- third distinct business model in the AI-power-demand thesis alongside CEG''s merchant-nuclear and VST''s diversified-IPP models"}'),

    ('AWK',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('AWK',  'rate_sensitive',     0.7, 'human', '{"reason": "largest pure-play water utility -- water demand is non-cyclical/infrastructure-driven with distinct rate-case dynamics from electric utilities, a genuinely new sub-sector"}'),

    ('WTRG', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('WTRG', 'rate_sensitive',     0.7, 'human', '{"reason": "mid-cap water+gas diversified utility -- cross-sectional complement to AWK within the new water-utility sub-sector"}'),

    ('HYD',  'fi_muni',        0.8, 'human', '{"reason": "non-investment-grade municipal debt -- real credit-spread dimension MUB''s IG-only construction doesn''t capture, closes fi_muni''s N=1 peer group"}'),
    ('HYD',  'rate_sensitive', 0.7, 'human', '{"reason": "bond ETF -- code review caught this was missing; every existing fi_* benchmark (MUB/TIP/PFF/HYG) carries rate_sensitive"}'),

    ('NAD',  'fi_muni',        0.7, 'human', '{"reason": "leveraged closed-end-fund muni proxy -- genuinely different instrument mechanic (structural leverage, NAV premium/discount dynamics) from a straight ETF, same leveraged-proxy logic as MSTR for BTC"}'),
    ('NAD',  'rate_sensitive', 0.8, 'human', '{"reason": "levered muni CEF -- amplified rate sensitivity vs an unlevered bond ETF, code review caught this was missing"}'),

    ('VRP',  'fi_preferred',   0.8, 'human', '{"reason": "floating/variable-rate preferred -- isolates credit risk from duration risk, distinct construction from PFF''s fixed+floating blend, closes fi_preferred''s N=1 peer group"}'),
    ('VRP',  'rate_sensitive', 0.6, 'human', '{"reason": "preferred security -- code review caught this was missing; lower weight than fixed-rate preferreds since floating-rate structure dampens (does not eliminate) rate sensitivity"}'),

    ('STIP', 'fi_tips',            0.8, 'human', '{"reason": "short-duration (1-5yr) TIPS -- isolates short-term inflation shocks from TIP''s full-duration exposure, closes fi_tips''s N=1 peer group"}'),
    ('STIP', 'fi_short_duration',  0.6, 'human', '{"reason": "short-duration construction, same family as other fi_short_duration instruments"}'),
    ('STIP', 'rate_sensitive',     0.6, 'human', '{"reason": "TIPS -- code review caught this was missing; lower weight than nominal Treasuries since inflation-linked principal partially offsets rate sensitivity"}'),

    ('NLY',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock (mortgage REIT)"}'),
    ('NLY',  'fi_credit_hy',       0.6, 'human', '{"reason": "mortgage REIT trading as equity but behaving like a levered credit portfolio -- genuinely distinct instrument type from a bond ETF, closes fi_credit_hy''s N=1 peer group"}'),
    ('NLY',  'rate_sensitive',     0.8, 'human', '{"reason": "levered mortgage-credit portfolio -- direct and amplified rate sensitivity"}'),

    ('FXC',  'fx_commodity', 0.8, 'human', '{"reason": "Canadian dollar -- genuinely different commodity-currency driver (oil/energy export mix) from FXA''s Australian dollar/broader industrial-commodity basket, closes fx_commodity''s N=1 peer group"}')
ON CONFLICT (symbol, tag) DO NOTHING;

COMMIT;
