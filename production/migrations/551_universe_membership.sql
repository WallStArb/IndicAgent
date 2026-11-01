-- Migration 551: universe membership on instruments, hashed into the run record (todo 491)
--
-- Two selection biases research could not see: the batch cohorts (batch 1 and wave 2 drew
-- names by today's market-cap rank, an outcome-conditioned selector) lived only in the
-- committed manifests under config/universe/, and `instruments` carried no entry date, so a
-- name onboarded in 2026 entered every panel for its whole 2006 history with nothing on the
-- row saying when it became selectable. This migration stores both facts per name.
--
-- Columns (nullable: the pre-SOP names have no cohort evidence and a future name could
-- legitimately onboard without a manifest batch):
--   universe_entry_date  the UTC date the name entered instruments (the onboarding day);
--   universe_cohort      the manifest `cohort` label (the selection rule, e.g. 'spx',
--                        'r3k_501_1000'); NULL when no manifest names the name.
--
-- Backfill. Entry date: created_at::date for every row. This IS the manifest evidence where
-- a manifest exists: all 1,256 manifest-named instruments (of 1,551 total) were onboarded on
-- their manifest's batch date (verified 2026-10-31, zero mismatches against
-- expansion_2026_09_26.csv, expansion_etfs_2026_09_26.csv, expansion_smallcaps_2026_09_26.csv,
-- wave2_etfs_2026_10_03.csv and wave2_stocks_2026_10_03.csv), and for the 295 names onboarded
-- before the SOP (2026-05-15 to 2026-09-16) created_at is the only knowable fact. Nothing is
-- invented: outside manifest coverage the cohort stays NULL. XWEB, named in a manifest but
-- rejected by IBKR qualification (SOP stage 5), has no instruments row and gets nothing.
--
-- Going forward the single writer of both columns is onboard_instrument()
-- (src/config/instrument_onboarding.py), called by the manifest onboarder with the row's
-- cohort. The other INSERT paths (database_manager.upsert_instruments, the API route) leave
-- both columns NULL and never touch them on conflict.
--
-- Research side: the runner hashes the S0 snapshot's symbol set (sha256 over the symbol
-- list, the same digest form as members_universe_hash) and records it on research_run
-- (this migration adds research_run.universe_hash, and teaches the append-only guard the
-- same NULL-to-value-once rule snapshot_hash has). No snapshot hash composition, spec field
-- or recorded run moves: existing recorded runs keep their hashes and get NULL.
--
-- Plain small table, not a hypertable; no VACUUM step.
-- Not idempotent on purpose: a second apply fails loudly on ALTER TABLE.
BEGIN;

ALTER TABLE instruments ADD COLUMN universe_entry_date date;
ALTER TABLE instruments ADD COLUMN universe_cohort text;

COMMENT ON COLUMN instruments.universe_entry_date IS
    'The UTC date the name entered the universe (the onboarding day). The manifest batch date '
    'where a manifest covers the name, else the row''s created_at date. Single writer: '
    'onboard_instrument() (todo 491). Not a vintage: vintage is a dated data span counted for '
    'a selection test (glossary).';
COMMENT ON COLUMN instruments.universe_cohort IS
    'The onboarding manifest cohort label naming the selection rule the row came from '
    '(config/universe/ manifests and README, e.g. ''spx'', ''r3k_501_1000''); NULL when no '
    'manifest names the instrument. Single writer: onboard_instrument() (todo 491).';

UPDATE instruments SET universe_entry_date = (created_at AT TIME ZONE 'UTC')::date;

-- dow_industrials (4 names)
UPDATE instruments SET universe_cohort = 'dow_industrials' WHERE symbol IN (
    'AMGN', 'CSCO', 'IBM', 'NKE'
);

-- dow_transports (9 names)
UPDATE instruments SET universe_cohort = 'dow_transports' WHERE symbol IN (
    'ALK', 'CAR', 'CHRW', 'EXPD', 'LSTR', 'LUV', 'MATX', 'NSC', 'UAL'
);

