import os
import time
import requests

from dotenv import load_dotenv


# =========================================================
# LOAD ENVIRONMENT VARIABLES
# =========================================================

# ai_engine.py loads the .env file itself because app.py
# imports this file before the Flask application starts.
load_dotenv()


# =========================================================
# CAREERBOT HYBRID AI ARCHITECTURE
# =========================================================
#
# 1. PRIMARY AI
#    Google Gemini API
#
# 2. OFFLINE FALLBACK
#    Local Ollama - Llama 3.2
#
# 3. EMERGENCY FALLBACK
#    Built-in CareerBot response
#
# =========================================================


# =========================================================
# GEMINI ONLINE AI SETTINGS
# =========================================================

GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY",
    ""
).strip()


GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.5-flash-lite"
).strip()


GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/"
    f"v1beta/models/{GEMINI_MODEL}:generateContent"
)


# =========================================================
# OLLAMA OFFLINE AI SETTINGS
# =========================================================

OLLAMA_URL = (
    "http://127.0.0.1:11434/api/generate"
)


OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "llama3.2:1b"
).strip()


# =========================================================
# TIMEOUT SETTINGS
# =========================================================

# Gemini should fail quickly if internet is unavailable.
# This is useful during the university viva.
GEMINI_CONNECT_TIMEOUT = 4
GEMINI_READ_TIMEOUT = 20


# Local Ollama can be given slightly more time.
OLLAMA_CONNECT_TIMEOUT = 3
OLLAMA_READ_TIMEOUT = 180
OLLAMA_CONTEXT_SIZE = 3072
OLLAMA_WARMUP_TIMEOUT = 90

# Keep the original Gemini-first behavior unless a mode is selected.
# For a viva without internet, select offline_only in PowerShell.
AI_MODE = os.getenv("CAREERBOT_AI_MODE", "online_first").strip().lower()
if AI_MODE not in ("online_first", "offline_first", "offline_only"):
    print("Unknown CAREERBOT_AI_MODE; using online_first.")
    AI_MODE = "online_first"

# Local requests must not be routed through an internet proxy.
# A separate Session per request is safe for concurrent Flask requests.
def post_to_local_ollama(payload, timeout):
    with requests.Session() as session:
        session.trust_env = False
        return session.post(OLLAMA_URL, json=payload, timeout=timeout)



# =========================================================
# OLLAMA MODEL WARM-UP
# =========================================================

def warm_up_model():

    """
    Preloads the local Ollama model into memory.

    Gemini does not need warm-up because it runs online.

    Ollama is warmed up so that it can quickly take over
    if Gemini or the internet becomes unavailable.
    """

    print()
    print("======================================")
    print("CAREERBOT AI INITIALIZATION")
    print("Engine revision: original-1561-viva-patch")
    print("Mode:", AI_MODE)
    print("======================================")

    print(
        "Configured Online AI:",
        GEMINI_MODEL
    )

    print(
        "Offline AI:",
        OLLAMA_MODEL
    )

    print("--------------------------------------")
    print("Warming up offline AI...")


    payload = {

        "model":
            OLLAMA_MODEL,

        "prompt":
            "Reply only with READY.",

        "stream":
            False,

        "keep_alive":
            "60m",

        "options": {

            "temperature":
                0,

            "num_predict":
                3,

            "num_ctx":
                OLLAMA_CONTEXT_SIZE
        }
    }


    try:

        response = post_to_local_ollama(

            payload=payload,

            timeout=(
                OLLAMA_CONNECT_TIMEOUT,
                OLLAMA_WARMUP_TIMEOUT
            )
        )


        response.raise_for_status()


        print(
            "OLLAMA WARM-UP SUCCESSFUL"
        )

        print(
            "======================================"
        )

        print()

        return True


    except Exception as error:

        print(
            "Offline AI warm-up skipped."
        )

        print(
            "Reason:",
            error
        )

        print(
            "CareerBot can still use Gemini "
            "when internet is available."
        )

        print(
            "======================================"
        )

        print()

        return False


