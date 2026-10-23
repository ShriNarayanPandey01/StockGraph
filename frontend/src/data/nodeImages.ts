// Safe, high-contrast, beautifully styled SVG data URIs for all canonical nodes
// Using encodeURIComponent guarantees zero decode failures, no 'broken' HTMLImageElement state, and zero 404s.

function createSvgDataUri(svgContent: string): string {
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svgContent.trim());
}

export const NODE_IMAGES: Record<string, string> = {
  // --- METALS & COMMODITIES ---
  COKING_COAL: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#18181b"/>
      <path d="M25 65 L40 30 L65 35 L80 60 L60 80 L35 75 Z" fill="#27272a" stroke="#f97316" stroke-width="2.5"/>
      <path d="M40 30 L55 50 L35 75 Z" fill="#3f3f46"/>
      <path d="M55 50 L65 35 L80 60 Z" fill="#18181b"/>
      <circle cx="70" cy="30" r="3.5" fill="#fb923c"/>
      <circle cx="82" cy="42" r="2.5" fill="#ea580c"/>
      <text x="50" y="93" font-family="sans-serif" font-size="11" font-weight="bold" fill="#fdba74" text-anchor="middle">COAL</text>
    </svg>
  `),

  HRC_STEEL: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#0f172a"/>
      <circle cx="50" cy="46" r="28" fill="none" stroke="#38bdf8" stroke-width="5"/>
      <circle cx="50" cy="46" r="16" fill="none" stroke="#f97316" stroke-width="4" stroke-dasharray="6 3"/>
      <circle cx="50" cy="46" r="6" fill="#ef4444"/>
      <line x1="22" y1="46" x2="78" y2="46" stroke="#38bdf8" stroke-width="2" stroke-dasharray="3 3"/>
      <text x="50" y="93" font-family="sans-serif" font-size="11" font-weight="bold" fill="#7dd3fc" text-anchor="middle">STEEL</text>
    </svg>
  `),

  BRENT_CRUDE: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#1c1917"/>
      <path d="M50 18 C50 18 28 46 28 60 C28 72 38 80 50 80 C62 80 72 72 72 60 C72 46 50 18 50 18 Z" fill="#f97316"/>
      <path d="M44 48 C44 48 36 58 36 66 C36 72 41 76 46 76 C42 73 40 68 42 62 C43 56 48 51 44 48 Z" fill="#ffedd5"/>
      <text x="50" y="93" font-family="sans-serif" font-size="11" font-weight="bold" fill="#fdba74" text-anchor="middle">CRUDE</text>
    </svg>
  `),

  ALUMINIUM: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#0f172a"/>
      <polygon points="50,18 82,38 82,72 50,88 18,72 18,38" fill="#1e293b" stroke="#94a3b8" stroke-width="3"/>
      <polygon points="50,28 72,42 72,66 50,78 28,66 28,42" fill="#334155" stroke="#cbd5e1" stroke-width="2"/>
      <text x="50" y="58" font-family="monospace" font-size="16" font-weight="bold" fill="#f1f5f9" text-anchor="middle">AL</text>
      <text x="50" y="94" font-family="sans-serif" font-size="10" font-weight="bold" fill="#94a3b8" text-anchor="middle">ALUMINIUM</text>
    </svg>
  `),

  GOLD_MCX: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#1c1917"/>
      <polygon points="26,62 38,32 74,32 62,62" fill="#eab308" stroke="#fef08a" stroke-width="2"/>
      <polygon points="74,32 86,52 62,62" fill="#ca8a04"/>
      <polygon points="26,62 38,72 74,72 62,62" fill="#a16207"/>
      <text x="50" y="52" font-family="monospace" font-size="14" font-weight="bold" fill="#ffffff" text-anchor="middle">AU</text>
      <text x="50" y="93" font-family="sans-serif" font-size="11" font-weight="bold" fill="#fef08a" text-anchor="middle">GOLD MCX</text>
    </svg>
  `),

  NATURAL_GAS: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#082f49"/>
      <path d="M50 18 C55 35 72 45 72 64 C72 76 62 84 50 84 C38 84 28 76 28 64 C28 45 45 35 50 18 Z" fill="#0284c7"/>
      <path d="M50 38 C53 48 62 55 62 66 C62 73 57 78 50 78 C43 78 38 73 38 66 C38 55 47 48 50 38 Z" fill="#38bdf8"/>
      <circle cx="50" cy="68" r="6" fill="#e0f2fe"/>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#7dd3fc" text-anchor="middle">NAT GAS</text>
    </svg>
  `),

  COPPER: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#2a1205"/>
      <circle cx="50" cy="46" r="26" fill="#7c2d12" stroke="#ea580c" stroke-width="3"/>
      <text x="50" y="53" font-family="monospace" font-size="18" font-weight="bold" fill="#ffedd5" text-anchor="middle">Cu</text>
      <text x="50" y="93" font-family="sans-serif" font-size="11" font-weight="bold" fill="#fdba74" text-anchor="middle">COPPER</text>
    </svg>
  `),

  // --- MACRO FACTORS ---
  RBI_REPO_RATE: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#1e112a"/>
      <path d="M20 38 L50 20 L80 38 Z" fill="#a855f7"/>
      <rect x="25" y="42" width="8" height="28" fill="#c084fc"/>
      <rect x="46" y="42" width="8" height="28" fill="#c084fc"/>
      <rect x="67" y="42" width="8" height="28" fill="#c084fc"/>
      <rect x="18" y="72" width="64" height="6" fill="#a855f7"/>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#e9d5ff" text-anchor="middle">RBI 6.5%</text>
    </svg>
  `),

  USD_INR_FX: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#172554"/>
      <circle cx="36" cy="46" r="16" fill="none" stroke="#38bdf8" stroke-width="2.5"/>
      <text x="36" y="53" font-family="sans-serif" font-size="16" font-weight="bold" fill="#38bdf8" text-anchor="middle">$</text>
      <circle cx="64" cy="46" r="16" fill="none" stroke="#38bdf8" stroke-width="2.5"/>
      <text x="64" y="53" font-family="sans-serif" font-size="16" font-weight="bold" fill="#38bdf8" text-anchor="middle">&#8377;</text>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#93c5fd" text-anchor="middle">USD/INR</text>
    </svg>
  `),

  INDIA_10Y_YIELD: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#18181b"/>
      <path d="M18 70 L36 56 L52 62 L70 36 L84 42" fill="none" stroke="#a855f7" stroke-width="3.5"/>
      <circle cx="70" cy="36" r="4.5" fill="#c084fc"/>
      <line x1="18" y1="76" x2="84" y2="76" stroke="#52525b" stroke-width="1.5"/>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#d8b4fe" text-anchor="middle">10Y 7.15%</text>
    </svg>
  `),

  INDIA_CPI: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#261014"/>
      <path d="M22 66 L42 46 L60 54 L80 26" fill="none" stroke="#f43f5e" stroke-width="3"/>
      <polygon points="76,24 82,24 82,30" fill="#f43f5e"/>
      <text x="50" y="74" font-family="sans-serif" font-size="14" font-weight="bold" fill="#fda4af" text-anchor="middle">5.4%</text>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#fb7185" text-anchor="middle">INDIA CPI</text>
    </svg>
  `),

  US_FED_RATE: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#172554"/>
      <rect x="24" y="24" width="52" height="48" rx="6" fill="#1e3a8a" stroke="#60a5fa" stroke-width="2"/>
      <text x="50" y="46" font-family="sans-serif" font-size="12" font-weight="bold" fill="#ffffff" text-anchor="middle">FED</text>
      <text x="50" y="64" font-family="monospace" font-size="13" font-weight="bold" fill="#93c5fd" text-anchor="middle">5.25%</text>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#bfdbfe" text-anchor="middle">US FED</text>
    </svg>
  `),

  GOVT_CAPEX_SPEND: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#064e3b"/>
      <path d="M22 72 L36 44 L50 56 L64 34 L78 22" fill="none" stroke="#34d399" stroke-width="3.5"/>
      <circle cx="78" cy="22" r="4" fill="#a7f3d0"/>
      <text x="50" y="68" font-family="monospace" font-size="13" font-weight="bold" fill="#a7f3d0" text-anchor="middle">&#8377;11.1L Cr</text>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#6ee7b7" text-anchor="middle">GOVT CAPEX</text>
    </svg>
  `),

  FII_DII_FLOWS: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#111827"/>
      <rect x="25" y="44" width="20" height="30" fill="#ef4444" rx="2"/>
      <rect x="55" y="24" width="20" height="50" fill="#10b981" rx="2"/>
      <text x="35" y="40" font-family="sans-serif" font-size="9" fill="#fca5a5" text-anchor="middle">FII</text>
      <text x="65" y="20" font-family="sans-serif" font-size="9" fill="#86efac" text-anchor="middle">DII</text>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#cbd5e1" text-anchor="middle">FLOWS</text>
    </svg>
  `),

  // --- STOCKS ---
  TATASTEEL: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#0c4a6e"/>
      <circle cx="50" cy="46" r="28" fill="none" stroke="#38bdf8" stroke-width="3"/>
      <text x="50" y="53" font-family="monospace" font-size="20" font-weight="bold" fill="#ffffff" text-anchor="middle">TS</text>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#7dd3fc" text-anchor="middle">TATA STEEL</text>
    </svg>
  `),

  RELIANCE: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#1e3a8a"/>
      <circle cx="50" cy="46" r="28" fill="none" stroke="#60a5fa" stroke-width="3"/>
      <text x="50" y="53" font-family="monospace" font-size="18" font-weight="bold" fill="#ffffff" text-anchor="middle">RIL</text>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#93c5fd" text-anchor="middle">RELIANCE</text>
    </svg>
  `),

  HDFCBANK: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#14532d"/>
      <circle cx="50" cy="46" r="28" fill="none" stroke="#4ade80" stroke-width="3"/>
      <text x="50" y="52" font-family="monospace" font-size="15" font-weight="bold" fill="#ffffff" text-anchor="middle">HDFC</text>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#86efac" text-anchor="middle">HDFC BANK</text>
    </svg>
  `),

  ASIANPAINTS: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#701a75"/>
      <circle cx="50" cy="46" r="28" fill="none" stroke="#f472b6" stroke-width="3"/>
      <circle cx="42" cy="42" r="6" fill="#f43f5e"/>
      <circle cx="58" cy="42" r="6" fill="#38bdf8"/>
      <circle cx="50" cy="54" r="6" fill="#facc15"/>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#fbcfe8" text-anchor="middle">PAINTS</text>
    </svg>
  `),

  INFY: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#0369a1"/>
      <circle cx="50" cy="46" r="28" fill="none" stroke="#7dd3fc" stroke-width="3"/>
      <text x="50" y="52" font-family="monospace" font-size="16" font-weight="bold" fill="#ffffff" text-anchor="middle">INFY</text>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#bae6fd" text-anchor="middle">INFOSYS</text>
    </svg>
  `),

  TCS: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#1e1b4b"/>
      <circle cx="50" cy="46" r="28" fill="none" stroke="#818cf8" stroke-width="3"/>
      <text x="50" y="52" font-family="monospace" font-size="17" font-weight="bold" fill="#ffffff" text-anchor="middle">TCS</text>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#c7d2fe" text-anchor="middle">TCS TECH</text>
    </svg>
  `),

  ICICIBANK: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#7c2d12"/>
      <circle cx="50" cy="46" r="28" fill="none" stroke="#fb923c" stroke-width="3"/>
      <text x="50" y="52" font-family="monospace" font-size="16" font-weight="bold" fill="#ffffff" text-anchor="middle">ICICI</text>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#fdba74" text-anchor="middle">ICICI BANK</text>
    </svg>
  `),

  SBIN: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#075985"/>
      <circle cx="50" cy="44" r="26" fill="#0284c7" stroke="#38bdf8" stroke-width="3"/>
      <circle cx="50" cy="44" r="8" fill="#ffffff"/>
      <rect x="47" y="44" width="6" height="18" fill="#075985"/>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#7dd3fc" text-anchor="middle">SBI BANK</text>
    </svg>
  `),

  LT: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#14532d"/>
      <circle cx="50" cy="46" r="28" fill="none" stroke="#22c55e" stroke-width="3"/>
      <text x="50" y="53" font-family="monospace" font-size="20" font-weight="bold" fill="#ffffff" text-anchor="middle">L&amp;T</text>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#86efac" text-anchor="middle">LARSEN</text>
    </svg>
  `),

  MARUTI: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#312e81"/>
      <circle cx="50" cy="46" r="28" fill="none" stroke="#a5b4fc" stroke-width="3"/>
      <text x="50" y="52" font-family="monospace" font-size="15" font-weight="bold" fill="#ffffff" text-anchor="middle">MSIL</text>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#c7d2fe" text-anchor="middle">MARUTI</text>
    </svg>
  `),

  SUNPHARMA: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#831843"/>
      <circle cx="50" cy="46" r="28" fill="none" stroke="#f472b6" stroke-width="3"/>
      <text x="50" y="52" font-family="monospace" font-size="17" font-weight="bold" fill="#ffffff" text-anchor="middle">SUN</text>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#fbcfe8" text-anchor="middle">PHARMA</text>
    </svg>
  `),

  ITC: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#713f12"/>
      <circle cx="50" cy="46" r="28" fill="none" stroke="#facc15" stroke-width="3"/>
      <text x="50" y="53" font-family="monospace" font-size="20" font-weight="bold" fill="#ffffff" text-anchor="middle">ITC</text>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#fef08a" text-anchor="middle">ITC LTD</text>
    </svg>
  `),

  BAJFINANCE: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#1e3a8a"/>
      <circle cx="50" cy="46" r="28" fill="none" stroke="#60a5fa" stroke-width="3"/>
      <text x="50" y="52" font-family="monospace" font-size="16" font-weight="bold" fill="#ffffff" text-anchor="middle">BAJ</text>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#bfdbfe" text-anchor="middle">FINANCE</text>
    </svg>
  `),

  JSWSTEEL: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#0f172a"/>
      <circle cx="50" cy="46" r="28" fill="none" stroke="#0284c7" stroke-width="3"/>
      <text x="50" y="52" font-family="monospace" font-size="17" font-weight="bold" fill="#ffffff" text-anchor="middle">JSW</text>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#7dd3fc" text-anchor="middle">JSW STEEL</text>
    </svg>
  `),

  BHARTIARTL: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#7f1d1d"/>
      <circle cx="50" cy="46" r="28" fill="none" stroke="#f87171" stroke-width="3"/>
      <text x="50" y="52" font-family="monospace" font-size="15" font-weight="bold" fill="#ffffff" text-anchor="middle">AIRTEL</text>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#fca5a5" text-anchor="middle">BHARTI</text>
    </svg>
  `),

  TITAN: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#1c1917"/>
      <circle cx="50" cy="46" r="28" fill="none" stroke="#eab308" stroke-width="3"/>
      <text x="50" y="52" font-family="monospace" font-size="15" font-weight="bold" fill="#ffffff" text-anchor="middle">TITAN</text>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#fef08a" text-anchor="middle">JEWELLERY</text>
    </svg>
  `),

  // --- NEWS & FILINGS ---
  CHINA_STIMULUS: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#042f2e"/>
      <path d="M20 72 L45 25 L55 25 L80 72 Z" fill="none" stroke="#10b981" stroke-width="3"/>
      <line x1="30" y1="55" x2="70" y2="55" stroke="#10b981" stroke-width="2"/>
      <line x1="50" y1="25" x2="85" y2="38" stroke="#34d399" stroke-width="3"/>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#6ee7b7" text-anchor="middle">STIMULUS</text>
    </svg>
  `),

  TELECOM_TARIFF: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#022c22"/>
      <line x1="50" y1="20" x2="50" y2="75" stroke="#10b981" stroke-width="4"/>
      <line x1="34" y1="38" x2="66" y2="38" stroke="#10b981" stroke-width="3"/>
      <line x1="26" y1="56" x2="74" y2="56" stroke="#10b981" stroke-width="3"/>
      <circle cx="50" cy="18" r="5" fill="#34d399"/>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#6ee7b7" text-anchor="middle">5G TARIFF</text>
    </svg>
  `),

  LDR_COMPLIANCE: createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#064e3b"/>
      <circle cx="50" cy="44" r="24" fill="none" stroke="#34d399" stroke-width="4"/>
      <path d="M38 44 L46 52 L64 34" fill="none" stroke="#34d399" stroke-width="4" stroke-linecap="round"/>
      <text x="50" y="93" font-family="sans-serif" font-size="10" font-weight="bold" fill="#a7f3d0" text-anchor="middle">LDR 89%</text>
    </svg>
  `),
};

// Safe fallback generator that is guaranteed 100% valid SVG and never fails to load
export function getNodeImage(id: string): string {
  if (NODE_IMAGES[id]) {
    return NODE_IMAGES[id];
  }
  const cleanId = id.replace(/[^a-zA-Z0-9_]/g, '');
  const shortText = cleanId.substring(0, 4);
  return createSvgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <rect width="100" height="100" fill="#18181b"/>
      <circle cx="50" cy="46" r="28" fill="none" stroke="#38bdf8" stroke-width="2.5"/>
      <text x="50" y="52" font-family="monospace" font-size="14" font-weight="bold" fill="#ffffff" text-anchor="middle">${shortText}</text>
      <text x="50" y="93" font-family="sans-serif" font-size="9" font-weight="bold" fill="#94a3b8" text-anchor="middle">${cleanId.substring(0, 8)}</text>
    </svg>
  `);
}