-- dow_utilities (9 names)
UPDATE instruments SET universe_cohort = 'dow_utilities' WHERE symbol IN (
    'ATO', 'D', 'ED', 'EIX', 'EXC', 'FE', 'PEG', 'SRE', 'XEL'
);

-- etf_alternatives (4 names)
UPDATE instruments SET universe_cohort = 'etf_alternatives' WHERE symbol IN (
    'CTA', 'DBMF', 'KMLM', 'MNA'
);

-- etf_commodity (10 names)
UPDATE instruments SET universe_cohort = 'etf_commodity' WHERE symbol IN (
    'CORN', 'CPER', 'GSG', 'PALL', 'SOYB', 'UNG', 'UNL', 'USL', 'USO', 'WEAT'
);

-- etf_commodity_gap (3 names)
UPDATE instruments SET universe_cohort = 'etf_commodity_gap' WHERE symbol IN (
    'BNO', 'CANE', 'UGA'
);

-- etf_country (12 names)
UPDATE instruments SET universe_cohort = 'etf_country' WHERE symbol IN (
    'EWA', 'EWC', 'EWD', 'EWH', 'EWI', 'EWL', 'EWN', 'EWP', 'EWQ', 'EWS',
    'EWU', 'EWW'
);

-- etf_country_em (12 names)
UPDATE instruments SET universe_cohort = 'etf_country_em' WHERE symbol IN (
    'ARGT', 'ECH', 'EIDO', 'EPHE', 'EPOL', 'EPU', 'EWM', 'EZA', 'KSA', 'THD',
    'TUR', 'VNM'
);

-- etf_credit_duration (5 names)
UPDATE instruments SET universe_cohort = 'etf_credit_duration' WHERE symbol IN (
    'FLOT', 'JAAA', 'LTPZ', 'VCIT', 'VCSH'
);

-- etf_currency (2 names)
UPDATE instruments SET universe_cohort = 'etf_currency' WHERE symbol IN (
    'FXB', 'FXF'
);

-- etf_equal_weight (10 names)
UPDATE instruments SET universe_cohort = 'etf_equal_weight' WHERE symbol IN (
    'QQEW', 'RSPC', 'RSPD', 'RSPF', 'RSPH', 'RSPM', 'RSPN', 'RSPR', 'RSPS', 'RSPT'
);

-- etf_fixed_income (7 names)
UPDATE instruments SET universe_cohort = 'etf_fixed_income' WHERE symbol IN (
    'ANGL', 'BKLN', 'BNDX', 'BWX', 'MBB', 'SJNK', 'VCLT'
);

-- etf_industry (15 names)
UPDATE instruments SET universe_cohort = 'etf_industry' WHERE symbol IN (
    'GDXJ', 'IHI', 'KBE', 'KCE', 'KIE', 'SLX', 'XAR', 'XES', 'XHE', 'XHS',
    'XME', 'XPH', 'XSD', 'XSW', 'XWEB'
);

-- etf_industry_gap (6 names)
UPDATE instruments SET universe_cohort = 'etf_industry_gap' WHERE symbol IN (
    'COPX', 'LIT', 'REMX', 'SIL', 'TAN', 'URNM'
);

-- etf_international_gap (5 names)
UPDATE instruments SET universe_cohort = 'etf_international_gap' WHERE symbol IN (
    'EIS', 'EPI', 'GREK', 'SCZ', 'VGK'
);

-- etf_real_assets_gap (4 names)
UPDATE instruments SET universe_cohort = 'etf_real_assets_gap' WHERE symbol IN (
    'IGF', 'PSP', 'REET', 'VNQI'
);

-- etf_size_style (6 names)
UPDATE instruments SET universe_cohort = 'etf_size_style' WHERE symbol IN (
    'IJH', 'IJR', 'IWC', 'IWN', 'IWO', 'VIXM'
);

-- etf_treasury (3 names)
UPDATE instruments SET universe_cohort = 'etf_treasury' WHERE symbol IN (
    'IEI', 'SHV', 'TLH'
);