# =========================================================
# BUILD CONVERSATION HISTORY
# =========================================================

def build_history_text(
    conversation_history
):

    """
    Converts recent CareerBot conversation history
    into text that can be supplied to the AI.

    Only recent messages are included to improve:
    - speed
    - token usage
    - response relevance
    """

    if not conversation_history:

        return (
            "No previous conversation."
        )


    # Keep only the latest 8 messages.
    recent_history = (
        conversation_history[-8:]
    )


    history_parts = []


    for message in recent_history:

        role = message.get(
            "role",
            "user"
        )


        content = str(
            message.get(
                "content",
                ""
            )
        )


        # Prevent an extremely large previous message
        # from increasing API latency.
        content = content[:1500]


        if role == "user":

            history_parts.append(
                f"Student: {content}"
            )


        elif role == "ai":

            history_parts.append(
                f"CareerBot: {content}"
            )


    if not history_parts:

        return (
            "No previous conversation."
        )


    return "\n\n".join(
        history_parts
    )


# =========================================================
# BUILD CAREERBOT PROMPT
# =========================================================

def build_prompt(
    user_profile,
    conversation_history,
    user_message,
    retrieved_context=""
):

    """
    Creates one CareerBot prompt that can be used
    by both Gemini and Ollama.
    """


    # -----------------------------------------------------
    # STUDENT NAME
    # -----------------------------------------------------

    name = (
        user_profile.get(
            "name"
        )
        or "Student"
    )


    # -----------------------------------------------------
    # EDUCATION
    # -----------------------------------------------------

    education = (

        user_profile.get(
            "current_education"
        )

        or user_profile.get(
            "degree"
        )

        or "Not provided"
    )


    # -----------------------------------------------------
    # GRADUATION YEAR
    # -----------------------------------------------------

    graduation_year = (
        user_profile.get(
            "graduation_year"
        )
        or "Not provided"
    )


    # -----------------------------------------------------
    # CURRENT SKILLS
    # -----------------------------------------------------

    current_skills = (
        user_profile.get(
            "current_skills"
        )
        or "Not provided"
    )


    # -----------------------------------------------------
    # SKILL LEVEL
    # -----------------------------------------------------

    skill_level = (
        user_profile.get(
            "skill_level"
        )
        or "Not provided"
    )


    # -----------------------------------------------------
    # CAREER GOAL
    # -----------------------------------------------------

    career_goal = (
        user_profile.get(
            "career_goal"
        )
        or "Not provided"
    )


    # -----------------------------------------------------
    # CAREER PREFERENCE
    # -----------------------------------------------------

    career_preference = (
        user_profile.get(
            "career_preference"
        )
        or "Not provided"
    )


    # -----------------------------------------------------
    # ADDITIONAL PROFILE INFORMATION
    # -----------------------------------------------------

    interests = (
        user_profile.get(
            "interests"
        )
        or "Not provided"
    )


    preferred_country = user_profile.get("preferred_country") or "Not specified"
    preferred_city = user_profile.get("preferred_city") or "Not specified"

    # -----------------------------------------------------
    # PREVIOUS CHAT
    # -----------------------------------------------------

    history_text = (
        build_history_text(
            conversation_history
        )
    )


    # -----------------------------------------------------
    # LIMIT CURRENT MESSAGE SIZE
    # -----------------------------------------------------

    user_message = str(
        user_message
    )[:4000]


    # -----------------------------------------------------
    # RETRIEVED KNOWLEDGE
    # -----------------------------------------------------

    retrieved_context = str(
        retrieved_context
        or ""
    )[:6000]


    if not retrieved_context:

        retrieved_context = (
            "No external verified knowledge "
            "was retrieved for this request."
        )


    # =====================================================
    # SPECIALIZED CAREER COUNSELING PROMPT
    # =====================================================

    prompt = f"""
You are CareerBot, a specialized AI Career Counseling Assistant.

Your primary purpose is to provide personalized, practical,
realistic and structured academic and career guidance for
university students.

You should behave as a professional career counselor rather
than a general-purpose chatbot.


============================================================
STUDENT PROFILE
============================================================

Student Name:
{name}

Current Education Level / Semester:
{education}

Expected Graduation Year:
{graduation_year}

Current Skills:
{current_skills}

Current Skill Level:
{skill_level}

Career Goal:
{career_goal}

Career Preference:
{career_preference}

Preferred Country:
{preferred_country}

Preferred City:
{preferred_city}

Additional Interests / Profile Information:
{interests}


============================================================
CAREERBOT INSTRUCTIONS
============================================================

1. Personalize every response using the student's profile.

2. Consider the student's:
   - education
   - current skills
   - skill level
   - career goal
   - career preference
   - preferred country and city, if provided

3. Avoid generic career advice when student information
   is already available.

4. Explain why a recommended career matches the student.

5. Identify the gap between the student's current skills
   and the skills required for the target career.

6. Give realistic and practical learning recommendations.

7. Recommend portfolio projects where appropriate.

8. Recommend certifications only when they are useful.

9. Include internship, job, freelancing or higher-study
   guidance depending on the student's selected preference.

10. Do not guarantee:
    - employment
    - salary
    - admission
    - visa approval
    - career success

11. Do not invent:
    - university fees
    - application deadlines
    - admission requirements
    - scholarship amounts

12. If current official information would be required,
    clearly tell the student to verify it from the
    official organization or university website.

13. Use clear professional Markdown.

14. Keep the answer focused and useful.

15. Do not unnecessarily repeat information.

16. For a follow-up question, answer the follow-up
    directly instead of recreating the complete roadmap.

17. Give advice appropriate to the student's current
    level rather than assuming advanced knowledge.


============================================================
FULL CAREER ROADMAP FORMAT
============================================================

When the student asks for a complete career roadmap,
use the following structure:

### 1. Career Assessment

Briefly analyze the student's:
- current education
- current skills
- career goal
- career preference


### 2. Top 3 Recommended Career Paths

For each career explain:

- Why it matches the student
- Main responsibilities
- Important skills
- Entry-level opportunities


### 3. Skill Gap Analysis

Clearly separate:

**Skills Already Available**

and

**Skills Still Required**


### 4. Technical Learning Roadmap

Give the student a logical learning sequence.

Use stages such as:

Beginner
→ Intermediate
→ Practical Projects
→ Internship
→ Job Ready


### 5. Portfolio Projects

Recommend practical projects the student can:

- build
- demonstrate
- add to a CV
- add to GitHub or portfolio


### 6. Certifications

Recommend relevant certifications only if they
would realistically help the student's career path.


### 7. Internship / Practical Experience Strategy

Explain how the student can gain practical experience.


### 8. Career Preference Strategy

The student's preferred direction is:

{career_preference}

Adapt the strategy accordingly.


### 9. 30-Day Action Plan

Give specific tasks for:

**Week 1**

**Week 2**

**Week 3**

**Week 4**


### 10. Long-Term Direction

Give a realistic target for approximately the next
6 to 12 months.


============================================================
PREVIOUS CONVERSATION
============================================================

{history_text}


============================================================
RETRIEVED VERIFIED KNOWLEDGE
============================================================

{retrieved_context}


============================================================
CURRENT STUDENT QUESTION
============================================================

{user_message}


Respond now as CareerBot.
"""


    return prompt


