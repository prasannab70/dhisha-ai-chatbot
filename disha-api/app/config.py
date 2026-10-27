from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # MySQL. Create the database and user with sql/schema.sql first.
    database_url: str = "mysql+pymysql://disha:disha-pass@localhost:3306/disha?charset=utf8mb4"
    # Laptop testing only: lets DATABASE_URL=sqlite:///./local-test.db start the app without MySQL. Never on a server.
    allow_local_test_db: bool = False
    # Which model runs Disha: anthropic | groq | ollama | openai
    llm_provider: str = "anthropic"
    # single = every message goes to LLM_PROVIDER.
    # hybrid = simple questions go to HYBRID_BASIC_PROVIDER (cheap/local), complex ones to HYBRID_COMPLEX_PROVIDER;
    #          if the basic model fails, the same message is retried on the complex one.
    llm_mode: str = "single"
    hybrid_basic_provider: str = "ollama"
    hybrid_complex_provider: str = "anthropic"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-5-5"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"      # free tier on console.groq.com; see README for alternatives
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_fallback_model: str = ""                       # second Groq model for per-minute limits; must exist on your account ("" = none)
    llm_max_rate_wait_seconds: float = 3.0               # wait this long at most for a rate limit before falling back
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "llama3.1:8b"                # any Ollama model with tool support (llama3.1, qwen2.5, mistral-nemo)
    ollama_timeout_seconds: int = 600                # local CPU models are slow; seconds allowed per model call
    llm_timeout_seconds: int = 120                   # per model call for Groq / OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"

    wa_token: str = ""
    wa_phone_number_id: str = ""
    wa_verify_token: str = "verify"
    wa_template_confirm: str = "booking_confirmed"
    wa_template_reminder: str = "appointment_reminder"

    retell_secret: str = "change-me"
    # "Talk to Disha AI" web page (/disha/): Retell API key (dashboard -> API Keys) and the agent id or its share link
    retell_api_key: str = ""
    retell_agent_id: str = ""
    voice_calls_per_minute: int = 5
    # On calls: if an answer takes longer than this (seconds), Disha first says "One moment, let me check that".
    # 0 turns it off.
    call_checking_seconds: float = 1.5
    # Phone line: the Indian numbers imported into Retell (both can be live at once for incoming calls).
    # PHONE_PROVIDER picks which one Disha calls OUT from: plivo | exotel
    phone_provider: str = "plivo"
    plivo_number: str = ""          # e.g. +918071234567
    exotel_number: str = ""         # e.g. +918047112233
    outbound_calls_per_hour: int = 30
    # DhishaAI Admin Portal (the Node LMS): every lead, booking and callback Disha captures becomes an Enquiry there.
    # Make a 'counsellor' user in the portal for Disha and put its sign-in here. Empty LMS_URL = off.
    lms_url: str = ""                 # e.g. http://127.0.0.1:4000  (same server) or https://portal.dhishaai.com
    lms_email: str = ""
    lms_password: str = ""
    lms_timeout_seconds: int = 15
    console_token: str = "change-me-too"

    # Website (WordPress) integration
    site_key: str = "change-me-site-key"            # shared secret between the WordPress plugin and this API
    allowed_origins: str = "*"                       # comma-separated, e.g. https://dhishaai.com,https://www.dhishaai.com
    wp_base_url: str = ""                            # e.g. https://dhishaai.com ; when set, courses sync from WordPress
    wp_sync_minutes: int = 10
    web_rate_limit_per_minute: int = 20

    # Website knowledge (app/site_refresh.py): Disha downloads the website on start and every WEBSITE_REFRESH_HOURS,
    # reading every page in its sitemap (plus WEBSITE_PAGES, always). New pages on the site are picked up automatically.
    website_url: str = "https://dhishaai.com"
    website_pages: str = ("/,/about-us/,/services/,/learning-development/,/product-development/,/project-consulting/,"
                          "/resource-management/,/industries/,/products/,/careers/,/testimonials/,/insights/,/contact/")
    website_refresh_enabled: bool = True
    website_refresh_hours: int = 6
    website_max_pages: int = 80
    website_timeout_seconds: int = 20

    office_name: str = "DhishaAI Complete Analytics"
    office_address: str = "Arya Hub Mall, Prashanth Extension, Whitefield, Bengaluru 560066"
    office_landmark: str = "Near Hope Farm junction, Whitefield Main Road"
    office_metro: str = "Hopefarm Channasandra (Purple Line), about 10 minutes' walk"
    office_hours: str = "9:30 AM to 7:00 PM, Mon to Sat"
    office_phone: str = "+91 98860 96090"            # from dhishaai.com (also WhatsApp)
    office_email: str = "contactus@dhishaai.com"
    tz: str = "Asia/Kolkata"

    slot_minutes: int = 30
    reminder_minutes_before: int = 60


settings = Settings()
