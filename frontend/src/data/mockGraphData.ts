import { GraphEntity } from '../types/graph';

export const GRAPH_ENTITIES: Record<string, GraphEntity> = {
  // 1. TATASTEEL
  TATASTEEL: {
    id: 'TATASTEEL',
    title: 'Tata Steel Limited',
    type: 'Stock',
    sector: 'Metals & Mining',
    exchange: 'NSE',
    avatar: 'TS',
    color: '#38BDF8',
    description: 'India-based multinational steel-making company. High sensitivity to imported metallurgical coal and coking coal benchmarks.',
    edges: [
      {
        id: 'COKING_COAL',
        label: 'EXPOSED_TO',
        type: 'Commodity',
        confidence: 0.88,
        impact: 'NEGATIVE',
        note: 'Australian coking coal FOB +$24/t raises hot metal conversion cost',
        marginImpactPct: '-8.2% MARGIN',
        rationale: "Tata Steel's domestic blast furnace operations consume ~0.77 tonnes of imported hard coking coal per tonne of hot metal. Premium low-volatile coking coal FOB Australia jumped +$24/tonne, exerting immediate 180-220 bps EBITDA margin pressure.",
        vendor: 'PLATTS_APAC',
        timeAgo: '20 min ago',
        imageUrl: 'https://images.unsplash.com/photo-1578328819058-b69f3a3b0f6b?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'HRC_STEEL',
        label: 'EXPOSED_TO',
        type: 'Commodity',
        confidence: 0.94,
        impact: 'POSITIVE',
        note: 'Domestic flat steel benchmark realizations uptick +₹1,200/t',
        marginImpactPct: '+4.5% REALIZATION',
        rationale: 'Domestic flat steel HRC prices in Mumbai wholesale market rose by ₹1,200 per metric tonne, partially neutralizing input raw material surge.',
        vendor: 'STEELMINT',
        timeAgo: '45 min ago',
        imageUrl: 'https://images.unsplash.com/photo-1504917599217-d4dc5ebe6122?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'RBI_REPO_RATE',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Macro',
        confidence: 0.72,
        impact: 'NEGATIVE',
        note: 'Higher rate elevates long-term capex debt refinancing costs',
        marginImpactPct: 'WACC +35bps',
        rationale: 'Long-term debt for Kalinganagar phase 2 capex experiences elevated servicing cost under persistent 6.50% repo rate.',
        vendor: 'RBI_BULLETIN',
        timeAgo: '2h ago',
        imageUrl: 'https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'CHINA_STIMULUS',
        label: 'DIRECTLY_IMPACTS',
        type: 'News',
        confidence: 0.91,
        impact: 'POSITIVE',
        note: 'Beijing infrastructure package lifting regional Asian steel spreads',
        marginImpactPct: '+6.1% SPREAD',
        rationale: 'China Ministry of Finance announced infrastructure bond quotas, slowing steel export dumping into Southeast Asia and improving regional pricing power.',
        vendor: 'REUTERS',
        timeAgo: '3h ago',
        imageUrl: 'https://images.unsplash.com/photo-1586528116311-ad8dd3c8310d?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: [
      {
        id: 'card-coking-coal',
        typeBadge: 'Commodity Shock',
        tag: 'COKING_COAL',
        badgeHalo: 'halo-orange',
        relationLabel: '[:EXPOSED_TO]',
        confidence: 0.88,
        timeAgo: '20 min ago · Reuters/Platts',
        source: 'PLATTS_APAC',
        headline: 'Queensland Coking Coal Port Disruptions Trigger Raw Material Cost Inflation',
        causalRationale: "Tata Steel's domestic blast furnace operations consume ~0.77 tonnes of imported hard coking coal per tonne of hot metal. Premium low-volatile coking coal FOB Australia jumped +$24/tonne, exerting immediate 180-220 bps EBITDA margin pressure.",
        vendorOrMeta: 'Vendor: PLATTS_APAC · Margin Impact: NEGATIVE',
        statVisual: {
          primaryText: '-8.2%',
          subText: 'MARGIN IMPACT',
        }
      },
      {
        id: 'card-rbi-repo',
        typeBadge: 'Macro Shock',
        tag: 'BROAD_SCOPE',
        badgeHalo: 'halo-purple',
        relationLabel: '[:SENSITIVE_TO_MACRO]',
        confidence: 0.72,
        timeAgo: '2h ago · RBI MPC Bulletin',
        source: 'RBI_MPC',
        headline: 'MPC Retains Hawkish Stance on High Food Inflation & System Liquidity Deficit',
        causalRationale: 'Sustained elevated rates increase borrowing costs on capex cycles and keep 10-year G-sec yields pinned above 7.15%, raising weighted average cost of capital (WACC) across leveraged infrastructure.',
        vendorOrMeta: 'Transmission: Capital Expenditure Servicing & Bond Yields',
        statVisual: {
          primaryText: '6.50%',
          subText: 'RBI REPO RATE',
          secondaryText: 'Broad Contagion'
        }
      }
    ]
  },

  // 2. RELIANCE
  RELIANCE: {
    id: 'RELIANCE',
    title: 'Reliance Industries Ltd',
    type: 'Stock',
    sector: 'Conglomerate / Energy',
    exchange: 'NSE',
    avatar: 'RIL',
    color: '#38BDF8',
    description: 'Integrated multinational conglomerate spanning oil-to-chemicals, telecommunications (Jio), retail, and green energy investments.',
    edges: [
      {
        id: 'BRENT_CRUDE',
        label: 'EXPOSED_TO',
        type: 'Commodity',
        confidence: 0.89,
        impact: 'MIXED',
        note: 'Jamnagar gross refining margins sensitive to heavy-light crude differentials',
        marginImpactPct: 'GRM $11.8/bbl',
        vendor: 'PLATTS_GLOBAL',
        imageUrl: 'https://images.unsplash.com/photo-1518709268805-4e9042af9f23?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'USD_INR_FX',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Macro',
        confidence: 0.82,
        impact: 'POSITIVE',
        note: 'Export refining earnings booked in USD benefit from rupee depreciation',
        marginImpactPct: '+₹420Cr / 1% drop',
        vendor: 'FEDAI',
        imageUrl: 'https://images.unsplash.com/photo-1580519542036-c47de6196ba5?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'TELECOM_TARIFF',
        label: 'IMPACTS_SECTOR',
        type: 'News',
        confidence: 0.86,
        impact: 'POSITIVE',
        note: 'Headline tariff hikes lift Jio wireless ARPU projections to ₹215',
        marginImpactPct: '+11% ARPU',
        vendor: 'TRAI_FILING',
        imageUrl: 'https://images.unsplash.com/photo-1544717305-2782549b5136?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: [
      {
        id: 'card-brent-reliance',
        typeBadge: 'Feedstock Dynamics',
        tag: 'BRENT_CRUDE',
        badgeHalo: 'halo-orange',
        relationLabel: '[:EXPOSED_TO]',
        confidence: 0.89,
        timeAgo: '1h ago · Platts Global',
        source: 'S&P_GLOBAL',
        headline: 'Singapore Complex Refining Margin Swings Impact Jamnagar Run Rates',
        causalRationale: 'Reliance Jamnagar complex processes heavy crude grades. Widening diesel and jet fuel crack spreads boost Gross Refining Margins (GRM) above $11.5/bbl.',
        vendorOrMeta: 'Vendor: PLATTS · Impact: Positive GRM Leverage',
        statVisual: {
          primaryText: '$11.8',
          subText: 'GRM / BARREL',
        }
      }
    ]
  },

  // 3. HDFCBANK
  HDFCBANK: {
    id: 'HDFCBANK',
    title: 'HDFC Bank Limited',
    type: 'Stock',
    sector: 'Financial Services',
    exchange: 'NSE',
    avatar: 'HDFC',
    color: '#38BDF8',
    description: "India's largest private sector bank following post-merger balance-sheet integration with parent HDFC Limited.",
    edges: [
      {
        id: 'RBI_REPO_RATE',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Macro',
        confidence: 0.95,
        impact: 'MIXED',
        note: 'Net Interest Margin (NIM) under pressure from elevated cost of deposits',
        marginImpactPct: 'NIM 3.45%',
        vendor: 'RBI_REPORT',
        imageUrl: 'https://images.unsplash.com/photo-1556742049-0a67e557224d?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'INDIA_10Y_YIELD',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Macro',
        confidence: 0.84,
        impact: 'NEGATIVE',
        note: 'Treasury book mark-to-market exposure tied to 10Y sovereign yields',
        marginImpactPct: 'Treasury -₹140Cr',
        vendor: 'CCIL',
        imageUrl: 'https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'LDR_COMPLIANCE',
        label: 'DIRECTLY_IMPACTS',
        type: 'News',
        confidence: 0.89,
        impact: 'POSITIVE',
        note: 'Credit-Deposit ratio glides down toward RBI prudential thresholds',
        marginImpactPct: 'LDR 89.2%',
        vendor: 'BSE_DISCLOSURE',
        imageUrl: 'https://images.unsplash.com/photo-1526304640581-d334cdbbf45e?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: [
      {
        id: 'card-ldr-hdfc',
        typeBadge: 'Balance Sheet Milestone',
        tag: 'REG_30_FILING',
        badgeHalo: 'halo-emerald',
        relationLabel: '[:DIRECTLY_IMPACTS]',
        confidence: 0.89,
        timeAgo: '1d ago · BSE Disclosures',
        source: 'BSE_REG30',
        headline: 'Credit-Deposit Ratio Normalization Ahead of Management Target',
        causalRationale: 'Accelerated branch deposit mobilization brings Loan-to-Deposit ratio below 90%, lifting restrictive margin overhang.',
        vendorOrMeta: 'Source: Official Exchange Reg-30 Filing',
        statVisual: {
          primaryText: '89.2%',
          subText: 'LDR TARGET',
          secondaryText: 'Risk De-escalation'
        }
      }
    ]
  },

  // 4. ASIANPAINTS
  ASIANPAINTS: {
    id: 'ASIANPAINTS',
    title: 'Asian Paints Limited',
    type: 'Stock',
    sector: 'Consumer Discretionary',
    exchange: 'NSE',
    avatar: 'PAINT',
    color: '#F43F5E',
    description: 'Leading Indian paint manufacturing corporation with over 50% market share in decorative coatings.',
    edges: [
      {
        id: 'BRENT_CRUDE',
        label: 'EXPOSED_TO',
        type: 'Commodity',
        confidence: 0.92,
        impact: 'NEGATIVE',
        note: 'Crude and petrochemical derivatives comprise over 35% of total input COGS',
        marginImpactPct: '-240bps Gross Margin',
        vendor: 'PLATTS',
        imageUrl: 'https://images.unsplash.com/photo-1589939705384-5185137a7f0f?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'USD_INR_FX',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Macro',
        confidence: 0.78,
        impact: 'NEGATIVE',
        note: 'Titanium dioxide (TiO2) and monomer imports invoiced in USD',
        marginImpactPct: '-₹85Cr FX headwind',
        vendor: 'FEDAI',
        imageUrl: 'https://images.unsplash.com/photo-1580519542036-c47de6196ba5?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 5. INFY (Infosys)
  INFY: {
    id: 'INFY',
    title: 'Infosys Limited',
    type: 'Stock',
    sector: 'Information Technology',
    exchange: 'NSE',
    avatar: 'INFY',
    color: '#0284C7',
    description: 'Global IT consulting, cloud services, and digital transformation powerhouse serving Fortune 500 enterprises.',
    edges: [
      {
        id: 'US_FED_RATE',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Macro',
        confidence: 0.91,
        impact: 'NEGATIVE',
        note: 'High US interest rates delay discretionary tech spend and corporate cloud migration budgets',
        marginImpactPct: '-120bps TCV growth',
        vendor: 'BLOOMBERG',
        imageUrl: 'https://images.unsplash.com/photo-1551288049-bebda4e38f71?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'USD_INR_FX',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Macro',
        confidence: 0.88,
        impact: 'POSITIVE',
        note: 'Rupee depreciation directly expands rupee EBIT margins on overseas billing',
        marginImpactPct: '+35bps EBIT / 1% INR drop',
        vendor: 'FEDAI',
        imageUrl: 'https://images.unsplash.com/photo-1580519542036-c47de6196ba5?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 6. TCS
  TCS: {
    id: 'TCS',
    title: 'Tata Consultancy Services',
    type: 'Stock',
    sector: 'Information Technology',
    exchange: 'NSE',
    avatar: 'TCS',
    color: '#818CF8',
    description: "India's highest market-cap IT services exporter with deep banking, financial services, and retail client footprint.",
    edges: [
      {
        id: 'US_FED_RATE',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Macro',
        confidence: 0.93,
        impact: 'NEGATIVE',
        note: 'US BFSI client capex pipeline sensitive to Federal Reserve rate expectations',
        marginImpactPct: '-80bps BFSI growth',
        vendor: 'REUTERS',
        imageUrl: 'https://images.unsplash.com/photo-1516321318423-f06f85e504b3?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'USD_INR_FX',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Macro',
        confidence: 0.89,
        impact: 'POSITIVE',
        note: 'Over 50% revenue from North America invoiced in USD',
        marginImpactPct: '+40bps EBIT per 100bps INR move',
        vendor: 'FEDAI',
        imageUrl: 'https://images.unsplash.com/photo-1580519542036-c47de6196ba5?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 7. ICICIBANK
  ICICIBANK: {
    id: 'ICICIBANK',
    title: 'ICICI Bank Limited',
    type: 'Stock',
    sector: 'Financial Services',
    exchange: 'NSE',
    avatar: 'ICICI',
    color: '#F97316',
    description: 'Premier private sector bank with industry-leading Return on Assets (RoA > 2.3%) and strong retail/SME franchise.',
    edges: [
      {
        id: 'RBI_REPO_RATE',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Macro',
        confidence: 0.94,
        impact: 'MIXED',
        note: 'Rapid transmission to external benchmark lending rates protects domestic NIM',
        marginImpactPct: 'NIM 4.36%',
        vendor: 'RBI',
        imageUrl: 'https://images.unsplash.com/photo-1556742049-0a67e557224d?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'INDIA_10Y_YIELD',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Macro',
        confidence: 0.82,
        impact: 'MIXED',
        note: 'Strong deposit franchise insulates against liquidity tightening',
        marginImpactPct: 'RoA 2.38%',
        vendor: 'CCIL',
        imageUrl: 'https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 8. SBIN
  SBIN: {
    id: 'SBIN',
    title: 'State Bank of India',
    type: 'Stock',
    sector: 'Public Sector Banking',
    exchange: 'NSE',
    avatar: 'SBIN',
    color: '#0284C7',
    description: "India's largest public lender with ~25% total banking asset market share and extensive rural and corporate presence.",
    edges: [
      {
        id: 'GOVT_CAPEX_SPEND',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Macro',
        confidence: 0.92,
        impact: 'POSITIVE',
        note: 'Sole/Lead consortium banker across major central and state infrastructure projects',
        marginImpactPct: '+15.4% Corporate Loan Growth',
        vendor: 'MIN_FIN',
        imageUrl: 'https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'INDIA_10Y_YIELD',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Macro',
        confidence: 0.86,
        impact: 'MIXED',
        note: 'Massive statutory liquidity ratio (SLR) bond portfolio subject to yield revaluations',
        marginImpactPct: 'Investment Yield 6.85%',
        vendor: 'RBI',
        imageUrl: 'https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 9. LT (Larsen & Toubro)
  LT: {
    id: 'LT',
    title: 'Larsen & Toubro Ltd',
    type: 'Stock',
    sector: 'Capital Goods / Infrastructure',
    exchange: 'NSE',
    avatar: 'LT',
    color: '#22C55E',
    description: "India's premier engineering, procurement, and construction conglomerate with ₹4.7 lakh crore order backlog.",
    edges: [
      {
        id: 'GOVT_CAPEX_SPEND',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Macro',
        confidence: 0.96,
        impact: 'POSITIVE',
        note: 'Central infrastructure allocations directly drive domestic order inflows across railways, roads, and power',
        marginImpactPct: '+18% Order Inflow YoY',
        vendor: 'BUDGET_ANALYSIS',
        imageUrl: 'https://images.unsplash.com/photo-1541888946425-d0fbb186c5f7?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'HRC_STEEL',
        label: 'EXPOSED_TO',
        type: 'Commodity',
        confidence: 0.85,
        impact: 'NEGATIVE',
        note: 'Fabrication steel prices affect fixed-price legacy engineering contracts',
        marginImpactPct: '-45bps EBITDA',
        vendor: 'STEELMINT',
        imageUrl: 'https://images.unsplash.com/photo-1504917599217-d4dc5ebe6122?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 10. MARUTI
  MARUTI: {
    id: 'MARUTI',
    title: 'Maruti Suzuki India',
    type: 'Stock',
    sector: 'Automobile',
    exchange: 'NSE',
    avatar: 'MSIL',
    color: '#6366F1',
    description: 'Leading passenger automobile manufacturer in India with >40% passenger vehicle market share.',
    edges: [
      {
        id: 'HRC_STEEL',
        label: 'EXPOSED_TO',
        type: 'Commodity',
        confidence: 0.89,
        impact: 'NEGATIVE',
        note: 'Automotive grade cold-rolled and flat steel is prime structural raw material',
        marginImpactPct: '-60bps Operating Margin',
        vendor: 'STEELMINT',
        imageUrl: 'https://images.unsplash.com/photo-1504917599217-d4dc5ebe6122?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'ALUMINIUM',
        label: 'EXPOSED_TO',
        type: 'Commodity',
        confidence: 0.82,
        impact: 'NEGATIVE',
        note: 'Engine blocks and lightweight structural components drive aluminium demand',
        marginImpactPct: '-35bps Gross Margin',
        vendor: 'MCX',
        imageUrl: 'https://images.unsplash.com/photo-1538356111053-748a48e1acb8?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 11. SUNPHARMA
  SUNPHARMA: {
    id: 'SUNPHARMA',
    title: 'Sun Pharmaceutical Industries',
    type: 'Stock',
    sector: 'Healthcare / Pharmaceuticals',
    exchange: 'NSE',
    avatar: 'SUN',
    color: '#EC4899',
    description: 'Leading global specialty generic pharmaceutical company with strong US dermatological and Indian branded formulations.',
    edges: [
      {
        id: 'USD_INR_FX',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Macro',
        confidence: 0.87,
        impact: 'POSITIVE',
        note: 'Export formulations invoiced in USD generate natural currency hedge and margin upside',
        marginImpactPct: '+25bps EBITDA / 1% drop',
        vendor: 'FEDAI',
        imageUrl: 'https://images.unsplash.com/photo-1584308666744-24d5c474f2ae?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 12. ITC
  ITC: {
    id: 'ITC',
    title: 'ITC Limited',
    type: 'Stock',
    sector: 'Fast Moving Consumer Goods',
    exchange: 'NSE',
    avatar: 'ITC',
    color: '#EAB308',
    description: 'Diversified conglomerate commanding dominant market share in legal cigarettes, branded packaged foods, agri-business, and luxury hotels.',
    edges: [
      {
        id: 'INDIA_CPI',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Macro',
        confidence: 0.84,
        impact: 'MIXED',
        note: 'Rural consumption recovery and food inflation determine agri & branded foods volume growth',
        marginImpactPct: '+8.2% FMCG Others YoY',
        vendor: 'MOSPI',
        imageUrl: 'https://images.unsplash.com/photo-1542838132-92c53300491e?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 13. BAJFINANCE
  BAJFINANCE: {
    id: 'BAJFINANCE',
    title: 'Bajaj Finance Limited',
    type: 'Stock',
    sector: 'NBFC / Consumer Finance',
    exchange: 'NSE',
    avatar: 'BAJ',
    color: '#3B82F6',
    description: "India's highest valuation consumer lending non-bank with over 80 million active customer franchises across consumer electronics and SME loans.",
    edges: [
      {
        id: 'RBI_REPO_RATE',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Macro',
        confidence: 0.91,
        impact: 'NEGATIVE',
        note: 'Fixed-rate consumer asset duration leads to borrowing cost lag during high repo rate environments',
        marginImpactPct: '-25bps NIM Compression',
        vendor: 'RBI',
        imageUrl: 'https://images.unsplash.com/photo-1563986768609-322da13575f3?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 14. JSWSTEEL
  JSWSTEEL: {
    id: 'JSWSTEEL',
    title: 'JSW Steel Limited',
    type: 'Stock',
    sector: 'Metals & Mining',
    exchange: 'NSE',
    avatar: 'JSW',
    color: '#0284C7',
    description: 'One of the fastest-growing steelmakers with extensive capacity across Vijayanagar and Dolvi plants.',
    edges: [
      {
        id: 'COKING_COAL',
        label: 'EXPOSED_TO',
        type: 'Commodity',
        confidence: 0.93,
        impact: 'NEGATIVE',
        note: 'High reliance on imported Australian metallurgical coal for blast furnace feeds',
        marginImpactPct: '-7.5% Operating Margin',
        vendor: 'PLATTS',
        imageUrl: 'https://images.unsplash.com/photo-1578328819058-b69f3a3b0f6b?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'CHINA_STIMULUS',
        label: 'DIRECTLY_IMPACTS',
        type: 'News',
        confidence: 0.89,
        impact: 'POSITIVE',
        note: 'Chinese steel production discipline prevents aggressive Asian dumping',
        marginImpactPct: '+5% Price Realization',
        vendor: 'REUTERS',
        imageUrl: 'https://images.unsplash.com/photo-1586528116311-ad8dd3c8310d?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 15. BHARTIARTL
  BHARTIARTL: {
    id: 'BHARTIARTL',
    title: 'Bharti Airtel Limited',
    type: 'Stock',
    sector: 'Telecommunications',
    exchange: 'NSE',
    avatar: 'AIRTEL',
    color: '#EF4444',
    description: 'Leading telecommunications services provider with expansive Indian mobile, home broadband, enterprise, and Africa operations.',
    edges: [
      {
        id: 'TELECOM_TARIFF',
        label: 'IMPACTS_SECTOR',
        type: 'News',
        confidence: 0.95,
        impact: 'POSITIVE',
        note: 'Headline mobile tariff hike flow-through lifts monthly blended ARPU toward ₹225',
        marginImpactPct: '+₹2,100Cr Annual EBITDA',
        vendor: 'TRAI',
        imageUrl: 'https://images.unsplash.com/photo-1544717305-2782549b5136?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 16. TITAN
  TITAN: {
    id: 'TITAN',
    title: 'Titan Company Limited',
    type: 'Stock',
    sector: 'Consumer Discretionary',
    exchange: 'NSE',
    avatar: 'TITAN',
    color: '#EAB308',
    description: 'Market leader in branded jewellery (Tanishq), watches, and eyewear with exceptional retail compounding history.',
    edges: [
      {
        id: 'GOLD_MCX',
        label: 'EXPOSED_TO',
        type: 'Commodity',
        confidence: 0.96,
        impact: 'MIXED',
        note: 'Domestic gold import duty reductions and spot gold rallies drive customer buying and hedging costs',
        marginImpactPct: '+22% Jewellery Revenue YoY',
        vendor: 'IBJA',
        imageUrl: 'https://images.unsplash.com/photo-1610375461246-83df859d849d?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 17. COKING_COAL
  COKING_COAL: {
    id: 'COKING_COAL',
    title: 'Hard Coking Coal (FOB Aus)',
    type: 'Commodity',
    sector: 'Bulk Commodities',
    exchange: 'Platts / Global',
    avatar: 'COAL',
    color: '#F97316',
    description: 'Essential metallurgical coal input for blast furnace steel-making. High volatility driven by Australian weather and supply constraints.',
    edges: [
      {
        id: 'TATASTEEL',
        label: 'EXPOSED_TO',
        type: 'Stock',
        confidence: 0.88,
        impact: 'NEGATIVE',
        note: 'Primary raw material cost driver for blast furnaces',
        vendor: 'PLATTS',
        imageUrl: 'https://images.unsplash.com/photo-1504917599217-d4dc5ebe6122?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'HRC_STEEL',
        label: 'RELATED_TO',
        type: 'Commodity',
        confidence: 0.91,
        impact: 'POSITIVE',
        note: 'Cost-push inflation pushes steel mills to raise base quotation rates',
        vendor: 'STEELMINT',
        imageUrl: 'https://images.unsplash.com/photo-1504917599217-d4dc5ebe6122?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 18. HRC_STEEL
  HRC_STEEL: {
    id: 'HRC_STEEL',
    title: 'Hot Rolled Coil Steel Benchmark',
    type: 'Commodity',
    sector: 'Ferrous Metals',
    exchange: 'Domestic Wholesale',
    avatar: 'HRC',
    color: '#38BDF8',
    description: 'Key industrial steel product used across infrastructure, automotive framing, and pipe manufacturing.',
    edges: [
      {
        id: 'TATASTEEL',
        label: 'EXPOSED_TO',
        type: 'Stock',
        confidence: 0.94,
        impact: 'POSITIVE',
        note: 'Primary product realization metric',
        vendor: 'STEELMINT',
        imageUrl: 'https://images.unsplash.com/photo-1504917599217-d4dc5ebe6122?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'MARUTI',
        label: 'EXPOSED_TO',
        type: 'Stock',
        confidence: 0.89,
        impact: 'NEGATIVE',
        note: 'Input steel sheet procurement costs',
        vendor: 'STEELMINT',
        imageUrl: 'https://images.unsplash.com/photo-1504917599217-d4dc5ebe6122?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 19. BRENT_CRUDE
  BRENT_CRUDE: {
    id: 'BRENT_CRUDE',
    title: 'Brent Crude Benchmark',
    type: 'Commodity',
    sector: 'Global Energy',
    exchange: 'Global',
    avatar: 'OIL',
    color: '#F97316',
    description: 'International crude oil benchmark with extensive second-order transmission across paints, aviation, and national trade balance.',
    edges: [
      {
        id: 'RELIANCE',
        label: 'EXPOSED_TO',
        type: 'Stock',
        confidence: 0.89,
        impact: 'MIXED',
        note: 'Refinery input and gross refining margin driver',
        vendor: 'UPSTOX',
        imageUrl: 'https://images.unsplash.com/photo-1518709268805-4e9042af9f23?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'ASIANPAINTS',
        label: 'EXPOSED_TO',
        type: 'Stock',
        confidence: 0.92,
        impact: 'NEGATIVE',
        note: 'Crude derivatives comprise >35% of decorative paint cost of goods sold',
        vendor: 'SELLER_INTEL',
        imageUrl: 'https://images.unsplash.com/photo-1589939705384-5185137a7f0f?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'USD_INR_FX',
        label: 'RELATED_TO',
        type: 'Macro',
        confidence: 0.79,
        impact: 'NEGATIVE',
        note: 'Indian import bill expands with crude rally, pressuring the Rupee',
        vendor: 'RBI',
        imageUrl: 'https://images.unsplash.com/photo-1580519542036-c47de6196ba5?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 20. ALUMINIUM
  ALUMINIUM: {
    id: 'ALUMINIUM',
    title: 'Aluminium Primary Ingot (MCX/LME)',
    type: 'Commodity',
    sector: 'Non-Ferrous Metals',
    exchange: 'MCX / LME',
    avatar: 'AL',
    color: '#94A3B8',
    description: 'Lightweight industrial metal essential for electric mobility, transmission cables, and construction alloys.',
    edges: [
      {
        id: 'MARUTI',
        label: 'EXPOSED_TO',
        type: 'Stock',
        confidence: 0.82,
        impact: 'NEGATIVE',
        note: 'Engine blocks and wheel casts raw material cost component',
        vendor: 'MCX',
        imageUrl: 'https://images.unsplash.com/photo-1538356111053-748a48e1acb8?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'LT',
        label: 'EXPOSED_TO',
        type: 'Stock',
        confidence: 0.78,
        impact: 'NEGATIVE',
        note: 'Power transmission towers and electrical conductors procurement',
        vendor: 'MCX',
        imageUrl: 'https://images.unsplash.com/photo-1541888946425-d0fbb186c5f7?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 21. GOLD_MCX
  GOLD_MCX: {
    id: 'GOLD_MCX',
    title: 'Gold MCX Futures 10g',
    type: 'Commodity',
    sector: 'Precious Metals',
    exchange: 'MCX',
    avatar: 'AU',
    color: '#EAB308',
    description: 'Benchmark precious metal for Indian household savings, wedding demand, and global store-of-value reserves.',
    edges: [
      {
        id: 'TITAN',
        label: 'EXPOSED_TO',
        type: 'Stock',
        confidence: 0.96,
        impact: 'MIXED',
        note: 'Spot domestic bullion price sets jewellery retail tags and hedging lease rates',
        vendor: 'IBJA',
        imageUrl: 'https://images.unsplash.com/photo-1610375461246-83df859d849d?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'USD_INR_FX',
        label: 'RELATED_TO',
        type: 'Macro',
        confidence: 0.85,
        impact: 'NEGATIVE',
        note: 'Gold imports expand Current Account Deficit (CAD) when domestic demand surges',
        vendor: 'RBI',
        imageUrl: 'https://images.unsplash.com/photo-1580519542036-c47de6196ba5?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 22. NATURAL_GAS
  NATURAL_GAS: {
    id: 'NATURAL_GAS',
    title: 'Natural Gas Henry Hub / MCX',
    type: 'Commodity',
    sector: 'Energy',
    exchange: 'MCX',
    avatar: 'GAS',
    color: '#38BDF8',
    description: 'Clean energy feedstock vital for fertilizer plants, city gas distribution, and petrochemical cracking.',
    edges: [
      {
        id: 'RELIANCE',
        label: 'EXPOSED_TO',
        type: 'Stock',
        confidence: 0.86,
        impact: 'POSITIVE',
        note: 'KG D6 deepwater block gas production realizations improve with benchmark revisions',
        vendor: 'PPAC',
        imageUrl: 'https://images.unsplash.com/photo-1518709268805-4e9042af9f23?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 23. COPPER
  COPPER: {
    id: 'COPPER',
    title: 'Copper Cathode LME / MCX',
    type: 'Commodity',
    sector: 'Base Metals',
    exchange: 'LME / MCX',
    avatar: 'Cu',
    color: '#EA580C',
    description: '"Doctor Copper" — global economic bellwether essential for green energy transition and electrical grids.',
    edges: [
      {
        id: 'LT',
        label: 'EXPOSED_TO',
        type: 'Stock',
        confidence: 0.81,
        impact: 'NEGATIVE',
        note: 'Substation cabling and industrial machinery manufacturing inputs',
        vendor: 'LME',
        imageUrl: 'https://images.unsplash.com/photo-1541888946425-d0fbb186c5f7?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 24. RBI_REPO_RATE
  RBI_REPO_RATE: {
    id: 'RBI_REPO_RATE',
    title: 'RBI Monetary Policy Repo Rate',
    type: 'Macro',
    sector: 'Monetary Policy',
    exchange: 'RBI',
    avatar: 'RBI',
    color: '#A855F7',
    description: 'Key policy repo rate set by the RBI Monetary Policy Committee, transmitting broadly across Indian corporate borrowing and valuation multiples.',
    edges: [
      {
        id: 'HDFCBANK',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Stock',
        confidence: 0.95,
        impact: 'MIXED',
        note: 'Floating rate loan book resets immediately on policy changes',
        vendor: 'RBI',
        imageUrl: 'https://images.unsplash.com/photo-1556742049-0a67e557224d?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'TATASTEEL',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Stock',
        confidence: 0.72,
        impact: 'NEGATIVE',
        note: 'Capex discount rate adjustment across manufacturing infrastructure',
        vendor: 'RBI',
        imageUrl: 'https://images.unsplash.com/photo-1504917599217-d4dc5ebe6122?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 25. USD_INR_FX
  USD_INR_FX: {
    id: 'USD_INR_FX',
    title: 'USD/INR Foreign Exchange Rate',
    type: 'Macro',
    sector: 'Currency / Forex',
    exchange: 'FEDAI / RBI',
    avatar: 'FX',
    color: '#38BDF8',
    description: 'Exchange rate between the US Dollar and Indian Rupee. Dictates import bill parity, IT exporter yields, and FII flows.',
    edges: [
      {
        id: 'INFY',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Stock',
        confidence: 0.88,
        impact: 'POSITIVE',
        note: 'Exporters gain rupee realization tailwinds from weaker rupee',
        vendor: 'FEDAI',
        imageUrl: 'https://images.unsplash.com/photo-1580519542036-c47de6196ba5?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'RELIANCE',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Stock',
        confidence: 0.82,
        impact: 'POSITIVE',
        note: 'Petrochemical exports booked in USD',
        vendor: 'FEDAI',
        imageUrl: 'https://images.unsplash.com/photo-1580519542036-c47de6196ba5?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 26. INDIA_10Y_YIELD
  INDIA_10Y_YIELD: {
    id: 'INDIA_10Y_YIELD',
    title: 'India 10-Year Sovereign Benchmark Yield',
    type: 'Macro',
    sector: 'Fixed Income',
    exchange: 'CCIL',
    avatar: '10Y',
    color: '#A855F7',
    description: 'The risk-free discount rate anchor for Indian financial asset valuation and banking treasury books.',
    edges: [
      {
        id: 'HDFCBANK',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Stock',
        confidence: 0.84,
        impact: 'NEGATIVE',
        note: 'Treasury book marked-to-market against benchmark yields',
        vendor: 'CCIL',
        imageUrl: 'https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 27. INDIA_CPI
  INDIA_CPI: {
    id: 'INDIA_CPI',
    title: 'India CPI Headline Inflation',
    type: 'Macro',
    sector: 'Macroeconomic Indicator',
    exchange: 'MOSPI',
    avatar: 'CPI',
    color: '#F43F5E',
    description: 'Consumer Price Index tracking retail prices of food, fuel, and manufactured items across urban and rural India.',
    edges: [
      {
        id: 'RBI_REPO_RATE',
        label: 'RELATED_TO',
        type: 'Macro',
        confidence: 0.96,
        impact: 'POSITIVE',
        note: 'Persistent food inflation delays central bank rate pivot',
        vendor: 'RBI',
        imageUrl: 'https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'ITC',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Stock',
        confidence: 0.84,
        impact: 'MIXED',
        note: 'Rural disposable purchasing power indicator',
        vendor: 'MOSPI',
        imageUrl: 'https://images.unsplash.com/photo-1542838132-92c53300491e?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 28. US_FED_RATE
  US_FED_RATE: {
    id: 'US_FED_RATE',
    title: 'US Federal Funds Rate (5.25%-5.50%)',
    type: 'Macro',
    sector: 'Global Monetary Policy',
    exchange: 'US Federal Reserve',
    avatar: 'FED',
    color: '#3B82F6',
    description: 'World benchmark risk-free rate governing international capital flows, dollar strength, and tech sector valuations.',
    edges: [
      {
        id: 'INFY',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Stock',
        confidence: 0.91,
        impact: 'NEGATIVE',
        note: 'US corporate technology spend freeze during elevated Fed rate cycles',
        vendor: 'BLOOMBERG',
        imageUrl: 'https://images.unsplash.com/photo-1551288049-bebda4e38f71?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'USD_INR_FX',
        label: 'RELATED_TO',
        type: 'Macro',
        confidence: 0.87,
        impact: 'POSITIVE',
        note: 'Interest rate differential drives dollar index strength',
        vendor: 'FEDAI',
        imageUrl: 'https://images.unsplash.com/photo-1580519542036-c47de6196ba5?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 29. GOVT_CAPEX_SPEND
  GOVT_CAPEX_SPEND: {
    id: 'GOVT_CAPEX_SPEND',
    title: 'Union Budget Infrastructure Capex (₹11.1L Cr)',
    type: 'Macro',
    sector: 'Fiscal Policy',
    exchange: 'Ministry of Finance',
    avatar: 'CAPEX',
    color: '#10B981',
    description: 'Capital expenditure budgeted by the Central Government for railways, highways, ports, and defense manufacturing.',
    edges: [
      {
        id: 'LT',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Stock',
        confidence: 0.96,
        impact: 'POSITIVE',
        note: 'Key catalyst for mega EPC tender awards and order pipeline expansion',
        vendor: 'BUDGET',
        imageUrl: 'https://images.unsplash.com/photo-1541888946425-d0fbb186c5f7?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'SBIN',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Stock',
        confidence: 0.92,
        impact: 'POSITIVE',
        note: 'Project loan syndication and bank guarantee fees expand',
        vendor: 'SBI',
        imageUrl: 'https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 30. FII_DII_FLOWS
  FII_DII_FLOWS: {
    id: 'FII_DII_FLOWS',
    title: 'Institutional Equity Flows (FII & DII)',
    type: 'Macro',
    sector: 'Market Liquidity',
    exchange: 'NSE / NSDL',
    avatar: 'FLOWS',
    color: '#38BDF8',
    description: 'Net buying/selling telemetry tracking domestic mutual fund SIPs (+₹23,000 Cr/mo) versus foreign portfolio outflows.',
    edges: [
      {
        id: 'HDFCBANK',
        label: 'SENSITIVE_TO_MACRO',
        type: 'Stock',
        confidence: 0.91,
        impact: 'POSITIVE',
        note: 'Heavy index constituent directly supported by domestic mutual fund inflows',
        vendor: 'NSDL',
        imageUrl: 'https://images.unsplash.com/photo-1556742049-0a67e557224d?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 31. CHINA_STIMULUS
  CHINA_STIMULUS: {
    id: 'CHINA_STIMULUS',
    title: 'China Infrastructure Bond Quota Stimulus',
    type: 'News',
    sector: 'Global Geopolitics & Policy',
    exchange: 'Global News Wire',
    avatar: 'NEWS',
    color: '#10B981',
    description: 'Fiscal package deployed by Beijing to support property restructuring and industrial raw material demand across Asia.',
    edges: [
      {
        id: 'TATASTEEL',
        label: 'DIRECTLY_IMPACTS',
        type: 'Stock',
        confidence: 0.91,
        impact: 'POSITIVE',
        note: 'Boosts regional Asian hot rolled coil spread margins',
        vendor: 'REUTERS',
        imageUrl: 'https://images.unsplash.com/photo-1586528116311-ad8dd3c8310d?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 32. TELECOM_TARIFF
  TELECOM_TARIFF: {
    id: 'TELECOM_TARIFF',
    title: 'Indian Telecom Industry Tariff Revision',
    type: 'News',
    sector: 'Telecom Regulatory',
    exchange: 'TRAI / Exchange Filings',
    avatar: 'TARIFF',
    color: '#10B981',
    description: 'Synchronized 15-20% tariff hikes across prepaid and postpaid wireless buckets by private telcos.',
    edges: [
      {
        id: 'RELIANCE',
        label: 'IMPACTS_SECTOR',
        type: 'Stock',
        confidence: 0.86,
        impact: 'POSITIVE',
        note: 'Lifts Jio wireless blended ARPU towards ₹215',
        vendor: 'TRAI',
        imageUrl: 'https://images.unsplash.com/photo-1544717305-2782549b5136?auto=format&fit=crop&w=400&q=80'
      },
      {
        id: 'BHARTIARTL',
        label: 'IMPACTS_SECTOR',
        type: 'Stock',
        confidence: 0.95,
        impact: 'POSITIVE',
        note: 'Translates to significant ROCE expansion',
        vendor: 'TRAI',
        imageUrl: 'https://images.unsplash.com/photo-1544717305-2782549b5136?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  },

  // 33. LDR_COMPLIANCE
  LDR_COMPLIANCE: {
    id: 'LDR_COMPLIANCE',
    title: 'HDFC Bank Credit-to-Deposit Glidepath',
    type: 'News',
    sector: 'Banking Regulation',
    exchange: 'BSE Reg-30',
    avatar: 'LDR',
    color: '#10B981',
    description: 'Prudential normalization of loan-to-deposit ratio toward RBI target zone through accelerated branch deposits.',
    edges: [
      {
        id: 'HDFCBANK',
        label: 'DIRECTLY_IMPACTS',
        type: 'Stock',
        confidence: 0.89,
        impact: 'POSITIVE',
        note: 'De-escalates liquidity risks and margin overhang',
        vendor: 'BSE_REG30',
        imageUrl: 'https://images.unsplash.com/photo-1526304640581-d334cdbbf45e?auto=format&fit=crop&w=400&q=80'
      }
    ],
    detailedCards: []
  }
};