-- r2k_draw_iwm (100 names)
UPDATE instruments SET universe_cohort = 'r2k_draw_iwm' WHERE symbol IN (
    'ACRS', 'ACVA', 'ADPT', 'AIR', 'AKTS', 'ALRM', 'AMPH', 'ANRO', 'APMD', 'ARTV',
    'ASTE', 'ASYS', 'BAND', 'BELFA', 'BH', 'BKD', 'BOC', 'BOX', 'BRBR', 'CDRE',
    'CFFN', 'CGON', 'CMPR', 'CPS', 'CSIQ', 'CUBI', 'DCH', 'DLO', 'ENOV', 'ENTA',
    'EPSN', 'FBIZ', 'FBRT', 'FCEL', 'FLO', 'FMAO', 'FRME', 'FRST', 'FSBC', 'GEF',
    'GENB', 'GLNG', 'GPI', 'GSBC', 'GYRE', 'HCKT', 'HNRG', 'HSTM', 'IBEX', 'IBP',
    'IDR', 'IIPR', 'INSP', 'JMSB', 'JOUT', 'KMT', 'KN', 'LCUT', 'LQDA', 'LXP',
    'MVBF', 'NESR', 'OEC', 'OSW', 'OTTR', 'PAYO', 'PBFS', 'PENG', 'PLMR', 'PMTS',
    'PTGX', 'RAIL', 'RBCAA', 'RCAT', 'RCMT', 'RDW', 'REA', 'REX', 'RLAY', 'SDRL',
    'SEZL', 'SGHC', 'SLAB', 'SRRK', 'STBA', 'SVRA', 'TPB', 'UHT', 'UNF', 'USAU',
    'UUUU', 'VATE', 'VISN', 'VOR', 'VOYG', 'WEYS', 'WSFS', 'WT', 'XZO', 'YORW'
);

-- r2k_draw_iwv_rank1001 (95 names)
UPDATE instruments SET universe_cohort = 'r2k_draw_iwv_rank1001' WHERE symbol IN (
    'AAP', 'ACMR', 'AGL', 'APPS', 'ATRO', 'AZTA', 'BCML', 'BLBD', 'BOW', 'BRSL',
    'BWIN', 'BZH', 'CAL', 'CBAN', 'CBC', 'CCBG', 'CLBK', 'CMCO', 'CMDB', 'CNXC',
    'COUR', 'CRC', 'CRVL', 'CVBF', 'CWT', 'CXW', 'CYRX', 'DHC', 'DORM', 'EBF',
    'ECVT', 'EFSC', 'FLGT', 'GOOD', 'HOG', 'INGN', 'IRT', 'KBH', 'KRUS', 'KURA',
    'LASR', 'LMNR', 'LOAR', 'MAMA', 'MBWM', 'MBX', 'MCY', 'MFP', 'MGTX', 'MOV',
    'MPB', 'MUX', 'MYRG', 'MZTI', 'NBTB', 'NEXT', 'NRIX', 'NUVB', 'NVST', 'NWBI',
    'NXRT', 'OCUL', 'OFLX', 'OGS', 'OLED', 'OMCL', 'ONIT', 'OUT', 'PAG', 'PAGS',
    'PAR', 'PARR', 'PATK', 'PFBC', 'PLOW', 'POST', 'POWI', 'PRSU', 'PUMP', 'PWP',
    'RES', 'SAFE', 'SAFT', 'SBGI', 'SCSC', 'SFL', 'SHC', 'STUB', 'TG', 'TRST',
    'UHAL', 'ULH', 'VSTS', 'WSBF', 'XERS'
);

