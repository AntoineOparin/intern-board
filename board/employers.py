"""Well-known software and tech employers whose job boards are always on the watchlist.

Some of the biggest intern hirers were never added automatically: the community lists link to
their own careers sites (stripe.com/jobs, careers.withwaymo.com), not to the job board behind them.
Companies with a career site of their own (Amazon, Google, Meta) are read by sites.py. Each board
here answered when it was added (October 2026). Boards with no internships are checked every 6
hours, like the others.

To add one, use the Companies page (it accepts a careers page link) or add a line here.
"""

# (platform, board token, company name), tokens as ats.parse_board_url() returns them.
BOARDS = [
    # Their own career sites (sites.py)
    ("site", "amazon", "Amazon"),
    ("site", "google", "Google"),
    ("site", "microsoft", "Microsoft"),
    ("site", "apple", "Apple"),
    ("site", "meta", "Meta"),
    ("site", "tiktok", "TikTok"),
    ("site", "bytedance", "ByteDance"),
    ("site", "goldman", "Goldman Sachs"),
    ("site", "ibm", "IBM"),
    ("site", "shopify", "Shopify"),
    ("oracle", "iaziqy.fa.ocs/CX_1", "Uber"),
    ("eightfold", "explore.jobs.netflix.net", "Netflix"),
    # Big tech, cloud and security
    ("workday", "salesforce.wd12/external_career_site", "Salesforce"),
    ("greenhouse", "databricks", "Databricks"),
    ("greenhouse", "datadog", "Datadog"),
    ("greenhouse", "mongodb", "MongoDB"),
    ("greenhouse", "okta", "Okta"),
    ("workday", "paloaltonetworks.wd5/panwexternalcareers", "Palo Alto Networks"),
    ("workday", "cisco.wd5/cisco_careers", "Cisco"),
    ("workday", "broadcom.wd1/external_career", "Broadcom"),
    ("workday", "hp.wd5/externalcareersite", "HP"),
    ("workday", "hpe.wd5/jobsathpe", "HPE"),
    ("workday", "sonyglobal.wd1/sonyglobalcareers", "Sony"),
    ("greenhouse", "sonyinteractiveentertainmentglobal", "Sony Interactive Entertainment"),
    ("workday", "zoom.wd5/zoom", "Zoom"),
    ("jibe", "careers.docusign.com", "DocuSign"),
    # Consumer internet
    ("greenhouse", "airbnb", "Airbnb"),
    ("greenhouse", "instacart", "Instacart"),
    ("greenhouse", "lyft", "Lyft"),
    ("greenhouse", "pinterest", "Pinterest"),
    ("greenhouse", "reddit", "Reddit"),
    ("workday", "snapchat.wd1/snap", "Snap"),
    ("greenhouse", "discord", "Discord"),
    ("greenhouse", "dropbox", "Dropbox"),
    ("greenhouse", "asana", "Asana"),
    ("greenhouse", "duolingo", "Duolingo"),
    ("workday", "expedia.wd108/search", "Expedia"),
    ("workday", "zillow.wd5/zillow_group_external", "Zillow"),
    ("greenhouse", "squarespace", "Squarespace"),
    # Developer tools and infrastructure
    ("greenhouse", "gitlab", "GitLab"),
    ("greenhouse", "elastic", "Elastic"),
    ("greenhouse", "grafanalabs", "Grafana Labs"),
    ("greenhouse", "coreweave", "CoreWeave"),
    ("greenhouse", "samsara", "Samsara"),
    ("greenhouse", "toast", "Toast"),
    # Fintech and payments
    ("greenhouse", "stripe", "Stripe"),
    ("ashby", "plaid", "Plaid"),
    ("greenhouse", "block", "Block"),
    ("greenhouse", "coinbase", "Coinbase"),
    ("greenhouse", "brex", "Brex"),
    ("greenhouse", "chime", "Chime"),
    ("greenhouse", "sofi", "SoFi"),
    ("workday", "paypal.wd1/jobs", "PayPal"),
    ("workday", "mastercard.wd1/corporatecareers", "Mastercard"),
    ("lever", "wealthfront", "Wealthfront"),
    ("greenhouse", "fanduel", "FanDuel"),
    # AI
    ("workable", "huggingface", "Hugging Face"),
    ("ashby", "runway-ml", "Runway"),
    ("ashby", "character", "Character.AI"),
    ("ashby", "anyscale", "Anyscale"),
    # Trading
    ("greenhouse", "wehrtyou", "Hudson River Trading"),
    ("greenhouse", "jumptrading", "Jump Trading"),
    ("greenhouse", "imc", "IMC Trading"),
    ("greenhouse", "towerresearchcapital", "Tower Research Capital"),
    ("avature", "careers.twosigma.com/careers", "Two Sigma"),
    ("greenhouse", "akunacapital", "Akuna Capital"),
    ("greenhouse", "squarepointcapital", "Squarepoint Capital"),
    # Hardware, robotics, autonomy and space
    ("workday", "micron.wd1/external", "Micron"),
    ("jibe", "careers.amd.com", "AMD"),
    ("eightfold", "qualcomm.eightfold.ai", "Qualcomm"),
    ("jibe", "jobs.keysight.com", "Keysight"),
    ("successfactors", "careers.qorvo.com", "Qorvo"),
    ("avature", "synopsys.avature.net/careers", "Synopsys"),
    ("jibe", "careers.garmin.com", "Garmin"),
    ("jibe", "careers.rivian.com", "Rivian"),
    ("eightfold", "johndeere.eightfold.ai", "John Deere"),
    ("successfactors", "jobs.l3harris.com", "L3Harris"),
    ("jibe", "careers.jhuapl.edu", "Johns Hopkins APL"),
    ("greenhouse", "tenstorrent", "Tenstorrent"),
    ("greenhouse", "waymo", "Waymo"),
    ("greenhouse", "flyzipline", "Zipline"),
    ("ashby", "aurora-operations-inc", "Aurora"),
    ("greenhouse", "nuro", "Nuro"),
    ("workday", "bostondynamics.wd1/boston_dynamics", "Boston Dynamics"),
    ("workday", "blueorigin.wd5/blueorigin", "Blue Origin"),
    ("greenhouse", "relativity", "Relativity Space"),
    # Games
    ("greenhouse", "nintendo", "Nintendo of America"),
    ("greenhouse", "roblox", "Roblox"),
    ("workday", "unitytech.wd1/unity", "Unity"),
    ("avature", "jobs.ea.com/en_US/careers", "Electronic Arts"),
    # Canada
    ("icims", "careers-kinaxis", "Kinaxis"),
    ("jibe", "careers.kpmg.ca", "KPMG Canada"),
    ("lever", "wattpad", "Wattpad"),
    ("greenhouse", "hootsuite", "Hootsuite"),
    ("ashby", "koho", "KOHO"),
    ("greenhouse", "d2l", "D2L"),
    ("greenhouse", "shakepay", "Shakepay"),
    ("lever", "mistplay", "Mistplay"),
    ("workable", "busbud", "Busbud"),
]