# =========================================================
# GEMINI ONLINE AI
# =========================================================

def generate_with_gemini(
    prompt,
    is_roadmap=False
):

    """
    Generates a CareerBot response using Google's
    Gemini API.

    This is CareerBot's PRIMARY online AI engine.
    """


    # -----------------------------------------------------
    # CHECK API KEY
    # -----------------------------------------------------

    if not GEMINI_API_KEY:

        raise RuntimeError(
            "GEMINI_API_KEY is missing from .env."
        )


    # -----------------------------------------------------
    # OUTPUT LENGTH
    # -----------------------------------------------------

    if is_roadmap:

        max_output_tokens = 1400

    else:

        max_output_tokens = 600


    # -----------------------------------------------------
    # GEMINI REQUEST PAYLOAD
    # -----------------------------------------------------

    payload = {

        "contents": [

            {

                "role":
                    "user",

                "parts": [

                    {

                        "text":
                            prompt
                    }

                ]
            }

        ],


        "generationConfig": {

            "temperature":
                0.4,

            "maxOutputTokens":
                max_output_tokens
        }
    }


    # -----------------------------------------------------
    # API HEADERS
    # -----------------------------------------------------

    headers = {

        "Content-Type":
            "application/json",

        "x-goog-api-key":
            GEMINI_API_KEY
    }


    # -----------------------------------------------------
    # TERMINAL STATUS
    # -----------------------------------------------------

    print()

    print(
        "--------------------------------------"
    )

    print(
        "CAREERBOT AI REQUEST"
    )

    print(
        "--------------------------------------"
    )

    print(
        "Trying ONLINE AI:",
        GEMINI_MODEL
    )


    # -----------------------------------------------------
    # SEND REQUEST
    # -----------------------------------------------------

    response = requests.post(

        GEMINI_API_URL,

        headers=headers,

        json=payload,

        timeout=(
            GEMINI_CONNECT_TIMEOUT,
            GEMINI_READ_TIMEOUT
        )
    )


    # Retry a temporary service overload once, then use the configured fallback.
    if response.status_code in (429, 500, 502, 503, 504):
        print("Gemini temporary HTTP error; retrying once:", response.status_code)
        time.sleep(1)
        response = requests.post(
            GEMINI_API_URL,
            headers=headers,
            json=payload,
            timeout=(GEMINI_CONNECT_TIMEOUT, GEMINI_READ_TIMEOUT)
        )

    # -----------------------------------------------------
    # CHECK HTTP STATUS
    # -----------------------------------------------------

    response.raise_for_status()


    # -----------------------------------------------------
    # CONVERT RESPONSE TO JSON
    # -----------------------------------------------------

    data = response.json()


    # -----------------------------------------------------
    # GET CANDIDATES
    # -----------------------------------------------------

    candidates = data.get(
        "candidates",
        []
    )


    if not candidates:

        prompt_feedback = data.get(
            "promptFeedback",
            {}
        )

        raise RuntimeError(
            "Gemini returned no response candidates. "
            f"Feedback: {prompt_feedback}"
        )


    # -----------------------------------------------------
    # GET CONTENT
    # -----------------------------------------------------

    content = candidates[0].get(
        "content",
        {}
    )


    parts = content.get(
        "parts",
        []
    )


    # -----------------------------------------------------
    # COLLECT TEXT PARTS
    # -----------------------------------------------------

    response_parts = []


    for part in parts:

        text = part.get(
            "text"
        )


        if text:

            response_parts.append(
                text
            )


    # -----------------------------------------------------
    # FINAL TEXT
    # -----------------------------------------------------

    ai_text = "\n".join(
        response_parts
    ).strip()


    if not ai_text:

        raise RuntimeError(
            "Gemini returned an empty response."
        )


    # -----------------------------------------------------
    # SUCCESS
    # -----------------------------------------------------

    print(
        "ONLINE AI RESPONSE SUCCESSFUL"
    )

    print(
        "Model:",
        GEMINI_MODEL
    )

    print(
        "--------------------------------------"
    )


    return ai_text