-- r3k_501_1000 (410 names)
UPDATE instruments SET universe_cohort = 'r3k_501_1000' WHERE symbol IN (
    'AAL', 'AAOI', 'AAON', 'ABCB', 'ACA', 'ACIW', 'ACM', 'ADC', 'AEIS', 'AFG',
    'AGCO', 'AGNC', 'AGX', 'AHR', 'AIT', 'ALKS', 'ALLY', 'ALSN', 'AM', 'AMG',
    'AMH', 'AMKR', 'AN', 'ANF', 'APG', 'APLD', 'APPF', 'AR', 'ARMK', 'AROC',
    'ARW', 'ARWR', 'AS', 'ASND', 'ASTS', 'ATR', 'AUB', 'AUR', 'AVAV', 'AVT',
    'AVTR', 'AWI', 'AXS', 'AXSM', 'AXTA', 'AYI', 'BAH', 'BBIO', 'BC', 'BCPC',
    'BIO', 'BJ', 'BKH', 'BLDR', 'BMNR', 'BMRN', 'BPOP', 'BRKR', 'BROS', 'BRX',
    'BSY', 'BTSG', 'BURL', 'BWA', 'BWXT', 'CACI', 'CAG', 'CART', 'CAVA', 'CBSH',
    'CCK', 'CE', 'CFR', 'CG', 'CGNX', 'CHDN', 'CHE', 'CHRD', 'CHWY', 'CHYM',
    'CIFR', 'CLF', 'CMC', 'CNH', 'CNM', 'CNO', 'CNR', 'COGT', 'COKE', 'COLB',
    'COMP', 'CORT', 'CORZ', 'CR', 'CRBG', 'CROX', 'CSL', 'CTRE', 'CUBE', 'CVLT',
    'CWST', 'CYTK', 'CZR', 'DBX', 'DCI', 'DFTX', 'DK', 'DKNG', 'DKS', 'DNTH',
    'DOCN', 'DOCU', 'DOX', 'DTM', 'DUOL', 'DY', 'EAT', 'ECG', 'EGP', 'EHC',
    'ELAN', 'ELF', 'ELS', 'EMN', 'ENS', 'ENSG', 'ENVA', 'EPAM', 'EPRT', 'EQH',
    'ESE', 'ESI', 'ESNT', 'ESTC', 'ETSY', 'EVR', 'EXLS', 'EXP', 'FAF', 'FBIN',
    'FCFS', 'FDXF', 'FHN', 'FIG', 'FIGR', 'FIVE', 'FLR', 'FLS', 'FLUT', 'FN',
    'FNB', 'FND', 'FNF', 'FORM', 'FR', 'FROG', 'FSS', 'FTDR', 'G', 'GATX',
    'GBCI', 'GFL', 'GFS', 'GGG', 'GLPI', 'GME', 'GMED', 'GNTX', 'GTES', 'GTLB',
    'GWRE', 'GXO', 'H', 'HAE', 'HALO', 'HCC', 'HIMS', 'HL', 'HLI', 'HOMB',
    'HQY', 'HR', 'HRB', 'HUBS', 'HUT', 'HWC', 'HXL', 'IDA', 'IDCC', 'IESC',
    'INGR', 'IONQ', 'IONS', 'IOT', 'IREN', 'JAZZ', 'JBTM', 'JEF', 'JXN', 'KBR',
    'KGS', 'KMX', 'KNSL', 'KNX', 'KRG', 'KRYS', 'KTOS', 'KYMR', 'LAD', 'LAMR',
    'LEA', 'LECO', 'LFUS', 'LGND', 'LKQ', 'LNC', 'LNTH', 'LSCC', 'LTH', 'LUMN',
    'LW', 'LYFT', 'M', 'MAC', 'MANH', 'MBGL', 'MDGL', 'MDLN', 'MEDP', 'MGY',
    'MHK', 'MKTX', 'MLI', 'MMSI', 'MOD', 'MOG.A', 'MOH', 'MP', 'MSA', 'MSGS',
    'MSM', 'MTCH', 'MTDR', 'MTG', 'MTN', 'MTZ', 'MUR', 'MUSA', 'MXL', 'NBIX',
    'NE', 'NEU', 'NFG', 'NJR', 'NNN', 'NOV', 'NOVT', 'NPO', 'NXST', 'NXT',
    'NYT', 'OC', 'OGE', 'OHI', 'OKLO', 'OMF', 'ONB', 'ONON', 'ONTO', 'ORA',
    'ORI', 'OSCR', 'OSK', 'OWL', 'OZK', 'PATH', 'PAYC', 'PB', 'PBF', 'PCOR',
    'PCTY', 'PCVX', 'PEN', 'PFGC', 'PINS', 'PIPR', 'PLXS', 'PNFP', 'POOL', 'POR',
    'PRAX', 'PRI', 'PRMB', 'PTCT', 'PTEN', 'QBTS', 'QGEN', 'QLYS', 'QRVO', 'QXO',
    'RAL', 'RBC', 'RBRK', 'RDN', 'RDNT', 'REXR', 'RGEN', 'RHP', 'RITM', 'RKT',
    'RLI', 'RMBS', 'RNG', 'RNR', 'RPM', 'RRC', 'RRX', 'RYN', 'RYTM', 'S',
    'SAIA', 'SAIC', 'SANM', 'SARO', 'SCI', 'SEIC', 'SF', 'SFM', 'SGI', 'SIGI',
    'SIRI', 'SITM', 'SM', 'SMTC', 'SN', 'SNEX', 'SOLS', 'SPXC', 'SSB', 'SSD',
    'SSRM', 'ST', 'STAG', 'STRL', 'STWD', 'SUI', 'SWX', 'SXT', 'SYRE', 'TAP',
    'TEM', 'TEX', 'TFX', 'TGTX', 'THG', 'TIGO', 'TKR', 'TLN', 'TPG', 'TRNO',
    'TRU', 'TTC', 'TTD', 'TTEK', 'TTMI', 'TVTX', 'TW', 'TWST', 'TXG', 'TXNM',
    'TXRH', 'U', 'UBSI', 'UFPI', 'UGI', 'UHAL.B', 'ULS', 'UMBF', 'UNM', 'VIAV',
    'VIK', 'VLY', 'VMI', 'VNO', 'VNOM', 'VNT', 'VOYA', 'VRNS', 'VSAT', 'VSEC',
    'VSNT', 'VSXY', 'W', 'WAL', 'WEX', 'WFRD', 'WH', 'WMS', 'WPC', 'WSO',
    'WTFC', 'WTM', 'WTS', 'WULF', 'XENE', 'XP', 'Z', 'ZETA', 'ZION', 'ZWS'
);

