"""Registry of specialist agents. business_analyst runs from Phase 2 (Client Intelligence); the rest are planned."""
AGENTS = [
    {"key": "business_analyst", "name": "Business Analyst", "phase": 2,
     "description": "Builds the client intelligence profile from client records, documents and website, with evidence."},
    {"key": "website_auditor", "name": "Website Auditor", "phase": 3,
     "description": "Crawls client websites and runs technical SEO and performance audits."},
    {"key": "market_researcher", "name": "Market Researcher", "phase": 4,
     "description": "Researches industries, geographies and demand signals."},
    {"key": "competitor_analyst", "name": "Competitor Intelligence Agent", "phase": 3,
     "description": "Identifies and monitors relevant competitors."},
    {"key": "buyer_finder", "name": "Buyer Discovery Agent", "phase": 4,
     "description": "Discovers potential buyers by product application and geography."},
    {"key": "lead_scorer", "name": "Lead Scoring Agent", "phase": 4,
     "description": "Scores prospects out of 100 with a separate evidence-confidence score."},
    {"key": "marketing_strategist", "name": "Marketing Strategist", "phase": 5,
     "description": "Prepares strategies, budgets and campaign plans for human approval."},
    {"key": "sales_assistant", "name": "Sales Assistant", "phase": 6,
     "description": "Drafts outreach, classifies enquiries and summarises meetings."},
]