# =========================================================
# COMPACT LOCAL AI PROMPT
# =========================================================

def build_local_prompt(user_profile, conversation_history, user_message,
                       retrieved_context="", is_roadmap=False):
    """Retain the student context without sending the full Gemini prompt."""
    profile = user_profile or {}
    def value(key, default="Not provided", limit=200):
        return str(profile.get(key) or default)[:limit]

    education = value("current_education", profile.get("degree") or "Not provided")
    skills = value("current_skills", profile.get("interests") or "Not provided")
    preference = value("career_preference")
    location = value("preferred_city") + ", " + value("preferred_country")
    history = []
    for message in (conversation_history or [])[-4:]:
        role = message.get("role", "user")
        if role in ("user", "ai", "assistant"):
            label = "Student" if role == "user" else "CareerBot"
            content = str(message.get("content") or "")[:350]
            # Do not teach the model to repeat saved emergency templates.
            if role != "user" and "Emergency Offline Mode" in content:
                continue
            history.append(f"{label}: {content}")
    history_text = "\n".join(history) or "No previous messages."
    context = str(retrieved_context or "")[:600] or "No verified external data."

    if is_roadmap:
        if "stud" in preference.lower() or "master" in str(user_message).lower():
            task = (
                "Give a concise higher-study roadmap with 4 headings: "
                "Suitable master's fields; Skills and prerequisites; "
                "University search and application preparation; 30-day action plan. "
                "Prioritize the student's existing technical subject and location."
            )
        else:
            task = (
                "Give a concise roadmap with 4 headings: Career options; "
                "Skill gaps; Learning and practical projects; 30-day action plan. "
                "Adapt advice to the stated career preference."
            )
    else:
        task = "Answer the latest question directly. Do not repeat the full roadmap."

    return f"""You are CareerBot, an academic and career counselor for students.
Use the student's technical field, not unrelated industries. Give practical,
focused Markdown advice at the student's skill level. Do not invent universities,
fees, deadlines, eligibility, salaries or vacancies. Say when official verification
is required. No guarantees of admission, jobs or visas.

Student: {value("name", "Student")}
Education: {education}
Graduation year: {value("graduation_year")}
Skills: {skills}
Skill level: {value("skill_level")}
Goal: {value("career_goal")}
Preference: {preference}
Preferred location: {location}
Additional interests: {value("interests", "Not provided", 200)}
Recent conversation: {history_text}
Reference context: {context}
Current question: {str(user_message or "")[:1000]}

{task}
Keep the answer brief, specific and complete.
"""


