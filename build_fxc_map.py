#!/usr/bin/env python3
"""
Build the FactoryXChange 2.0 service map data (entities.json) for the FXC viewer.

Model (agreed with Thom):
  - 6 CATEGORY hubs: Technology, AI, Data, Business, Skills, Ecosystem
  - each SERVICE has ONE primary category (solid edge) and an optional
    SOFT second category (dashed edge)
  - each SERVICE is coloured by its PILLAR (5 EDIH pillars)
  - each SERVICE links to its delivering PARTNER (light edge)
  - 3 consortium partners sell nothing bookable: ICHEC co-delivers the Blueprint;
    Monaru + Piquant hold ecosystem/comms roles (light "role" edges to Ecosystem)

Source of truth: the curated tables below, compiled 2026-07-07 from live FXC
product pages. Category/soft/pillar are editorial assignments made here — tweak
the tables below and re-run to reshape the map.

Run:  python build_fxc_map.py
Then: python chat_server.py   (open /index.html)
"""

import html
import json
import re
from pathlib import Path

OUT = Path(__file__).parent / "_data" / "entities.json"
INDEX = Path(__file__).parent / "FXC_Service_Index.md"
RICH = json.loads((Path(__file__).parent / "rich_descriptions.json").read_text(encoding="utf-8"))

# ---------------------------------------------------------------- taxonomies
CATEGORIES = [
    ("technology", "Technology"),
    ("ai", "AI"),
    ("data", "Data"),
    ("business", "Business"),
    ("skills", "Skills"),
    ("ecosystem", "Ecosystem"),
]

# pillar id -> (label, colour)   (service node colour = its pillar)
PILLARS = [
    ("test-before-invest", "Test Before Invest", "#3498db"),
    ("skills-training", "Skills & Training", "#2ecc71"),
    ("support-investment", "Support to Find Investment", "#f39c12"),
    ("partnerships-networking", "Partnerships & Networking", "#9b59b6"),
    ("data-ai", "Data & AI Value Chain", "#e74c3c"),
]

# ---------------------------------------------------------------- partners
# id -> (short label, full name, portfolio, contact, route-here-when summary)
PARTNERS = [
    ("imr", "IMR", "Irish Manufacturing Research", "Business / Ecosystem / Technology",
     "Barry Fitzpatrick · barry.fitzpatrick@imr.ie",
     "Prototype/trial tech before investing; metal AM & rapid prototyping; STEM workshops. Consortium coordinator."),
    ("cspark", "Creative Spark", "Creative Spark Ltd", "Ecosystem / Skills",
     "Thom Conaty · thom@creativespark.ie",
     "Physically prototype an idea (laser/3D-print/CNC) with mentorship; design-thinking & innovation literacy; FabLab network."),
    ("fcast", "Futurecast", "Manorhamilton Innovation & Development Co.", "Ecosystem / Technology",
     "Miriam Kivlehan · miriam@futurecast.info",
     "Drone + AI/LiDAR surveying; machine design / robotics R&D; NW regional innovation & funding support."),
    ("tisa", "TisaLabs", "TisaLabs Limited", "Technology",
     "Mo Hassine · mo.hassine@tisalabs.com",
     "IT/OT/IoT cybersecurity & NIS2 gap assessment; manufacturing AI/data analytics, pipelines & retrofit."),
    ("kpmg", "KPMG Future Analytics", "KPMG Services Unlimited Company", "Business / Data",
     "William Hynes · william.hynes@kpmg.ie",
     "Data-analytics & visualisation literacy ladder; SME business strategy & planning."),
    ("gemmo", "Gemmo AI", "Gemmo Limited", "Technology / Data",
     "Luca Marchesotti · luca.marchesotti@gemmo.ai",
     "Applied AI build & deploy; computer vision; optimise underperforming AI."),
    ("mavarick", "Mavarick AI", "Mavarick", "Technology / Data",
     "Koen Jasper · koen@mavarick.ai",
     "AI strategy to build: opportunity ID, data readiness, model dev & integration for manufacturing."),
    ("tus", "TUS", "Technological University of the Shannon", "Skills / Technology",
     "John Cosgrove · john.cosgrove@tus.ie",
     "Skills & digital/AI maturity; funding strategy; IDEAM industrial research (robotics, precision mfg)."),
    ("impetus", "Impetus", "Impetus, BTAS Advisory Services Ltd", "Business",
     "Gerry Murray · gerry@weareimpetus.com",
     "Leadership-led growth & operational transformation; sustainability into strategy."),
    ("saluto", "Saluto Partners", "Saluto Creations and Consulting Ltd", "Business",
     "Duncan Kerin · duncan@salutopartners.com",
     "Lean operational-excellence & process diagnostics; digital transformation roadmap."),
    ("micro", "MicroInspect", "Ascension Digital Services Ltd", "Technology",
     "John Traynor · john@microinspect.ie",
     "Machine vision / computer-vision AI for inspection; AI & LiDAR primers."),
    ("frontend", "Frontend", "Frontend Usability Engineering Ltd", "Business / Technology",
     "Frank Long · frank.long@frontend.com",
     "Human-centred design / UX; frame the right problem; validation testing."),
    ("inventya", "Inventya", "Inventya Ventures (EU) Ltd", "Business",
     "Carmel Meredew · c.meredew@inventya.com",
     "Access-to-finance & business-plan support; investment readiness."),
    ("cyberlynk", "Cyberlynk", "Cyberlynk", "Technology",
     "Sam Sorensen · sam.sorensen@cyberlynk.ie",
     "De-risk automation commissioning with pre-deployment OT/ICS network testing."),
    ("ichec", "ICHEC", "Irish Centre for High-End Computing", "Data / Technology",
     "Peter Woods · peter.woods@ichec.ie",
     "National HPC & AI infrastructure. Co-delivers the AI & Data Blueprint; no solo bookable service."),
    ("monaru", "Monaru", "Monaru Design Ltd", "Ecosystem",
     "Michael McLaughlin · michael@monaru.ie",
     "Consortium role: physical hub environments & exhibitions. Not client-bookable."),
    ("piquant", "Piquant", "Piquant Media Ltd", "Ecosystem / Comms",
     "Roisin Buckley · roisin@piquant.ie",
     "Consortium role: communications & branding lead. Not client-bookable."),
]

