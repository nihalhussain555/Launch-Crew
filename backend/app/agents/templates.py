"""Twenty website templates: the professional shapes the crew is asked for most, as real briefs.

A template is not a picture of a site. Each one fixes the decisions a run would otherwise have to guess
- the layout style, the site type, the content blocks the page is built from, the plain-English features
the brief asks for and the pages a site of that kind needs - and hands them to the same wizard, the same
`SiteSpec` and the same pipeline a hand-written brief goes through. `app/llm/mock.py` renders those blocks
as their own markup (a menu is not a testimonial in a different colour), so the page a template produces
carries the content that template promises.

Two rules hold here, because a gallery is the easiest place in this product to overstate things:

* every block named on a card is a block the builder has code for. `SECTION_INFO` in
  `app/agents/styles.py` is the only source of those names, and `test_templates.py` fails if a card
  advertises something the builder cannot render;
* every feature named on a card is a capability from `app/agents/capabilities.py`, shown with that
  capability's own honest status and setup steps. A cart, a payment link, an email inbox or an
  appointment calendar is scaffolding the owner has to connect - the card says so in the catalog's words
  rather than implying the crew delivered a shop.

Nothing here is a claim about a customer, an award or a company's history. The sample copy a template's
first run writes is placeholder content, labelled as placeholder content on the page itself.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.agents import capabilities as caps
from app.agents import styles as design_styles

CATEGORIES = ("Business & Corporate", "SaaS, AI & Technology", "E-commerce & Retail",
              "Professional Services", "Education, Content & Community", "Startup & Conversion Templates")


@dataclass(frozen=True)
class Template:
    key: str
    label: str
    category: str
    industries: tuple[str, ...]           # who this is for, shown under the name
    summary: str                          # the card's line: what the page is made of
    style: str                            # a design-style key: the layout it starts in
    business: str                         # a business-type key: what the crew writes copy for
    sections: tuple[str, ...]             # optional content blocks the page is built with
    features: tuple[str, ...]             # capability keys the brief asks for (reviewed, never auto-applied)
    asks: tuple[str, ...]                 # the same requests in the owner's words, for the brief
    pages: tuple[str, ...]
    audience: str                         # who the example brief is written for
    tone: str
    ideas: tuple[str, ...]                # the first one starts the run; the rest are the wizard's examples
    notes: tuple[str, ...] = ()           # what the owner must still supply, said out loud

    def industries_line(self) -> str:
        return " · ".join(self.industries)

    def blocks(self) -> list[dict]:
        """The content blocks this page is built from: always the three core sections, then its own."""
        core = [{"key": k, "label": design_styles.SECTION_INFO[k][0],
                 "carries": design_styles.SECTION_INFO[k][1]} for k in design_styles.REQUIRED_SECTIONS]
        extra = [{"key": k, "label": design_styles.SECTION_INFO[k][0],
                  "carries": design_styles.SECTION_INFO[k][1]} for k in self.sections]
        return core + extra

    def feature_rows(self) -> list[dict]:
        """Each requested feature with the catalog's own status next to it - never a claim of its own.

        A template asks; nothing is written into a page until the workspace builds and reviews it, so the
        wording here is 'what this needs' rather than 'what you get'.
        """
        rows = []
        for key in self.features:
            cap = caps.get(key)
            if cap is None:                       # the registry test stops this; kept honest anyway
                rows.append({"key": key, "label": key, "status": "unknown", "status_label":
                             "not in the feature catalog", "needs": [], "setup": [], "env": [],
                             "limits": ""})
                continue
            rows.append({"key": cap.key, "label": cap.label, "status": cap.status,
                         "status_label": caps.STATE_LABEL[cap.status], "needs": list(cap.needs),
                         "setup": list(cap.setup), "env": list(cap.env), "limits": cap.limits})
        return rows

    def weakest(self) -> str:
        """The most demanding status among its features, for the card's one-line honesty badge."""
        order = {caps.GENERATED: 0, caps.SCAFFOLD: 1, caps.NEEDS_SETUP: 2}
        statuses = [r["status"] for r in self.feature_rows()]
        if not statuses:
            return caps.GENERATED
        return max(statuses, key=lambda s: order.get(s, 0))