# =========================================================
# OLLAMA OFFLINE AI
# =========================================================

def generate_with_ollama(
    prompt,
    is_roadmap=False
):

    """
    Generates a response using local Ollama.

    This function is automatically used if Gemini
    cannot provide a response.
    """


    # -----------------------------------------------------
    # OUTPUT LENGTH
    # -----------------------------------------------------

    if is_roadmap:

        max_tokens = 450

    else:

        max_tokens = 250


    # -----------------------------------------------------
    # OLLAMA REQUEST
    # -----------------------------------------------------

    payload = {

        "model":
            OLLAMA_MODEL,

        "prompt":
            prompt,

        "stream":
            False,

        "keep_alive":
            "60m",

        "options": {

            "temperature":
                0.3,

            "num_predict":
                max_tokens,

            "num_ctx":
                OLLAMA_CONTEXT_SIZE
        }
    }


    # -----------------------------------------------------
    # TERMINAL STATUS
    # -----------------------------------------------------

    print()

    print(
        "--------------------------------------"
    )

    print(
        "Switching to OFFLINE AI"
    )

    print(
        "Model:",
        OLLAMA_MODEL
    )

    print(
        "--------------------------------------"
    )


    # -----------------------------------------------------
    # SEND REQUEST
    # -----------------------------------------------------

    response = post_to_local_ollama(

        payload=payload,

        timeout=(
            OLLAMA_CONNECT_TIMEOUT,
            OLLAMA_READ_TIMEOUT
        )
    )


    # -----------------------------------------------------
    # CHECK STATUS
    # -----------------------------------------------------

    response.raise_for_status()


    # -----------------------------------------------------
    # READ RESPONSE
    # -----------------------------------------------------

    data = response.json()


    ai_text = data.get(
        "response",
        ""
    ).strip()


    if not ai_text:

        raise RuntimeError(
            "Ollama returned an empty response."
        )


    # -----------------------------------------------------
    # SUCCESS
    # -----------------------------------------------------

    print(
        "OFFLINE AI RESPONSE SUCCESSFUL"
    )

    print(
        "--------------------------------------"
    )


    return ai_text


# =========================================================
# BUILT-IN EMERGENCY FALLBACK
# =========================================================