# Company websites — derived from each partner's email domain (spot-check before publishing).
WEBSITES = {
    "imr": "https://www.imr.ie",
    "cspark": "https://www.creativespark.ie",
    "fcast": "https://www.futurecast.info",
    "tisa": "https://www.tisalabs.com",
    "kpmg": "https://kpmg.com/ie/en/home.html",
    "gemmo": "https://www.gemmo.ai",
    "mavarick": "https://www.mavarick.ai",
    "tus": "https://www.tus.ie",
    "impetus": "https://www.weareimpetus.com",
    "saluto": "https://www.salutopartners.com",
    "micro": "https://www.microinspect.ie",
    "frontend": "https://www.frontend.com",
    "inventya": "https://www.inventya.com",
    "cyberlynk": "https://www.cyberlynk.ie",
    "ichec": "https://www.ichec.ie",
    "monaru": "https://www.monaru.ie",
    "piquant": "https://www.piquant.ie",
}

# ---------------------------------------------------------------- services
# (label, partner, primary_category, soft_category|None, pillar, short description)
P = "test-before-invest"; S = "skills-training"; I = "support-investment"
N = "partnerships-networking"; D = "data-ai"

SERVICES = [
    # IMR (13)
    ("Automation Partnership Tender Evaluation", "imr", "business", "technology", P, "Pick the right partners for an automation project — as critical as the tech itself."),
    ("Automation Project Maturation", "imr", "technology", "business", P, "From idea to impact: de-risk and accelerate your automation journey."),
    ("Automation Road Mapping", "imr", "technology", "business", P, "Expert-led roadmap to confidently chart your automation journey."),
    ("Automation Talent To-Go Service", "imr", "technology", "skills", P, "Expert automation talent on demand to accelerate project success."),
    ("Ideas Made Real: Future Makers Tour", "imr", "skills", "ecosystem", S, "Inspiring the next generation of makers and problem-solvers."),
    ("Ideas Made Real: STEM Workshop", "imr", "skills", "technology", S, "Hands-on STEM workshop exploring advanced manufacturing via design thinking."),
    ("Ideas Made Real: TY Programme", "imr", "skills", "ecosystem", S, "Transition-Year programme exploring advanced manufacturing through real-world STEM."),
    ("Ideas Made Real: TY Work Experience", "imr", "skills", "ecosystem", S, "5-day immersive TY programme exploring STEM, manufacturing and future careers."),
    ("Industrial Digitalisation Feasibility", "imr", "technology", "business", P, "Expert feasibility assessment to de-risk major digital innovation projects."),
    ("Industrial Rapid Digital Prototyping", "imr", "technology", "business", P, "Fast-track your digital prototype from concept to clicks."),
    ("Machine Tool Optimisation", "imr", "technology", "data", P, "Maximise CNC performance with IMR's tap-testing expertise."),
    ("Metal Additive Manufacturing Prototype", "imr", "technology", "business", P, "Advance product development with ULAS additive manufacturing."),
    ("Product Innovation with Additive Manufacturing", "imr", "technology", "business", P, "Unlock additive manufacturing to stay ahead in product development."),
    # Creative Spark (8)
    ("3D CAD for Prototyping & Digital Fabrication", "cspark", "skills", "technology", S, "Master the fundamentals of 3D CAD design for digital fabrication."),
    ("Design Thinking in Practice", "cspark", "skills", "business", S, "Where creative thinking meets digital transformation."),
    ("Digital Fabrication Feasibility Pathway", "cspark", "technology", "skills", P, "Feasibility pilot of digital-fabrication applications for process & product innovation."),
    ("Discovery & Challenge Framing", "cspark", "business", "skills", P, "Uncover the right problems before investing in solutions."),
    ("Fundamentals of Innovation Literacy", "cspark", "skills", "business", S, "Building innovation confidence for Industry 5.0 success."),
    ("Ideation & Concept Development", "cspark", "skills", "business", S, "Transform your challenges into high-value concepts."),
    ("Introduction to the FabLab Innovation Network", "cspark", "ecosystem", "skills", N, "Explore the global FabLab network and local digital-fabrication opportunities."),
    ("Prototype to Impact Pathway", "cspark", "technology", "business", P, "Bridge the gap from working prototype to real-world impact with FabLab support."),
    # Futurecast (7)
    ("Digital Construction Skills", "fcast", "skills", "technology", S, "Upskilling in BIM, Lean manufacturing and process optimisation."),
    ("Drone & AI Geological Surveys", "fcast", "technology", "ai", D, "AI-powered drone surveys for construction and quarrying site geology."),
    ("Energy Optimisation & Carbon Tracking Audit", "fcast", "technology", "data", P, "Real-time virtual models for predictive maintenance and operational optimisation."),
    ("Funding Strategy & Grant Support", "fcast", "business", None, I, "Bespoke funding roadmap and proposal support for innovation, R&D and sustainability."),
    ("Immersive Learning for Secondary Schools", "fcast", "skills", "technology", S, "Immersive VR/AR introducing students to modern construction careers."),
    ("Innovation in Machine Design", "fcast", "technology", "business", P, "Advanced machine design combining automation, robotics and R&D."),
    ("Tax Relief & R&D Credit Support", "fcast", "business", None, I, "Claim optimisation for innovation tax relief including R&D credits."),
    # TisaLabs (6)
    ("AI & Data Innovation Blueprint for Manufacturing", "tisa", "ai", "data", D, "Prepare manufacturing data, systems and teams for practical AI (co-delivered with ICHEC, IMR, Inventya)."),
    ("AI-Driven Data Analytics for Manufacturing", "tisa", "data", "ai", D, "Turn continuous manufacturing data streams into actionable decisions."),
    ("Cybersecurity Gap Assessment", "tisa", "technology", "business", P, "Strengthen your security posture for NIS2 / CIS compliance across IT + OT."),
    ("Data Pipeline for Manufacturing", "tisa", "data", "technology", D, "Optimise manufacturing data flow from sensors, PLCs and ERP for analysis."),
    ("Penetration Testing incl. AI Validation", "tisa", "technology", "ai", P, "Proactively secure your IT/OT infrastructure."),
    ("Smart Retrofit & Facility Performance Planning", "tisa", "technology", "data", P, "Plan smarter, connected retrofit investments with data-driven confidence."),
    # KPMG Future Analytics (6)
    ("Business Strategy Development for SMEs", "kpmg", "business", None, P, "Elevate your SME business strategy for a competitive, fast-evolving landscape."),
    ("Introduction to Data Analytics", "kpmg", "data", "skills", S, "Data-analytics basics for business transformation."),
    ("Introduction to Data Visualisation", "kpmg", "data", "skills", S, "The power of graphic design and visual communication for business success."),
    ("Maximising the Benefit of Data Analytics", "kpmg", "data", "skills", D, "Advance business transformation through applied data analytics."),
    ("Maximising Benefit of Data Visualisation", "kpmg", "data", "skills", D, "Transform complex datasets into clear, actionable visuals."),
    ("Real Estate — Planning & Development", "kpmg", "business", None, P, "Two days of expert planning & development strategy support."),
    # Gemmo AI (5)
    ("AI Clinic", "gemmo", "ai", "data", P, "Rapid expert-led diagnostic to assess AI feasibility."),
    ("AI Deep Dive", "gemmo", "ai", "data", P, "Technical validation of your data, compliance and readiness."),
    ("AI Implementation", "gemmo", "ai", "technology", D, "End-to-end deployment of tailored, production-grade AI."),
    ("AI Optimisation", "gemmo", "ai", "data", D, "Enhance AI performance through monitoring, retraining and ROI tracking."),
    ("AI Pathfinder", "gemmo", "ai", "business", P, "Structured assessment and prioritisation of high-impact AI use cases."),
    # Mavarick AI (5)
    ("AI Model & Solution Development", "mavarick", "ai", "technology", D, "Designing and building custom AI models for critical business challenges."),
    ("AI Opportunity Identification & Assessment", "mavarick", "ai", "business", P, "Identify high-impact AI use cases aligned with business goals."),
    ("AI Solution Integration & Deployment", "mavarick", "ai", "technology", D, "Seamlessly integrate AI into existing IT and operational environments."),
    ("AI Strategy Development", "mavarick", "ai", "business", P, "A clear, phased AI strategy tailored to objectives and compliance."),
    ("Data Readiness & Engineering", "mavarick", "data", "ai", D, "Prepare, clean and integrate data as a solid foundation for AI."),
    # TUS (5)
    ("Data Visualisation with Power BI", "tus", "data", "skills", S, "Turn information into actionable business intelligence with IDEAM at TUS."),
    ("Digital & AI Maturity Assessment for Industry", "tus", "technology", "ai", P, "Benchmark where you are and accelerate your digital journey."),
    ("Digital & AI Strategy Compass & Roadmap", "tus", "business", "ai", P, "Plan the optimised journey for your digital transformation."),
    ("Funding & Grant Strategy, Strategic Submission", "tus", "business", None, I, "Begin the journey to secure available funding for your enterprise."),
    ("Industrial Research — Scoping Project", "tus", "technology", "business", P, "Scope, validate and transform ideas into innovation."),
    # Impetus (4)
    ("360 Strategic Business Assessment", "impetus", "business", None, P, "A thorough financial and operational health check to guide transformation."),
    ("Grow Accelerator: Blueprint for Growth", "impetus", "business", "skills", P, "Leaders' discovery workshop to zone in on the key levers of success."),
    ("Integrating Sustainability into your Strategy", "impetus", "business", None, P, "How to incorporate sustainability into your business."),
    ("Manufacturing Performance", "impetus", "business", "technology", P, "From operational-strategy complexity to predictable, profitable performance."),
    # Saluto Partners (4)
    ("AI Discovery", "saluto", "ai", "business", P, "Identify where AI can create real value and define a practical path to action."),
    ("Digital Transformation Assessment & Roadmap", "saluto", "business", "technology", P, "Assess digital capability and define a clear transformation roadmap."),
    ("Operational Excellence Diagnostic & Roadmap", "saluto", "business", None, P, "Identify operational waste and define a roadmap to improve flow and performance."),
    ("Process Optimisation & Workflow Redesign", "saluto", "business", "technology", P, "Streamline processes and enable efficient workflows across the organisation."),
    # MicroInspect (3)
    ("An Introduction to AI", "micro", "skills", "ai", S, "Your first confident step into AI, guided by experts."),
    ("Computer Vision + AI Workshop", "micro", "skills", "ai", S, "Learn to leverage the power of computer vision and AI."),
    ("LiDAR Introduction — Where to Start", "micro", "technology", "skills", P, "Test before you invest: an introduction to 3D LiDAR scanning."),
    # Frontend (3)
    ("Digital Taskflow Optimisation", "frontend", "business", "technology", P, "Optimise workflows, reduce friction, maximise technology impact."),
    ("Innovation Pathfinder Workshop", "frontend", "business", "skills", P, "Identify the right problems and build a prioritised innovation roadmap."),
    ("Validation Testing", "frontend", "technology", "business", P, "Validate early, reduce risk, build with confidence."),
    # Inventya (2)
    ("Access to Finance Support", "inventya", "business", None, I, "Build the right blended-finance roadmap for growth and transformation."),
    ("Business Plan Support", "inventya", "business", None, I, "Develop a concise business plan aligned with funding and growth goals."),
    # Cyberlynk (2)
    ("De-risk & Accelerate your Automation Project (1-Month)", "cyberlynk", "technology", "business", P, "Resolve system-integration issues before equipment delivery — 1-month deployment."),
    ("De-risk & Accelerate your Automation Project (3-Month)", "cyberlynk", "technology", "business", P, "Resolve system-integration issues before equipment delivery — 3-month deployment."),
]