# The 12 idea-starters this gallery replaced live on as example briefs inside the templates they suit, so
# nobody loses the sentence they used to start with. Each appears verbatim in the `ideas` tuple below.
TEMPLATE_LIST = (
    Template(
        "corporate-pro", "Corporate Pro", "Business & Corporate",
        ("Business", "Consulting", "Enterprise"),
        "Clean corporate layout, company profile, services, leadership, case studies and a contact path.",
        "corporate", "corporate",
        ("about", "stats", "services", "work", "team", "contact"),
        ("contact", "booking"),
        ("company profile", "services we offer", "leadership team", "case studies", "contact form"),
        ("home", "about", "services", "work", "contact"),
        "procurement leads and new clients at mid-sized firms", "reassuring, precise, no hype",
        ("A consultancy that helps mid-sized manufacturers put their reporting on one dashboard",
         "An accounting practice that handles payroll and VAT for trades businesses"),
        ("Years founded, headcount and client figures are placeholders until you set them - the page marks "
         "invented numbers as invented.",
         "Case-study clients are placeholders too: name your own before you launch."),
    ),
    Template(
        "creative-agency", "Creative Agency", "Business & Corporate",
        ("Agencies", "Branding", "Marketing"),
        "Bold statement hero, a work portfolio, services, client projects, testimonials and an enquiry form.",
        "agency", "agency",
        ("services", "work", "testimonials", "gallery", "team", "contact"),
        ("contact",),
        ("services list", "portfolio of client work", "team page", "enquiry form"),
        ("home", "work", "services", "about", "contact"),
        "brands looking for someone to run their marketing", "confident, direct, a bit loud",
        ("A branding studio for food and drink start-ups, with a portfolio and a short enquiry form"),
        ("Testimonial quotes are placeholders until real clients give you one; the page labels them.",),
    ),
    Template(
        "luxury-editorial", "Luxury Editorial", "Business & Corporate",
        ("Architecture", "Interior design", "Premium brands"),
        "Large imagery, elegant typography, generous whitespace, project galleries and quiet motion.",
        "luxury", "agency",
        ("about", "services", "work", "gallery", "visit"),
        ("uploads", "layout"),
        ("project galleries", "studio profile", "enquiries from the studio"),
        ("home", "projects", "studio", "contact"),
        "private clients and developers who buy on taste", "spare, unhurried, understated",
        ("An interior architecture studio for period homes, shown as a gallery of completed projects"),
        ("Image uploads need your own storage keys - the gallery ships as CSS panels until you connect them.",
         "Respects prefers-reduced-motion: the quiet animation stops for people who ask it to."),
    ),
    Template(
        "saas-launchpad", "SaaS Launchpad", "SaaS, AI & Technology",
        ("SaaS", "Startups", "Software products"),
        "Product hero, feature proof, a pricing ladder, integrations, FAQs and conversion calls to action.",
        "saas", "saas",
        ("skills", "preview", "testimonials", "pricing", "contact"),
        ("authentication", "pricing", "analytics"),
        ("sign-up and login", "pricing plans", "usage analytics"),
        ("home", "pricing", "features", "contact"),
        "small teams who buy software themselves", "clear, practical, benefit-led",
        ("An invoice reminder tool for freelancers that politely chases late payments",
         "A receipt scanner for small business owners that sorts expenses for tax season",
         "A virtual coworking space for remote workers who struggle to focus alone"),
        ("Plan prices are placeholders until you set them.",
         "Payments and analytics stay scaffolding: your Stripe or provider keys come last, in SETUP.md."),
    ),
    Template(
        "ai-future", "AI Future", "SaaS, AI & Technology",
        ("AI tools", "Automation", "Developer products"),
        "Dark visual system with subtle gradients, capability sections, a demo area and product previews.",
        "gradient", "ai",
        ("stats", "skills", "preview", "pricing", "contact"),
        ("api", "authentication", "records"),
        ("model API integration", "usage-based account", "prompt history"),
        ("home", "pricing", "docs", "contact"),
        "technical buyers and their teams", "sharp, technical, no magic-wand talk",
        ("A tool that finds the best short clips in long podcast episodes for creators",
         "An email triage assistant for busy founders that drafts replies in their voice"),
        ("The demo area is a CSS-drawn frame, not a recording - bring your own screenshots.",
         "An API integration ships as code with your key names in it, never a working call to a model."),
    ),
    Template(
        "developer-portfolio", "Developer Portfolio", "SaaS, AI & Technology",
        ("Developers", "Engineers", "Technical founders"),
        "Skills, shipped projects, repository links, experience, measurable achievements and contact.",
        "dark", "portfolio",
        ("stats", "skills", "work", "timeline", "contact"),
        ("contact", "layout"),
        ("project write-ups", "contact form", "link to my repositories"),
        ("home", "work", "about", "contact"),
        "hiring managers and founders looking for an engineer", "matter-of-fact, specific",
        ("A portfolio for a backend engineer who ships tooling for small teams"),
        ("Repository links and employers are yours to add - the crew will not invent either, and an "
         "invented job reads as a lie.",),
    ),
    Template(
        "fashion-boutique", "Fashion Boutique", "E-commerce & Retail",
        ("Fashion", "Clothing", "Accessories"),
        "Editorial homepage, product grid, categories, product detail, cart and checkout scaffolding.",
        "editorial", "store",
        ("about", "catalog", "gallery", "visit"),
        ("catalog", "browse", "authentication"),
        ("product grid", "categories", "cart and checkout", "customer accounts"),
        ("home", "shop", "product", "contact"),
        "shoppers who browse by look rather than by filter", "polished, warm, editorial",
        ("A boutique for handmade knitwear, with seasonal collections and a size guide"),
        ("Checkout is scaffolding: a payment provider account and its keys are yours to connect.",
         "Product photos and prices are placeholders - nothing here is a real garment or a real order."),
    ),
    Template(
        "tech-store", "Tech Store", "E-commerce & Retail",
        ("Electronics", "Phone accessories", "Gadgets"),
        "Product filters, search, specification tables, comparisons, cart and order tracking.",
        "store", "store",
        ("about", "services", "catalog", "visit"),
        ("catalog", "browse", "records"),
        ("search and filters", "specification per product", "cart and checkout", "order status"),
        ("home", "catalogue", "product", "support", "contact"),
        "people who compare before they buy", "factual, dense with detail",
        ("A store for refurbished laptops and phone gear, with spec tables and a warranty page"),
        ("Order tracking needs the database-backed records feature started by you - it ships as source.",
         "Warranty terms and prices are placeholders until you write the real ones."),
    ),
    Template(
        "beauty-lifestyle", "Beauty & Lifestyle", "E-commerce & Retail",
        ("Beauty", "Skincare", "Lifestyle"),
        "Product storytelling, collections, ingredient detail, reviews, cart and promotions.",
        "glass", "store",
        ("about", "catalog", "testimonials", "visit"),
        ("catalog", "browse", "pricing"),
        ("collections", "ingredient detail", "reviews", "subscribe and save"),
        ("home", "shop", "about", "contact"),
        "repeat buyers who care what is in the bottle", "calm, honest, unhyped",
        ("A small skincare range with refill subscriptions and full ingredient lists per product"),
        ("Reviews are placeholders until real customers send you words you may print.",
         "Claims about results, testing or approvals must come from you - the crew will not make them up."),
    ),
    Template(
        "restaurant-cafe", "Restaurant & Café", "Professional Services",
        ("Restaurants", "Cafés", "Bakeries"),
        "Menu, opening hours, location, gallery, table reservation and an ordering path.",
        "store", "restaurant",
        ("about", "catalog", "gallery", "visit", "booking"),
        ("booking", "catalog", "contact"),
        ("menu with prices", "opening hours", "table booking", "contact form"),
        ("home", "menu", "visit", "contact"),
        "neighbourhood diners and people booking a table", "appetising, plain-spoken",
        ("A digital loyalty card for independent coffee shops with no app download",
         "A neighbourhood bistro with a seasonal menu and table booking on weekends"),
        ("Menu prices are placeholders until you set them.",
         "Reservations arrive nowhere until the booking feature is connected - the page says so on itself."),
    ),
    Template(
        "real-estate-pro", "Real Estate Pro", "Professional Services",
        ("Property", "Rentals", "Real estate agencies"),
        "Property listings, filters, detailed property pages, image galleries and inquiry forms.",
        "luxury", "realestate",
        ("about", "catalog", "gallery", "team", "visit", "booking"),
        ("browse", "booking", "uploads", "contact"),
        ("listings with filters", "photo gallery per property", "booking a viewing", "agent profiles"),
        ("home", "listings", "property", "agents", "contact"),
        "buyers, landlords and tenants", "measured, credible",
        ("A lettings agency for city flats, with searchable listings and viewing appointments"),
        ("Addresses, prices and past sales are yours: an invented listing is worse than an empty one, so "
         "the sample rows are marked as samples.",),
    ),
    Template(
        "healthcare-clinic", "Healthcare & Clinic", "Professional Services",
        ("Clinics", "Healthcare providers", "Wellness"),
        "Services, practitioner profiles, appointment requests, FAQs and location.",
        "corporate", "health",
        ("services", "team", "visit", "booking", "contact"),
        ("booking", "contact", "layout"),
        ("treatments we offer", "practitioner profiles", "appointment request", "clinic location"),
        ("home", "services", "team", "visit", "contact"),
        "patients comparing clinics near them", "calm, careful, clinical",
        ("A 3-minute meditation app for people with anxiety at work",
         "A physiotherapy clinic with evening appointments and a referral form"),
        ("The meditation app above is a retired idea card kept as an example brief - a clinic page is not "
         "a medical device, and no treatment claim here is real until you write one.",
         "Qualifications and registrations must come from you; the crew labels invented ones as samples."),
    ),
    Template(
        "legal-consulting", "Legal & Consulting", "Professional Services",
        ("Law firms", "Advisors", "Consultants"),
        "Practice areas, professional profiles, credentials, case information and consultation requests.",
        "editorial", "legal",
        ("about", "stats", "services", "work", "team", "booking"),
        ("booking", "contact"),
        ("practice areas", "credentials and memberships", "case notes", "book a consultation"),
        ("home", "services", "team", "about", "contact"),
        "clients who need a specific specialism", "formal, exact, reassuring",
        ("A small employment law practice that advises founders, with rates and a consultation request"),
        ("Bar admissions, memberships and past case outcomes must be true and yours - the builder marks "
         "any that the crew invented as placeholders.",),
    ),
    Template(
        "edtech-academy", "EdTech Academy", "Education, Content & Community",
        ("Courses", "Training", "Online education"),
        "Course catalogue, instructor profiles, learning paths, a student area and enrollment.",
        "startup", "education",
        ("catalog", "timeline", "pricing", "team", "booking"),
        ("authentication", "profiles", "booking", "pricing"),
        ("course catalogue", "student sign-in", "progress tracking", "enrollment and payment"),
        ("home", "courses", "pricing", "contact"),
        "working adults studying around a job", "encouraging, concrete",
        ("A language-exchange app for retirees who want to practise with native speakers",
         "An AI math practice coach for middle-school students that explains mistakes kindly",
         "A six-week data course for career changers, with mentor sessions and a certificate"),
        ("Student accounts and progress are database-backed source you start yourself.",
         "Completion rates and student outcomes are placeholders until your data says otherwise."),
    ),
    Template(
        "editorial-blog", "Editorial & Blog", "Education, Content & Community",
        ("Blogs", "Newsletters", "Online publications"),
        "Article layouts, categories, author profiles, search, related stories and newsletter signup.",
        "editorial", "media",
        ("about", "catalog", "team", "contact"),
        ("blog", "browse", "contact"),
        ("article index with categories", "author profiles", "search", "newsletter signup"),
        ("home", "archive", "about", "contact"),
        "regular readers, not one-off visitors", "distinctive, readable",
        ("A fortnightly newsletter about city transport, with an archive and per-author pages"),
        ("Publishing is source you run: the posts arrive as a workspace file set plus the blog feature, "
         "not a live CMS.",
         "The signup form collects nothing until it points at your list provider - the security audit "
         "warns you about that on purpose."),
    ),
    Template(
        "events-conference", "Events & Conference", "Education, Content & Community",
        ("Hackathons", "Conferences", "Meetups"),
        "Schedule, speaker profiles, registration, ticket tiers and a countdown to the day.",
        "brutalist", "event",
        ("stats", "timeline", "pricing", "team", "booking"),
        ("booking", "pricing", "authentication"),
        ("agenda by track", "speaker profiles", "ticket tiers", "registration"),
        ("home", "schedule", "speakers", "tickets", "contact"),
        "attendees deciding whether to come", "energetic, specific",
        ("A two-day hackathon for student developers, with a track agenda and free tickets"),
        ("Dates, venues and speaker names come from you - a countdown to an invented date is a bad way to "
         "launch an event.",),
    ),
    Template(
        "startup-waitlist", "Startup Waitlist", "Startup & Conversion Templates",
        ("Product launches", "Early access", "MVPs"),
        "Focused hero, email capture, product preview, benefits and launch announcements.",
        "minimal", "saas",
        ("stats", "preview", "timeline", "contact"),
        ("records", "contact"),
        ("email capture", "waitlist counter", "launch updates"),
        ("home", "contact"),
        "the first hundred users", "plain, quick, one promise",
        ("A waitlist for a shared calendar that finally works for two-income households"),
        ("Sign-ups land in the page's own status message until the records feature is running: no list is "
         "stored by the page alone.",),
    ),
    Template(
        "mobile-app-showcase", "Mobile App Showcase", "Startup & Conversion Templates",
        ("iOS", "Android", "Mobile products"),
        "Phone mockups drawn in CSS, app features, screenshot gallery, testimonials and store links.",
        "startup", "ai",
        ("skills", "preview", "testimonials", "gallery", "contact"),
        ("layout", "contact"),
        ("feature walkthrough", "screenshot gallery", "store links", "support contact"),
        ("home", "features", "support", "contact"),
        "people deciding on a phone, in one hand", "friendly, short sentences",
        ("A habit tracker for night-shift workers",
         "A two-minute wind-down app for people who can't stop checking work at night"),
        ("Store links and app-store badges are yours to add - the crew will not invent a listing URL.",
         "Screenshots are CSS placeholder panels until you upload real ones."),
    ),
    Template(
        "personal-brand", "Personal Brand", "Startup & Conversion Templates",
        ("Freelancers", "Creators", "Professionals"),
        "Introduction, services, work samples, testimonials, biography and booking links.",
        "minimal", "freelance",
        ("about", "services", "testimonials", "gallery", "booking"),
        ("booking", "contact"),
        ("what I do", "work samples", "about me", "book a call"),
        ("home", "work", "about", "contact"),
        "the one client you want, not any client", "first person, direct",
        ("A commission manager for digital artists to track requests, payments and deadlines",
         "Portfolio and booking page for a freelance illustrator working with publishers"),
        ("Quotes from past clients must be real ones you supply - the page labels invented quotes.",),
    ),
    Template(
        "mobile-service-center", "Mobile Service Center", "Startup & Conversion Templates",
        ("Phone repair", "Accessories", "Device services"),
        "Repair services, device categories, price estimates, booking, accessories and store location.",
        "store", "local",
        ("services", "catalog", "pricing", "visit", "booking"),
        ("booking", "catalog", "contact"),
        ("repair price list", "device categories", "book a slot", "opening hours", "accessories for sale"),
        ("home", "services", "book", "visit", "contact"),
        "people with a broken phone today", "practical, straight, local",
        ("A phone and laptop repair shop with same-day screen fixes, a price list and online booking",
         "A booking and live-tracking service for neighbourhood dog walkers"),
        ("Prices are placeholders until you set them - an estimate the shop cannot honour costs more than "
         "no number at all.",),
    ),
)

