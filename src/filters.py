import re
import urllib.parse
from typing import Dict, Any, List, Optional, Tuple
from .utils import setup_logger

logger = setup_logger("filters")

# City alias dictionary mapping canonical cities to common spellings, tech hubs, and sub-regions
CITY_ALIASES: Dict[str, List[str]] = {
    "bengaluru": [
        "bengaluru", "bangalore", "blr", "electronic city", "whitefield", 
        "bellandur", "koramangala", "indiranagar", "marathahalli", "manyata", 
        "karnataka", "outer ring road"
    ],
    "hyderabad": [
        "hyderabad", "secunderabad", "hyd", "hitech city", "hitec city", 
        "gachibowli", "madhapur", "kondapur", "telangana", "cyberabad"
    ],
    "remote": [
        "remote", "work from home", "wfh", "virtual", "telecommute", 
        "work-from-home", "anywhere", "pan india", "any location"
    ],
    "pune": [
        "pune", "hinjewadi", "magarpatta", "kharadi", "baner", "maharashtra", "viman nagar"
    ],
    "mumbai": [
        "mumbai", "bombay", "navi mumbai", "thane", "andheri", "bkc", "bandra", "goregaon", "powai"
    ],
    "delhi": [
        "delhi", "new delhi", "ncr", "delhi ncr", "delhi/ncr"
    ],
    "noida": [
        "noida", "greater noida", "noida expressway", "uttar pradesh", "up"
    ],
    "gurgaon": [
        "gurgaon", "gurugram", "cyber city", "golf course road", "haryana", "sohna road", "manesar"
    ],
    "chennai": [
        "chennai", "madras", "omr", "t nagar", "velachery", "siruseri", "tamil nadu", "guindy"
    ],
    "kolkata": [
        "kolkata", "calcutta", "salt lake", "new town", "sector v", "west bengal"
    ],
    "ahmedabad": [
        "ahmedabad", "gandhinagar", "gift city", "gujarat"
    ]
}


def normalize_string(text: str) -> str:
    """Lowercase and strip punctuation."""
    if not text:
        return ""
    return re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower()).strip()


