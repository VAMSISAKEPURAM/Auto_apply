import os
import json
import re
import time
from typing import Dict, Any, Optional
from groq import Groq

from .utils import load_settings, load_resume, setup_logger
from .db import get_unscored_jobs, update_job_score

logger = setup_logger("ranker")


def get_groq_client() -> Optional[Groq]:
    """Get initialized Groq client if API key is present."""
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        logger.error("GROQ_API_KEY environment variable is not set. Please add it to your .env file.")
        return None
    return Groq(api_key=api_key)


def parse_json_from_response(raw_text: str) -> Dict[str, Any]:
    """Extract JSON object from LLM response even if wrapped in markdown."""
    text = raw_text.strip()
    # Remove markdown code block if present
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    else:
        # Match outermost curly braces
        match_braces = re.search(r"(\{.*\})", text, re.DOTALL)
        if match_braces:
            text = match_braces.group(1)
            
    return json.loads(text)


def score_job_fit(client: Groq, resume_text: str, job: Dict[str, Any], model: str = "qwen/qwen3.8-27b") -> Dict[str, Any]:
    """
    Query Groq LLM to compute a 0-100 relevance score and justification.
    """
    job_summary = f"""
Job Title: {job.get('title', 'N/A')}
Company: {job.get('company', 'N/A')}
Location: {job.get('location', 'N/A')}
Experience Required: {job.get('experience', 'N/A')}
Key Skills: {job.get('skills', 'N/A')}
Description/Summary: {job.get('description', 'N/A')}
"""

    system_prompt = (
        "You are an expert technical recruiter and resume evaluator. "
        "Your task is to evaluate the match between a candidate's resume and a job posting on a scale of 0 to 100. "
        "Criteria:\n"
        "1. Required technical skills vs candidate skills (50% weight)\n"
        "2. Experience level match (30% weight)\n"
        "3. Domain/role alignment (20% weight)\n\n"
        "You MUST respond ONLY with a JSON object in this exact schema, with no preamble or additional text:\n"
        "{\n"
        '  "score": <integer from 0 to 100>,\n'
        '  "justification": "<one concise sentence explaining the score>"\n'
        "}"
    )

    user_prompt = f"Candidate Resume:\n{resume_text}\n\nJob Posting:\n{job_summary}"

    for attempt in range(1, 4):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=500
            )
            content = response.choices[0].message.content
            parsed = parse_json_from_response(content)
            score = int(parsed.get("score", 0))
            score = max(0, min(100, score)) # clamp 0-100
            justification = parsed.get("justification", "").strip()
            return {"score": score, "justification": justification}

        except Exception as e:
            logger.warning(f"Attempt {attempt} failed to score job {job.get('id')}: {e}")
            time.sleep(1.5 * attempt)

    # Fallback if LLM fails
    return {"score": 50, "justification": "Scoring failed due to API / parsing error"}


def run_ranker(limit: int = 50) -> Dict[str, int]:
    """
    Fetch unscored jobs from DB, evaluate them against resume.txt with Groq,
    and persist results.
    """
    settings = load_settings()
    min_score = settings.get("filters", {}).get("min_relevance_score", 75)
    model = settings.get("llm", {}).get("model", "llama-3.3-70b-versatile")

    try:
        resume_text = load_resume()
    except Exception as e:
        logger.error(f"Cannot run ranker: {e}")
        return {"processed": 0, "qualified": 0}

    client = get_groq_client()
    if not client:
        print("\n[ERROR] GROQ_API_KEY is not set. Please create a .env file with your key:")
        print("GROQ_API_KEY=gsk_...\n")
        return {"processed": 0, "qualified": 0}

    unscored = get_unscored_jobs(limit=limit)
    if not unscored:
        logger.info("No unscored jobs found in database.")
        return {"processed": 0, "qualified": 0}

    logger.info(f"Ranking {len(unscored)} unscored jobs using Groq ({model})...")
    
    stats = {"processed": 0, "qualified": 0, "skipped": 0}
    
    for job in unscored:
        logger.info(f"Scoring #{job['id']}: '{job['title']}' at '{job['company']}'")
        result = score_job_fit(client, resume_text, job, model=model)
        score = result["score"]
        justification = result["justification"]
        
        status = "scored" if score >= min_score else "skipped"
        update_job_score(job["id"], score, justification, status)
        
        stats["processed"] += 1
        if status == "scored":
            stats["qualified"] += 1
            logger.info(f"-> [QUALIFIED] Score: {score}/100 | {justification}")
        else:
            stats["skipped"] += 1
            logger.info(f"-> [SKIPPED] Score: {score}/100 | {justification}")

        # Minor pause between LLM calls to respect rate limits
        time.sleep(0.5)

    logger.info(
        f"Ranking Complete: {stats['processed']} scored, "
        f"{stats['qualified']} qualified (score >= {min_score}), {stats['skipped']} skipped."
    )
    return stats