-- r3k_depth_draw (74 names)
UPDATE instruments SET universe_cohort = 'r3k_depth_draw' WHERE symbol IN (
    'AESI', 'AMCX', 'ANGI', 'ASC', 'ASPI', 'ASPN', 'AUGO', 'BATRA', 'BKV', 'BMBL',
    'BORR', 'BTU', 'CABO', 'CARG', 'CBT', 'CC', 'CCO', 'CLB', 'CMP', 'CNK',
    'CRGY', 'CVI', 'EGY', 'ELE', 'EU', 'EVER', 'FLNG', 'FUBO', 'FUL', 'GLIBA',
    'GPK', 'GPRE', 'GRNT', 'GSAT', 'GTN', 'HWKN', 'HYMC', 'IMAX', 'INVX', 'IPI',
    'LION', 'LPG', 'LXU', 'LZM', 'MAX', 'MCS', 'MTRN', 'MYE', 'NAT', 'NB',
    'NCMI', 'NEXN', 'NIQ', 'OII', 'PPTA', 'RIG', 'RYAM', 'SCL', 'SD', 'SEI',
    'SHEN', 'SXC', 'TRIP', 'TROX', 'TRS', 'TTAM', 'UAMY', 'UNIT', 'VTS', 'WHD',
    'WTI', 'WTTR', 'ZD', 'ZIP'
);