# Live FXC product-page slug per service (read from store-products-sitemap.xml, 2026-07-08).
# Kept as a label->slug map because ~20 site slugs differ from their service titles.
PRODUCT_BASE = "https://www.factoryxchange.ie/product-page/"
SERVICE_URLS = {
    "Automation Partnership Tender Evaluation": "automation-partnership-tender-evaluation",
    "Automation Project Maturation": "automation-project-maturation",
    "Automation Road Mapping": "automation-road-mapping",
    "Automation Talent To-Go Service": "automation-talent-to-go-service",
    "Ideas Made Real: Future Makers Tour": "ideas-made-real-future-makers-tour",
    "Ideas Made Real: STEM Workshop": "ideas-made-real-stem-workshop-1",
    "Ideas Made Real: TY Programme": "ideas-made-real-transition-year-ty-programme",
    "Ideas Made Real: TY Work Experience": "ideas-made-real-transition-year-work-experience",
    "Industrial Digitalisation Feasibility": "industrial-digitalisation-feasibility",
    "Industrial Rapid Digital Prototyping": "industrial-rapid-digital-prototyping",
    "Machine Tool Optimisation": "machine-tool-optimisation",
    "Metal Additive Manufacturing Prototype": "metal-additive-manufacturing-prototype",
    "Product Innovation with Additive Manufacturing": "product-innovation-with-am-1",
    "3D CAD for Prototyping & Digital Fabrication": "3d-cad-for-prototyping-and-digital-fabrication",
    "Design Thinking in Practice": "design-thinking-in-practice",
    "Digital Fabrication Feasibility Pathway": "digital-fabrication-feasibility-pathway",
    "Discovery & Challenge Framing": "discovery-and-challenge-framing",
    "Fundamentals of Innovation Literacy": "fundamentals-of-innovation-literacy",
    "Ideation & Concept Development": "ideation-and-concept-development",
    "Introduction to the FabLab Innovation Network": "introduction-to-the-fablab-innovation-network",
    "Prototype to Impact Pathway": "prototype-to-impact-pathway",
    "Digital Construction Skills": "digital-construction-skills",
    "Drone & AI Geological Surveys": "drone-and-ai-geological-surveys",
    "Energy Optimisation & Carbon Tracking Audit": "energy-optimisation-for-manufacturing",
    "Funding Strategy & Grant Support": "funding-strategy-and-grant-support",
    "Immersive Learning for Secondary Schools": "immersive-learning-for-secondary-schools",
    "Innovation in Machine Design": "innovation-in-machine-design",
    "Tax Relief & R&D Credit Support": "tax-relief-rd-credit-support",
    "AI & Data Innovation Blueprint for Manufacturing": "ai-data-innovation-blueprint-for-manufacturing",
    "AI-Driven Data Analytics for Manufacturing": "ai-driven-data-analytics-for-manufacturing",
    "Cybersecurity Gap Assessment": "cybersecurity-gap-assessment",
    "Data Pipeline for Manufacturing": "data-pipeline-for-manufacturing",
    "Penetration Testing incl. AI Validation": "penetration-testing-including-ai-validation",
    "Smart Retrofit & Facility Performance Planning": "smart-retrofit-facility-performance-planning",
    "Business Strategy Development for SMEs": "business-strategies-for-smes",
    "Introduction to Data Analytics": "introduction-to-data-analytics",
    "Introduction to Data Visualisation": "introduction-to-data-visualisation",
    "Maximising the Benefit of Data Analytics": "maximising-benefit-of-data-analytics",
    "Maximising Benefit of Data Visualisation": "maximising-benefit-of-data-visualisation",
    "Real Estate — Planning & Development": "real-estate-planning-and-development",
    "AI Clinic": "ai-clinic",
    "AI Deep Dive": "ai-deep-dive",
    "AI Implementation": "ai-implementation",
    "AI Optimisation": "ai-optimisation",
    "AI Pathfinder": "ai-pathfinder",
    "AI Model & Solution Development": "ai-model-and-solution-development",
    "AI Opportunity Identification & Assessment": "ai-opportunity-identification-and-assessment",
    "AI Solution Integration & Deployment": "ai-solution-integration-and-deployment",
    "AI Strategy Development": "ai-strategy-development",
    "Data Readiness & Engineering": "data-readiness-and-engineering",
    "Data Visualisation with Power BI": "data-visualisation-with-powerbi",
    "Digital & AI Maturity Assessment for Industry": "digital-maturity-assessment-for-industry",
    "Digital & AI Strategy Compass & Roadmap": "digital-roadmap-and-strategy",
    "Funding & Grant Strategy, Strategic Submission": "funding-grant-strategy-strategic-submission",
    "Industrial Research — Scoping Project": "industrial-research-scoping-project",
    "360 Strategic Business Assessment": "360-strategic-business-assessment",
    "Grow Accelerator: Blueprint for Growth": "grow-accelerator-blueprint-for-growth",
    "Integrating Sustainability into your Strategy": "integrating-sustainability-into-your-strategy",
    "Manufacturing Performance": "manufacturing-performance",
    "AI Discovery": "ai-discovery",
    "Digital Transformation Assessment & Roadmap": "digital-transformation-assessment-roadmap",
    "Operational Excellence Diagnostic & Roadmap": "operational-excellence-diagnostic-roadmap",
    "Process Optimisation & Workflow Redesign": "process-optimisation-workflow-redesign",
    "An Introduction to AI": "an-introduction-to-ai",
    "Computer Vision + AI Workshop": "computer-vision-ai-workshop",
    "LiDAR Introduction — Where to Start": "lidar-introduction-where-to-start",
    "Digital Taskflow Optimisation": "digital-taskflow-optimisation",
    "Innovation Pathfinder Workshop": "innovation-pathfinder-workshop",
    "Validation Testing": "validation-testing",
    "Access to Finance Support": "access-to-finance-support",
    "Business Plan Support": "business-plan-support",
    "De-risk & Accelerate your Automation Project (1-Month)": "de-risk-accelerate-your-automation-project",
    "De-risk & Accelerate your Automation Project (3-Month)": "de-risk-accelerate-your-automation-project-3-month",
}

