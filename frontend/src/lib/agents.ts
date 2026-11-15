// Mirrors backend/app/services/agents.py. Every agent is "planned" until its execution API exists.
export const AGENTS = [
  { key: "business_analyst", name: "Business Analyst", phase: 2, description: "Builds a verified business profile from client data and documents." },
  { key: "website_auditor", name: "Website Auditor", phase: 3, description: "Crawls client websites and runs technical SEO and performance audits." },
  { key: "market_researcher", name: "Market Researcher", phase: 4, description: "Researches industries, geographies and demand signals." },
  { key: "competitor_analyst", name: "Competitor Intelligence Agent", phase: 3, description: "Identifies and monitors relevant competitors." },
  { key: "buyer_finder", name: "Buyer Discovery Agent", phase: 4, description: "Discovers potential buyers by product application and geography." },
  { key: "lead_scorer", name: "Lead Scoring Agent", phase: 4, description: "Scores prospects out of 100 with a separate evidence-confidence score." },
  { key: "marketing_strategist", name: "Marketing Strategist", phase: 5, description: "Prepares strategies, budgets and campaign plans for human approval." },
  { key: "sales_assistant", name: "Sales Assistant", phase: 6, description: "Drafts outreach, classifies enquiries and summarises meetings." },
] as const;