-- r3k_top500_fill (66 names)
UPDATE instruments SET universe_cohort = 'r3k_top500_fill' WHERE symbol IN (
    'AFRM', 'ALAB', 'ALNY', 'ATI', 'AU', 'BAM', 'CDE', 'CLH', 'CPNG', 'CRCL',
    'CRDO', 'CRS', 'CW', 'DINO', 'DT', 'ENTG', 'EWBC', 'FCNCA', 'FTAI', 'FTI',
    'FWONK', 'GH', 'HEI.A', 'INSM', 'ITT', 'JLL', 'LNG', 'LPLA', 'MDB', 'MKL',
    'MKSI', 'MTSI', 'NET', 'NTNX', 'NTRA', 'NU', 'NVT', 'OKTA', 'OVV', 'PR',
    'QSR', 'RBA', 'RBLX', 'RGA', 'RGLD', 'RKLB', 'ROIV', 'ROKU', 'RPRX', 'RS',
    'SCCO', 'SNOW', 'SNX', 'SOFI', 'SPCX', 'SPOT', 'SSNC', 'SUNB', 'TEAM', 'TOST',
    'TWLO', 'USFD', 'UTHR', 'WWD', 'XPO', 'ZM'
);

-- r3k_utilities_depth (18 names)
UPDATE instruments SET universe_cohort = 'r3k_utilities_depth' WHERE symbol IN (
    'AVA', 'AWR', 'BEPC', 'BIPC', 'CPK', 'CWCO', 'CWEN', 'GNE', 'HE', 'HTO',
    'MDU', 'MGEE', 'MNTK', 'MSEX', 'NWE', 'NWN', 'SR', 'UTL'
);