# consortium-role / co-delivery edges (partner -> target node), rendered faint
ROLE_EDGES = [
    ("ichec", "svc", "AI & Data Innovation Blueprint for Manufacturing", "co-delivers"),
    ("monaru", "cat", "ecosystem", "consortium role"),
    ("piquant", "cat", "ecosystem", "consortium role"),
]


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def build():
    cat_ids = {c[0] for c in CATEGORIES}
    pillar_ids = {p[0] for p in PILLARS}
    partner_ids = {p[0] for p in PARTNERS}

    services = []
    svc_id_by_label = {}
    for label, partner, cat, soft, pillar, desc in SERVICES:
        assert partner in partner_ids, f"unknown partner {partner}"
        assert cat in cat_ids, f"unknown category {cat} on {label}"
        assert soft is None or soft in cat_ids, f"unknown soft category {soft} on {label}"
        assert soft != cat, f"soft category equals primary on {label}"
        assert pillar in pillar_ids, f"unknown pillar {pillar} on {label}"
        assert label in SERVICE_URLS, f"no FXC product URL mapped for {label}"
        assert label in RICH, f"no rich detail for {label}"
        sid = f"svc-{partner}-{slug(label)}"
        svc_id_by_label[label] = sid
        services.append({
            "id": sid, "label": label, "partner": partner,
            "category": cat, "soft": soft, "pillar": pillar, "desc": desc,
            "url": PRODUCT_BASE + SERVICE_URLS[label],
            "full": html.unescape(RICH[label]["description"]),
            "duration": RICH[label]["duration"],
            "service_lead": RICH[label]["service_lead"],
            "price": RICH[label]["price"],
            "availability": RICH[label]["availability"],
        })

    roles = []
    for partner, kind, target, rel in ROLE_EDGES:
        tid = svc_id_by_label[target] if kind == "svc" else f"cat-{target}"
        roles.append({"partner": partner, "target": tid, "rel": rel})

    data = {
        "meta": {
            "title": "FactoryXChange 2.0 — Service Map",
            "subtitle": "Digital Strategist Pathfinding Tool",
            "generated_from": "FXC marketplace (curated 2026-07-07)",
        },
        "categories": [{"id": f"cat-{cid}", "key": cid, "label": lbl} for cid, lbl in CATEGORIES],
        "pillars": [{"id": pid, "label": lbl, "color": col} for pid, lbl, col in PILLARS],
        "partners": [{
            "id": f"par-{pid}", "key": pid, "label": lbl, "full": full,
            "portfolio": port, "contact": contact, "route": route,
            "website": WEBSITES.get(pid, ""),
            "sells": any(s["partner"] == pid for s in services),
        } for pid, lbl, full, port, contact, route in PARTNERS],
        "services": [{
            "id": s["id"], "label": s["label"],
            "partner": f"par-{s['partner']}",
            "category": f"cat-{s['category']}",
            "soft": f"cat-{s['soft']}" if s["soft"] else None,
            "pillar": s["pillar"], "desc": s["desc"], "url": s["url"],
            "full": s["full"], "duration": s["duration"], "service_lead": s["service_lead"],
            "price": s["price"], "availability": s["availability"],
        } for s in services],
        "roles": [{"partner": f"par-{r['partner']}", "target": r["target"], "rel": r["rel"]} for r in roles],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # --- also emit the partner-grouped service index (markdown) ---
    cat_label = {cid: lbl for cid, lbl in CATEGORIES}
    pil_label = {p[0]: p[1] for p in PILLARS}
    delivering = sum(1 for p in PARTNERS if any(s["partner"] == p[0] for s in services))
    lines = [
        "# FactoryXChange 2.0 — Service Index",
        "",
        f"All {len(services)} live services across {delivering} delivering partners, grouped by "
        "partner. Each service links to its live FXC product page.",
        "",
        "*Generated by `build_fxc_map.py` from the FXC store sitemap (2026-07-08). "
        "Re-run the script to refresh.*",
        "",
        "---",
        "",
    ]
    non_sellers = []
    for pid, lbl, full, port, contact, route in PARTNERS:
        ps = [s for s in services if s["partner"] == pid]
        if not ps:
            non_sellers.append((lbl, full, route))
            continue
        web = WEBSITES.get(pid, "")
        lines.append(f"## {lbl} — {full}")
        lines.append(f"[{web}]({web}) · {contact} · {len(ps)} services")
        lines.append("")
        lines.append("| Service | Category | Pillar | FXC page |")
        lines.append("|---|---|---|---|")
        for s in ps:
            lines.append(f"| {s['label']} | {cat_label[s['category']]} | {pil_label[s['pillar']]} | [open]({s['url']}) |")
        lines.append("")
    if non_sellers:
        lines.append("---")
        lines.append("")
        lines.append("## Consortium partners with no bookable service")
        lines.append("")
        for lbl, full, route in non_sellers:
            lines.append(f"- **{lbl}** — {full} {route}")
        lines.append("")
    INDEX.write_text("\n".join(lines), encoding="utf-8")

    # quick self-check
    n_soft = sum(1 for s in services if s["soft"])
    print(f"[OK] wrote {OUT}")
    print(f"     {len(data['categories'])} categories · {len(data['pillars'])} pillars · "
          f"{len(data['partners'])} partners · {len(services)} services")
    print(f"     {n_soft} services carry a soft second category · {len(roles)} consortium-role edges")
    sellers = sum(1 for p in data["partners"] if p["sells"])
    print(f"     {sellers} partners sell services · {len(data['partners']) - sellers} consortium-role only")


if __name__ == "__main__":
    build()