def parse_experience_range(exp_str: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Parse experience strings from job cards into (min_years, max_years).
    Examples:
    - '1-2 Yrs' -> (1.0, 2.0)
    - '0 - 2 years' -> (0.0, 2.0)
    - '3-5 Yrs' -> (3.0, 5.0)
    - '5+ Yrs' -> (5.0, 99.0)
    - '2 Yrs' -> (2.0, 2.0)
    - 'Fresher' -> (0.0, 0.5)
    - '1 to 2 years' -> (1.0, 2.0)
    """
    if not exp_str:
        return (None, None)

    exp_clean = exp_str.lower().strip()

    if "fresher" in exp_clean or "entry" in exp_clean:
        return (0.0, 1.0)

    # Match 'X - Y yrs' or 'X to Y yrs' or 'X-Y'
    range_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)", exp_clean)
    if range_match:
        return (float(range_match.group(1)), float(range_match.group(2)))

    # Match 'X+ yrs' or 'X + yrs'
    plus_match = re.search(r"(\d+(?:\.\d+)?)\s*\+", exp_clean)
    if plus_match:
        return (float(plus_match.group(1)), 99.0)

    # Match single number 'X yrs' or 'X year'
    single_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:yr|year)", exp_clean)
    if single_match:
        val = float(single_match.group(1))
        return (val, val)

    # Match just lone numbers if short
    lone_match = re.search(r"^(\d+(?:\.\d+)?)$", exp_clean)
    if lone_match:
        val = float(lone_match.group(1))
        return (val, val)

    return (None, None)


def extract_experience_from_text(text: str) -> Optional[str]:
    """
    Search text (such as job title or description) for explicit experience requirements.
    Examples: '1-2 years', '1 to 2 yrs', '2+ years', 'experience: 1-2'.
    """
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?|yr)\b", text, re.IGNORECASE)
    if m:
        return f"{m.group(1)}-{m.group(2)} Yrs"
    m = re.search(r"experience\s*[:\-]\s*(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if m:
        return f"{m.group(1)}-{m.group(2)} Yrs"
    m = re.search(r"(\d+(?:\.\d+)?)\s*\+\s*(?:years?|yrs?|yr)\b", text, re.IGNORECASE)
    if m:
        return f"{m.group(1)}+ Yrs"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:years?|yrs?|yr)\s*(?:of\s*)?experience\b", text, re.IGNORECASE)
    if m:
        return f"{m.group(1)} Yrs"
    return None


def is_experience_matching(
    job_exp_str: str, 
    target_exp_years: float = 1.0,
    min_tolerance_years: Optional[float] = None,
    max_tolerance_years: Optional[float] = None,
    strict_match: bool = False,
    include_0_to_2: bool = True
) -> bool:
    """
    Verify if the job's stated experience matches the required experience range.
    Strict rule: strictly matches roles with experience between min_tolerance_years (1.0) and max_tolerance_years (2.0).
    When include_0_to_2 is True, also permits entry-level postings requiring 0-2 years.
    Rejects any role exceeding max_tolerance_years (e.g. 1-3, 2-5, 3-5, 3-8, 5+ yrs).
    In strict mode, rejects roles where experience is unstated or missing.
    """
    if not job_exp_str or not job_exp_str.strip():
        if strict_match:
            logger.debug("Filter REJECT [Strict Experience]: No experience stated on job card")
            return False
        return True

    job_min, job_max = parse_experience_range(job_exp_str)
    if job_min is None and job_max is None:
        if strict_match:
            logger.debug(f"Filter REJECT [Strict Experience]: Could not parse experience from '{job_exp_str}'")
            return False
        return True

    if min_tolerance_years is not None:
        allowed_min = min_tolerance_years
    elif strict_match or target_exp_years <= 2.0:
        allowed_min = 1.0
    else:
        allowed_min = max(0.0, target_exp_years - 2.0)

    if max_tolerance_years is not None:
        allowed_max = max_tolerance_years
    elif strict_match or target_exp_years <= 2.0:
        allowed_max = 2.0
    else:
        allowed_max = target_exp_years + 3.0

    # 1. Reject if job explicitly requires more than allowed maximum
    # e.g. 1-3 Yrs, 2-5 Yrs, 3-5 Yrs, 3-8 Yrs, 5+ Yrs, 10-15 Yrs
    if job_max is not None and job_max > allowed_max:
        logger.debug(f"Filter REJECT [Experience too high]: Job requires '{job_exp_str}' (max {job_max}), strictly allowed max is {allowed_max} Yrs")
        return False

    if job_min is not None and job_min > allowed_max:
        logger.debug(f"Filter REJECT [Experience too high]: Job requires '{job_exp_str}' (min {job_min}), strictly allowed max is {allowed_max} Yrs")
        return False

    # 2. Minimum experience checks
    if strict_match:
        if include_0_to_2:
            # Matches 1-2 Yrs, 0-2 Yrs, 1 Yr, 2 Yrs
            # If job_max < allowed_min (e.g. pure fresher 0-0.5 yrs), reject
            if job_max is not None and job_max < allowed_min:
                logger.debug(f"Filter REJECT [Experience too low]: Job requires '{job_exp_str}' (max {job_max}), strictly requires >= {allowed_min} Yrs")
                return False
            return True
        else:
            # Strictly requires job_min >= allowed_min (e.g. min >= 1.0)
            if job_min is not None and job_min < allowed_min:
                logger.debug(f"Filter REJECT [Experience too low]: Job requires '{job_exp_str}' (min {job_min}), strictly requires >= {allowed_min} Yrs")
                return False
            return True

    return True


def is_location_matching(
    job_location_str: str, 
    preferred_locations: List[str],
    strict_match: bool = True
) -> bool:
    """
    Verify if the job's location matches any of the candidate's preferred locations.
    Uses canonical city aliases and handles remote/hybrid work designations.
    """
    if not preferred_locations:
        return True

    if not job_location_str or not job_location_str.strip():
        # If location is unspecified, allow to pass if not overly strict
        return not strict_match

    job_loc_norm = normalize_string(job_location_str)

    # Check if job is Remote / WFH (almost universally matches any preferred location)
    for alias in CITY_ALIASES["remote"]:
        if alias in job_loc_norm:
            return True

    # Check against each preferred location and its aliases
    for pref in preferred_locations:
        pref_norm = pref.strip().lower()
        
        # Check direct substring
        if pref_norm in job_loc_norm:
            return True

        # Check aliases
        aliases = CITY_ALIASES.get(pref_norm, [pref_norm])
        for alias in aliases:
            if alias in job_loc_norm:
                return True

    # If strict matching is enabled, reject locations that don't match any preferred hub
    if strict_match:
        logger.debug(f"Filter REJECT [Location mismatch]: Job location '{job_location_str}' does not match preferred {preferred_locations}")
        return False

    return True


def filter_job_card(
    job_card_data: Dict[str, Any],
    settings: Dict[str, Any]
) -> Tuple[bool, str]:
    """
    Apply comprehensive pre-filters (Experience, City, Role Relevance) on a scraped job card.
    Returns (True, 'passed') if the job satisfies all criteria, or (False, reason) if rejected.
    """
    search_cfg = settings.get("search", {})
    filters_cfg = settings.get("filters", {})

    target_exp = float(search_cfg.get("experience_years", 3))
    min_exp_tol = filters_cfg.get("experience_min")
    max_exp_tol = filters_cfg.get("experience_max")
    if min_exp_tol is not None:
        min_exp_tol = float(min_exp_tol)
    if max_exp_tol is not None:
        max_exp_tol = float(max_exp_tol)

    preferred_locations = search_cfg.get("locations", ["Bengaluru", "Remote"])
    strict_loc = filters_cfg.get("strict_location_match", True)

    # 1. Experience Check (strict 1 to 2 years rule)
    job_exp = job_card_data.get("experience", "")
    if not job_exp or not job_exp.strip():
        # Fallback: check title and description for explicit experience mentions
        inferred = extract_experience_from_text(f"{job_card_data.get('title', '')} {job_card_data.get('description', '')}")
        if inferred:
            job_exp = inferred
            job_card_data["experience"] = inferred

    strict_exp = filters_cfg.get("strict_experience_match", True)
    include_0_to_2 = filters_cfg.get("include_entry_level_0_to_2", True)

    if not is_experience_matching(
        job_exp, 
        target_exp_years=target_exp, 
        min_tolerance_years=min_exp_tol, 
        max_tolerance_years=max_exp_tol,
        strict_match=strict_exp,
        include_0_to_2=include_0_to_2
    ):
        return False, f"Experience mismatch: job requires '{job_exp}', strictly restricted to {min_exp_tol}-{max_exp_tol} Yrs"

    # 2. Location Check
    job_loc = job_card_data.get("location", "")
    if not is_location_matching(job_loc, preferred_locations, strict_match=strict_loc):
        return False, f"Location mismatch: job location '{job_loc}' not in preferred {preferred_locations}"

    # 3. Title Check (Filter out completely irrelevant roles)
    title = job_card_data.get("title", "").lower()
    negative_title_keywords = [
        "telecaller", "bpo", "customer care", "sales executive", "accountant", 
        "data entry", "receptionist", "driver", "graphic designer intern", "medical representative"
    ]
    for neg in negative_title_keywords:
        if neg in title:
            return False, f"Irrelevant job title role: contains '{neg}'"

    return True, "passed"


# Platform-specific Search URL Builders with Experience & City Filters

def build_naukri_search_url(keyword: str, location: str = "", experience_years: int = 1, job_age_days: int = 30) -> str:
    """
    Construct Naukri search URL with full query and path filters:
    - keyword (k)
    - location (l)
    - experience (experience)
    - freshness (jobAge)
    - work from home / remote (wfhType)
    """
    kw_slug = re.sub(r"[^a-zA-Z0-9]+", "-", keyword.strip().lower()).strip("-")
    loc_slug = re.sub(r"[^a-zA-Z0-9]+", "-", location.strip().lower()).strip("-") if location else ""

    is_remote = location.strip().lower() in ["remote", "work from home", "wfh"]

    if kw_slug and loc_slug and not is_remote:
        path = f"{kw_slug}-jobs-in-{loc_slug}"
    elif kw_slug:
        path = f"{kw_slug}-jobs"
    else:
        path = "jobs"

    params: Dict[str, Any] = {
        "k": keyword.strip()
    }
    
    if location and not is_remote:
        params["l"] = location.strip()

    if experience_years is not None and experience_years >= 0:
        params["experience"] = str(int(experience_years))

    if job_age_days:
        params["jobAge"] = str(int(job_age_days))

    if is_remote:
        params["wfhType"] = "2"  # Naukri Remote WFH filter

    query_str = urllib.parse.urlencode(params)
    return f"https://www.naukri.com/{path}?{query_str}"


def build_linkedin_search_url(
    keyword: str, 
    location: str = "", 
    experience_years: int = 1, 
    job_age_days: int = 30, 
    easy_apply_only: bool = True
) -> str:
    """
    Construct LinkedIn search URL with:
    - keywords
    - location
    - Easy Apply (f_AL=true)
    - Experience level (f_E: 1=Intern, 2=Entry, 3=Associate, 4=Mid-Senior, 5=Director, 6=Exec)
    - Time posted (f_TPR: r86400 / r604800 / r2592000)
    - Remote / On-site (f_WT: 1=On-site, 2=Remote, 3=Hybrid)
    """
    params: Dict[str, Any] = {
        "keywords": keyword.strip(),
        "sortBy": "R"
    }

    if easy_apply_only:
        params["f_AL"] = "true"

    if location:
        params["location"] = location.strip()

    is_remote = location.strip().lower() in ["remote", "work from home", "wfh"]
    if is_remote:
        params["f_WT"] = "2"  # Remote filter

    # LinkedIn Experience Level Filter (f_E)
    if experience_years is not None:
        if experience_years <= 2:
            params["f_E"] = "2,3"      # Entry level, Associate (1-2 Yrs)
        elif experience_years <= 6:
            params["f_E"] = "3,4"      # Associate, Mid-Senior
        else:
            params["f_E"] = "4,5"      # Mid-Senior, Director

    # LinkedIn Date Posted Filter (f_TPR)
    if job_age_days:
        if job_age_days <= 1:
            params["f_TPR"] = "r86400"    # 24 hours
        elif job_age_days <= 7:
            params["f_TPR"] = "r604800"   # Past week
        else:
            params["f_TPR"] = "r2592000"  # Past month

    query_str = urllib.parse.urlencode(params)
    return f"https://www.linkedin.com/jobs/search/?{query_str}"


def build_indeed_search_url(keyword: str, location: str = "", experience_years: int = 1, job_age_days: int = 30) -> str:
    """Construct Indeed India search URL with experience, freshness, and location filters."""
    params: Dict[str, Any] = {
        "q": keyword.strip(),
        "fromage": str(min(job_age_days, 30))
    }
    if location:
        params["l"] = location.strip()

    # Experience level tag on Indeed: ENTRY_LEVEL for 1-2 Yrs
    if experience_years is not None:
        if experience_years <= 2:
            params["explvl"] = "ENTRY_LEVEL"
        elif experience_years <= 6:
            params["explvl"] = "MID_LEVEL"
        else:
            params["explvl"] = "SENIOR_LEVEL"

    query_str = urllib.parse.urlencode(params)
    return f"https://in.indeed.com/jobs?{query_str}"


def build_foundit_search_url(
    keyword: str, 
    location: str = "", 
    experience_years: int = 1, 
    min_exp: int = 1, 
    max_exp: int = 2
) -> str:
    """Construct Foundit (Monster India) search URL with experience range and location filters."""
    params: Dict[str, Any] = {
        "query": keyword.strip(),
        "experience": str(experience_years),
        "experienceRanges": f"{min_exp}~{max_exp}"
    }
    if location:
        params["locations"] = location.strip()

    query_str = urllib.parse.urlencode(params)
    return f"https://www.foundit.in/srp/results?{query_str}"


def build_shine_search_url(keyword: str, location: str = "", experience_years: int = 1) -> str:
    """Construct Shine.com search URL with experience and city filters."""
    kw_slug = re.sub(r"[^a-zA-Z0-9]+", "-", keyword.strip().lower()).strip("-")
    loc_slug = re.sub(r"[^a-zA-Z0-9]+", "-", location.strip().lower()).strip("-") if location else ""

    if kw_slug and loc_slug:
        path = f"{kw_slug}-jobs-in-{loc_slug}"
    elif kw_slug:
        path = f"{kw_slug}-jobs"
    else:
        path = "job-search"

    params: Dict[str, Any] = {
        "q": keyword.strip(),
        "exp": str(experience_years)
    }
    if location:
        params["loc"] = location.strip()

    query_str = urllib.parse.urlencode(params)
    return f"https://www.shine.com/job-search/{path}?{query_str}"


def build_instahyre_search_url(keyword: str, location: str = "", experience_years: int = 1) -> str:
    """Construct Instahyre search URL with experience and location parameters."""
    params: Dict[str, Any] = {
        "search": "true",
        "years_of_experience": str(experience_years),
        "job_functions": keyword.strip()
    }
    if location:
        params["location"] = location.strip()

    query_str = urllib.parse.urlencode(params)
    return f"https://www.instahyre.com/candidate/opportunities/?{query_str}"