-- spx (368 names)
UPDATE instruments SET universe_cohort = 'spx' WHERE symbol IN (
    'A', 'ABBV', 'ABNB', 'ABT', 'ACGL', 'ACN', 'ADBE', 'ADI', 'ADP', 'ADSK',
    'AEE', 'AES', 'AFL', 'AIG', 'AIZ', 'AJG', 'AKAM', 'ALB', 'ALGN', 'ALL',
    'ALLE', 'AMAT', 'AMCR', 'AME', 'AMP', 'ANET', 'AON', 'AOS', 'APA', 'APD',
    'APH', 'APO', 'APP', 'APTV', 'ARE', 'ARES', 'AVY', 'AXON', 'AZO', 'BALL',
    'BAX', 'BBY', 'BDX', 'BE', 'BEN', 'BF.B', 'BG', 'BIIB', 'BKR', 'BMY',
    'BNY', 'BR', 'BRK.B', 'BRO', 'BSX', 'BX', 'BXP', 'C', 'CAH', 'CARR',
    'CB', 'CBOE', 'CBRE', 'CCI', 'CCL', 'CDNS', 'CDW', 'CEG', 'CF', 'CFG',
    'CHD', 'CHTR', 'CI', 'CIEN', 'CINF', 'CLX', 'CME', 'CMG', 'CMI', 'CMS',
    'CNC', 'CNP', 'COF', 'COHR', 'COO', 'COR', 'CPAY', 'CPRT', 'CPT', 'CRH',
    'CRL', 'CSGP', 'CTAS', 'CTSH', 'CVNA', 'DASH', 'DDOG', 'DECK', 'DELL', 'DG',
    'DGX', 'DHR', 'DLR', 'DLTR', 'DOC', 'DOV', 'DPZ', 'DRI', 'DTE', 'DVA',
    'DVN', 'DXCM', 'EBAY', 'ECHO', 'EFX', 'EG', 'EL', 'EME', 'EOG', 'EQT',
    'ERIE', 'ESS', 'ETN', 'EVRG', 'EW', 'EXE', 'EXPE', 'EXR', 'FANG', 'FAST',
    'FDS', 'FERG', 'FFIV', 'FICO', 'FIS', 'FISV', 'FITB', 'FIX', 'FLEX', 'FOXA',
    'FRT', 'FTNT', 'FTV', 'GD', 'GDDY', 'GEHC', 'GEN', 'GIS', 'GL', 'GLW',
    'GNRC', 'GPC', 'GPN', 'GRMN', 'GWW', 'HAL', 'HAS', 'HBAN', 'HIG', 'HII',
    'HLT', 'HONA', 'HOOD', 'HPE', 'HPQ', 'HRL', 'HSIC', 'HST', 'HSY', 'HUBB',
    'HUM', 'HWM', 'IBKR', 'ICE', 'IDXX', 'IEX', 'IFF', 'ILMN', 'INCY', 'INTC',
    'INTU', 'INVH', 'IP', 'IQV', 'IR', 'IRM', 'IT', 'ITW', 'IVZ', 'J',
    'JBL', 'JCI', 'JKHY', 'KDP', 'KEY', 'KEYS', 'KHC', 'KIM', 'KKR', 'KLAC',
    'KMB', 'KR', 'KVUE', 'L', 'LDOS', 'LH', 'LHX', 'LII', 'LITE', 'LNT',
    'LOW', 'LRCX', 'LULU', 'LVS', 'LYB', 'LYV', 'MA', 'MAA', 'MAS', 'MCHP',
    'MCK', 'MCO', 'MDLZ', 'MDT', 'MET', 'MKC', 'MLM', 'MNST', 'MOS', 'MPC',
    'MPWR', 'MRNA', 'MRSH', 'MRVL', 'MSCI', 'MSI', 'MTB', 'MTD', 'MU', 'NCLH',
    'NDAQ', 'NDSN', 'NI', 'NOC', 'NOW', 'NRG', 'NTAP', 'NTRS', 'NWSA', 'NXPI',
    'O', 'OKE', 'OMC', 'ON', 'ORCL', 'ORLY', 'OTIS', 'P', 'PAYX', 'PCAR',
    'PCG', 'PFG', 'PH', 'PHM', 'PKG', 'PLTR', 'PNC', 'PNR', 'PNW', 'PODD',
    'PPG', 'PPL', 'PRU', 'PSA', 'PSKY', 'PSX', 'PTC', 'PWR', 'PYPL', 'Q',
    'RDDT', 'REG', 'RF', 'RL', 'RMD', 'ROK', 'ROL', 'ROP', 'ROST', 'RSG',
    'RVTY', 'SBAC', 'SBUX', 'SCHW', 'SJM', 'SMCI', 'SNA', 'SNDK', 'SNPS', 'SOLV',
    'SPGI', 'STE', 'STLD', 'STT', 'STX', 'STZ', 'SW', 'SWK', 'SWKS', 'SYF',
    'SYK', 'SYY', 'TDG', 'TDY', 'TECH', 'TEL', 'TER', 'TFC', 'TGT', 'TJX',
    'TKO', 'TMO', 'TPL', 'TPR', 'TRGP', 'TRMB', 'TROW', 'TSCO', 'TSN', 'TT',
    'TTWO', 'TXN', 'TYL', 'UDR', 'UHS', 'ULTA', 'URI', 'VEEV', 'VICI', 'VLO',
    'VLTO', 'VMC', 'VMRK', 'VRSK', 'VRSN', 'VRT', 'VTR', 'VTRS', 'WAB', 'WAT',
    'WBD', 'WDAY', 'WDC', 'WEC', 'WELL', 'WFC', 'WM', 'WRB', 'WST', 'WTW',
    'WY', 'WYNN', 'XYL', 'XYZ', 'YUM', 'ZBH', 'ZBRA', 'ZTS'
);
-- ---------------------------------------------------------------------------
-- research_run.universe_hash: the run's universe identity, recorded once at finish
-- ---------------------------------------------------------------------------

ALTER TABLE research_run ADD COLUMN universe_hash text;

COMMENT ON COLUMN research_run.universe_hash IS
    'sha256 over the S0 snapshot''s symbol list: the promoted universe the attempt ran on. '
    'NULL→value once at finish, with snapshot_hash; recorded runs before migration 551 keep '
    'NULL (todo 491). Not a vintage.';