def create_fallback_response(
    user_profile
):

    """
    Final CareerBot fallback.

    This is used only when:

    1. Gemini is unavailable
    AND
    2. Ollama is unavailable
    """


    name = (
        user_profile.get(
            "name"
        )
        or "Student"
    )


    education = (

        user_profile.get(
            "current_education"
        )

        or user_profile.get(
            "degree"
        )

        or "your current education"
    )


    current_skills = (

        user_profile.get(
            "current_skills"
        )

        or user_profile.get(
            "interests"
        )

        or "your current skills"
    )


    skill_level = (
        user_profile.get(
            "skill_level"
        )
        or "your current level"
    )


    career_goal = (
        user_profile.get(
            "career_goal"
        )
        or "your target career"
    )


    career_preference = (
        user_profile.get(
            "career_preference"
        )
        or "professional employment"
    )


    return f"""
### 🎯 Career Roadmap for {name}

CareerBot is currently operating in **Emergency Offline Mode**.

> This is a built-in template, not an AI-generated response.

Based on your **{education}** background, your current skills
(**{current_skills}**), current level (**{skill_level}**) and
career goal (**{career_goal}**), here is a practical starting plan.

### 1. Career Assessment

Your first step is to compare your current knowledge with the
skills required for **{career_goal}**.

### 2. Skill Development

Focus on:

- Core fundamentals of your chosen career
- Practical technical skills
- Problem solving
- Communication skills
- Industry tools relevant to your target role

### 3. Portfolio Development

Complete at least **2 to 3 practical projects**.

For every project document:

- Project objective
- Technologies used
- Implementation
- Problems solved
- Final result

Where appropriate, publish your work on GitHub or a portfolio.

### 4. Practical Experience

Look for:

- Internships
- University projects
- Entry-level opportunities
- Freelance projects
- Volunteer technical work

### 5. Career Preference

Your selected career preference is:

**{career_preference}**

Your learning and application strategy should be designed
around this direction.

### 6. 30-Day Action Plan

**Week 1:** Review fundamentals and identify your skill gaps.

**Week 2:** Begin one practical portfolio project.

**Week 3:** Improve the project and learn relevant industry tools.

**Week 4:** Update your CV, LinkedIn and portfolio and begin
researching relevant opportunities.

> CareerBot used its emergency fallback because no AI engine enabled
> in the selected mode could return a response.
"""


# =========================================================
# MAIN CAREERBOT AI FUNCTION
# =========================================================