TEMPLATES: tuple[Template, ...] = TEMPLATE_LIST
_BY_KEY: dict[str, Template] = {t.key: t for t in TEMPLATES}


def get(key: str) -> Template | None:
    """The template with this key, or None. Nothing here substitutes a different template for an
    unknown id - a card that silently became another one is invisible to the person who clicked it."""
    return _BY_KEY.get(str(key or ""))


def keys() -> tuple[str, ...]:
    return tuple(t.key for t in TEMPLATES)


def in_category(category: str) -> tuple[Template, ...]:
    return tuple(t for t in TEMPLATES if t.category == category)


def as_card(t: Template) -> dict:
    """One template as the gallery draws it. Style and business names come from the registries that
    actually build the site, so a card cannot advertise a layout no run can produce."""
    style = design_styles.get(t.style)
    business = design_styles.BUSINESS_BY_KEY.get(t.business)
    return {
        "key": t.key, "label": t.label, "category": t.category, "industries": list(t.industries),
        "summary": t.summary, "style": t.style,
        "style_label": style.label if style else t.style,
        "style_blurb": style.blurb if style else "",
        "business": t.business, "business_label": business.label if business else t.business,
        "sections": list(t.sections), "blocks": t.blocks(),
        "features": t.feature_rows(), "asks": list(t.asks), "pages": list(t.pages),
        "audience": t.audience, "tone": t.tone, "idea": t.ideas[0], "ideas": list(t.ideas),
        "notes": list(t.notes), "status": t.weakest(),
        "status_label": caps.STATE_LABEL.get(t.weakest(), ""),
    }


def cards() -> list[dict]:
    return [as_card(t) for t in TEMPLATES]


def catalog() -> dict:
    """The whole gallery in one response, grouped in the order the categories are meant to read."""
    return {"categories": list(CATEGORIES),
            "templates": cards(),
            "counts": {"templates": len(TEMPLATES), "categories": len(CATEGORIES)},
            "note": ("A template fixes the layout, the content blocks and the requests the brief carries. "
                     "Features it names are built later, in the workspace, and reviewed before anything "
                     "reaches the page.")}


def spec_for(t: Template, idea: str = "") -> dict:
    """The template as the `SiteSpec` a project stores, so a card and a hand-written brief are the same
    kind of request - and the owner can change any field of it in the wizard before launching."""
    return {
        "business_type": t.business,
        "audience": t.audience,
        "pages": list(t.pages),
        "style": t.style,
        "color": "",
        "features": list(t.asks),
        "tone": t.tone,
        "sections": list(t.sections),
        "feature_keys": list(t.features),
        "template": t.key,
        "theme": {},
        "idea": idea or t.ideas[0],
    }