CREATE OR REPLACE FUNCTION fn_research_run_guard()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'started' THEN
            RAISE EXCEPTION 'research_run is append-only: a row must be inserted as started, got %',
                NEW.status
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.evidence IS NOT NULL OR NEW.finished_at IS NOT NULL
           OR NEW.snapshot_hash IS NOT NULL
           OR NEW.decision_t IS NOT NULL OR NEW.decision_p IS NOT NULL
           OR NEW.gross_sharpe IS NOT NULL OR NEW.mean_session_pnl IS NOT NULL
           OR NEW.turnover_per_session IS NOT NULL OR NEW.n_sessions IS NOT NULL
           OR NEW.span_start IS NOT NULL OR NEW.span_end IS NOT NULL
           OR NEW.n_families IS NOT NULL OR NEW.effective_breadth IS NOT NULL
           OR NEW.top_group_share IS NOT NULL OR NEW.lofo_max_t_drop IS NOT NULL
           OR NEW.sign_stability_min IS NOT NULL
           OR NEW.universe_hash IS NOT NULL THEN
            RAISE EXCEPTION 'research_run is append-only: a started row carries no evidence, '
                'finished_at, snapshot_hash, headline numbers or universe_hash'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;

    -- UPDATE
    IF OLD.status <> 'started' THEN
        RAISE EXCEPTION 'research_run is append-only: run % is already terminal (%)',
            OLD.run_id, OLD.status
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status NOT IN ('completed', 'guard_failed', 'refused', 'failed') THEN
        RAISE EXCEPTION 'research_run is append-only: a started row may only move to a '
            'terminal status, got %', NEW.status
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.finished_at IS NULL THEN
        RAISE EXCEPTION 'research_run is append-only: a terminal row needs finished_at'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.run_id IS DISTINCT FROM OLD.run_id
       OR NEW.run_group IS DISTINCT FROM OLD.run_group
       OR NEW.concept_id IS DISTINCT FROM OLD.concept_id
       OR NEW.kind IS DISTINCT FROM OLD.kind
       OR NEW.mode IS DISTINCT FROM OLD.mode
       OR NEW.spec_path IS DISTINCT FROM OLD.spec_path
       OR NEW.spec_hash IS DISTINCT FROM OLD.spec_hash
       OR NEW.spec_blob IS DISTINCT FROM OLD.spec_blob
       OR NEW.code_commit IS DISTINCT FROM OLD.code_commit
       OR NEW.vintage IS DISTINCT FROM OLD.vintage
       OR NEW.budget_m IS DISTINCT FROM OLD.budget_m
       OR NEW.screen_alpha IS DISTINCT FROM OLD.screen_alpha
       OR NEW.started_at IS DISTINCT FROM OLD.started_at
       OR NEW.recipe_hash IS DISTINCT FROM OLD.recipe_hash
       OR NEW.informed_by IS DISTINCT FROM OLD.informed_by THEN
        RAISE EXCEPTION 'research_run is append-only: only status, snapshot_hash, universe_hash, '
            'evidence, finished_at and the headline numbers change, once'
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.snapshot_hash IS NOT NULL
       AND NEW.snapshot_hash IS DISTINCT FROM OLD.snapshot_hash THEN
        RAISE EXCEPTION 'research_run is append-only: snapshot_hash may go from NULL to a '
            'value, never change'
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.universe_hash IS NOT NULL
       AND NEW.universe_hash IS DISTINCT FROM OLD.universe_hash THEN
        RAISE EXCEPTION 'research_run is append-only: universe_hash may go from NULL to a '
            'value, never change'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION fn_research_run_guard() IS
    'research_run append-only guard (migration 366; headline numbers by 515 and 538; '
    'universe_hash added by 551): INSERT must be started with no evidence, finished_at, '
    'snapshot_hash, headline numbers or universe_hash; UPDATE only moves a started row to a '
    'terminal status once, setting finished_at, evidence and snapshot_hash and universe_hash '
    '(each NULL to value only); every other column is immutable.';

COMMIT;