def generate_ai_response(
    user_profile=None,
    conversation_history=None,
    user_message="",
    retrieved_context=""
):

    """
    CareerBot Hybrid AI Pipeline

    online_first: Gemini, then Ollama (original default).
    offline_first: Ollama, then Gemini.
    offline_only: Ollama only, no online API calls.
    Built-in emergency response is used if enabled engines fail.
    """


    # -----------------------------------------------------
    # DEFAULT VALUES
    # -----------------------------------------------------

    user_profile = (
        user_profile
        or {}
    )


    conversation_history = (
        conversation_history
        or []
    )


    user_message = (
        user_message
        or ""
    )


    # -----------------------------------------------------
    # BUILD SHARED CAREERBOT PROMPT
    # -----------------------------------------------------

    prompt = build_prompt(

        user_profile=(
            user_profile
        ),

        conversation_history=(
            conversation_history
        ),

        user_message=(
            user_message
        ),

        retrieved_context=(
            retrieved_context
        )
    )


    # -----------------------------------------------------
    # DETECT FULL ROADMAP REQUEST
    # -----------------------------------------------------

    user_message_lower = (
        user_message.lower()
    )


    roadmap_keywords = [

        "roadmap",

        "career plan",

        "career path",

        "complete plan",

        "learning plan"
    ]


    is_roadmap = any(

        keyword in user_message_lower

        for keyword in roadmap_keywords
    )


    # Build a compact prompt only for local inference. The original
    # detailed Gemini prompt above remains unchanged except for location.
    local_prompt = build_local_prompt(
        user_profile, conversation_history, user_message,
        retrieved_context, is_roadmap
    )

    if AI_MODE == "offline_only":
        providers = ("ollama",)
    elif AI_MODE == "offline_first":
        providers = ("ollama", "gemini")
    else:
        providers = ("gemini", "ollama")

    print("CAREERBOT AI MODE:", AI_MODE)
    for provider in providers:
        if provider == "gemini":
            # =====================================================
            # PRIORITY 1
            # TRY GEMINI ONLINE AI
            # =====================================================

            try:

                ai_text = (
                    generate_with_gemini(

                        prompt=prompt,

                        is_roadmap=is_roadmap
                    )
                )


                return ai_text


            # -----------------------------------------------------
            # GEMINI TIMEOUT
            # -----------------------------------------------------

            except requests.exceptions.Timeout:

                print()

                print(
                    "GEMINI STATUS:"
                )

                print(
                    "Gemini request timed out."
                )

                print(
                    "Trying another enabled AI engine, if available."
                )


            # -----------------------------------------------------
            # NO INTERNET
            # -----------------------------------------------------

            except requests.exceptions.ConnectionError:

                print()

                print(
                    "GEMINI STATUS:"
                )

                print(
                    "Internet connection unavailable."
                )

                print(
                    "Trying another enabled AI engine, if available."
                )


            # -----------------------------------------------------
            # GEMINI HTTP ERROR
            # -----------------------------------------------------

            except requests.exceptions.HTTPError as error:

                print()

                print(
                    "GEMINI API HTTP ERROR:"
                )

                print(
                    error
                )


                # Print Google's error message without
                # printing the API key.
                try:

                    error_data = (
                        error.response.json()
                    )


                    google_error = (
                        error_data.get(
                            "error",
                            {}
                        )
                    )


                    print(
                        "Google API message:",
                        google_error.get(
                            "message",
                            "No additional message."
                        )
                    )


                    print(
                        "Google API status:",
                        google_error.get(
                            "status",
                            "Unknown"
                        )
                    )


                except Exception:

                    pass


                print(
                    "Trying another enabled AI engine, if available."
                )


            # -----------------------------------------------------
            # OTHER GEMINI ERROR
            # -----------------------------------------------------

            except Exception as error:

                print()

                print(
                    "GEMINI API ERROR:"
                )

                print(
                    error
                )

                print(
                    "Trying another enabled AI engine, if available."
                )


        else:
            # =====================================================
            # PRIORITY 2
            # TRY LOCAL OLLAMA
            # =====================================================

            try:

                ai_text = (
                    generate_with_ollama(

                        prompt=local_prompt,

                        is_roadmap=is_roadmap
                    )
                )


                return ai_text


            # -----------------------------------------------------
            # OLLAMA TIMEOUT
            # -----------------------------------------------------

            except requests.exceptions.Timeout:

                print()

                print(
                    "OLLAMA STATUS:"
                )

                print(
                    "Local Ollama exceeded "
                    "the response time limit."
                )


            # -----------------------------------------------------
            # OLLAMA NOT RUNNING
            # -----------------------------------------------------

            except requests.exceptions.ConnectionError:

                print()

                print(
                    "OLLAMA STATUS:"
                )

                print(
                    "Local Ollama is not running."
                )


            # -----------------------------------------------------
            # OTHER OLLAMA ERROR
            # -----------------------------------------------------

            except Exception as error:

                print()

                print(
                    "OLLAMA ERROR:"
                )

                print(
                    error
                )


    # =====================================================
    # PRIORITY 3
    # EMERGENCY FALLBACK
    # =====================================================

    print()

    print(
        "--------------------------------------"
    )

    print(
        "NO ENABLED AI ENGINE RETURNED A RESPONSE"
    )

    print(
        "Using CareerBot emergency fallback."
    )

    print(
        "--------------------------------------"
    )


    if not is_roadmap:
        return (
            "### AI temporarily unavailable\n\n"
            "CareerBot could not generate a live answer. "
            "Please check the selected AI engine and try your question again."
        )

    return create_fallback_response(
        user_profile
    )