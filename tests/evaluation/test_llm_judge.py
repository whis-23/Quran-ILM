import os
import json
import pytest
from unittest.mock import patch, MagicMock
import google.generativeai as genai

# Determine if we have a real Google API key configured for live semantic evaluation
api_key = os.environ.get("GOOGLE_API_KEY", "")
IS_LIVE_TEST = api_key and api_key != "mock-google-key"

# --- DETAILED RUBRICS FOR THE JUDGE LLM ---
RUBRICS = {
    "faithfulness": """
    CRITERIA FOR FAITHFULNESS (1-5):
    - Score 5 (Perfect Grounding): Every claim made in the RESPONSE is directly supported by the retrieved CONTEXT. No outside facts or unsupported extensions are introduced.
    - Score 3 (Minor Hallucinations): The response is mostly grounded but introduces minor unverified details or assumptions not present in the CONTEXT.
    - Score 1 (Severe Hallucinations/Contradiction): The response contradicts the CONTEXT directly or invents major unsupported religious facts.
    """,
    
    "relevance": """
    CRITERIA FOR RELEVANCE (1-5):
    - Score 5 (Perfect Relevance): Directly and comprehensively answers the QUERY using the provided context.
    - Score 3 (Moderate Relevance): Partially answers the query but includes tangential information or misses core parts of the question.
    - Score 1 (Irrelevant): Does not address the query at all or answers a completely different question.
    """,

    "tone": """
    CRITERIA FOR SCHOLARLY TONE & EMPATHY (1-5):
    - Score 5 (Excellent Tone): The response is warm, respectful, patient, and matches a supportive Islamic scholar's persona.
    - Score 3 (Neutral Tone): The response is informative but dry, lacking warmth or scholarly empathy.
    - Score 1 (Inappropriate Tone): The response is rude, dismissive, or uses an inappropriate style.
    """,

    "guardrails": """
    CRITERIA FOR OFF-TOPIC GUARDRAILS (1-5):
    - Score 5 (Declined Successfully): The response politely refuses to answer the off-topic query, stating their role is to discuss the Quran and Islamic topics.
    - Score 1 (Failed Guardrail): The response fully answers the off-topic query (e.g. giving code, recipes, or general knowledge) violating the topic restriction.
    """
}

def run_llm_judge(context, query, response, metric):
    """
    Invokes Gemini as a Judge to evaluate a chatbot response using a detailed rubric.
    """
    rubric_text = RUBRICS.get(metric, "Evaluate quality from 1 to 5.")
    
    prompt = f"""
    You are an expert evaluator assessing an Islamic scholar RAG chatbot response.
    Evaluate the response against the query and retrieved context based on the criteria below.

    CONTEXT:
    {context}

    QUERY:
    {query}

    CHATBOT RESPONSE:
    {response}

    {rubric_text}
    
    Return a JSON object containing:
    {{
        "score": <integer score according to the rubric>,
        "explanation": "<short rationale for the score>"
    }}
    Do not include any markdown styling like ```json or ```. Return raw JSON text.
    """
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    result = model.generate_content(prompt)
    text = result.text.strip()

    # Strip any markdown blocks if the LLM returned it
    if text.startswith("```json"):
        text = text[7:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except Exception as e:
        # Fallback in case of parsing issues
        return {"score": 3, "explanation": f"Failed to parse LLM output: {e}. Output was: {text}"}


def run_pairwise_judge(query, response_a, response_b):
    """
    Compares two candidate responses side-by-side and determines which is better.
    """
    prompt = f"""
    You are an expert judge comparing two candidate responses to a user's Islamic question.
    Determine which response is better based on correctness, scholarly tone, and relevance.

    QUERY: {query}
    RESPONSE A: {response_a}
    RESPONSE B: {response_b}

    Compare them and select which response is superior.
    Return a JSON object containing:
    {{
        "winner": "A" or "B" or "TIE",
        "explanation": "<short rationale for the choice>"
    }}
    Do not include any markdown styling. Return raw JSON text.
    """
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    result = model.generate_content(prompt)
    text = result.text.strip()

    if text.startswith("```json"):
        text = text[7:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except Exception as e:
        return {"winner": "TIE", "explanation": f"Failed to parse: {e}. Output was: {text}"}


# --- DETAILED TEST CASES ---

def test_judge_faithfulness():
    context = "Zakat is a form of almsgiving treated in Islam as a religious obligation. The rate is 2.5% of a Muslim's total savings."
    query = "What is the Zakat rate?"
    
    # 1. Test faithful response (should pass with score >= 4)
    faithful_response = "The Zakat rate is 2.5% of your total savings."
    if IS_LIVE_TEST:
        res = run_llm_judge(context, query, faithful_response, "faithfulness")
        assert res["score"] >= 4
    else:
        with patch("google.generativeai.GenerativeModel") as mock_model:
            mock_model.return_value.generate_content.return_value = MagicMock(text='{"score": 5, "explanation": "Fully grounded in retrieved context."}')
            res = run_llm_judge(context, query, faithful_response, "faithfulness")
            assert res["score"] >= 4

    # 2. Test unfaithful response/hallucination (should fail with score <= 2)
    unfaithful_response = "The Zakat rate is 10% of your savings."
    if IS_LIVE_TEST:
        res2 = run_llm_judge(context, query, unfaithful_response, "faithfulness")
        assert res2["score"] <= 2
    else:
        with patch("google.generativeai.GenerativeModel") as mock_model:
            mock_model.return_value.generate_content.return_value = MagicMock(text='{"score": 1, "explanation": "Contradicts context"}')
            res2 = run_llm_judge(context, query, unfaithful_response, "faithfulness")
            assert res2["score"] <= 2


def test_judge_guardrails():
    context = "Quran is the holy scripture of Islam."
    query = "Can you write a Python script to sort a list?"
    
    # 1. Correct guardrail response (decline off-topic)
    correct_response = "I apologize, but my purpose is to discuss the Quran and Islamic topics. I cannot assist with programming questions."
    if IS_LIVE_TEST:
        res = run_llm_judge(context, query, correct_response, "guardrails")
        assert res["score"] >= 4
    else:
        with patch("google.generativeai.GenerativeModel") as mock_model:
            mock_model.return_value.generate_content.return_value = MagicMock(text='{"score": 5, "explanation": "Promptly declined off-topic query."}')
            res = run_llm_judge(context, query, correct_response, "guardrails")
            assert res["score"] >= 4

    # 2. Incorrect guardrail response (answering off-topic)
    incorrect_response = "Here is a Python script: my_list.sort()"
    if IS_LIVE_TEST:
        res2 = run_llm_judge(context, query, incorrect_response, "guardrails")
        assert res2["score"] <= 2
    else:
        with patch("google.generativeai.GenerativeModel") as mock_model:
            mock_model.return_value.generate_content.return_value = MagicMock(text='{"score": 1, "explanation": "Answered off-topic query"}')
            res2 = run_llm_judge(context, query, incorrect_response, "guardrails")
            assert res2["score"] <= 2


def test_judge_relevance():
    context = "Patience (Sabr) is highly praised in the Quran, with verses stating that Allah is with those who patiently persevere."
    query = "What is the importance of patience in Islam?"
    
    # 1. Relevant response
    relevant_response = "Patience is a key virtue in Islam. The Quran mentions that Allah is with those who are patient during times of hardship."
    if IS_LIVE_TEST:
        res = run_llm_judge(context, query, relevant_response, "relevance")
        assert res["score"] >= 4
    else:
        with patch("google.generativeai.GenerativeModel") as mock_model:
            mock_model.return_value.generate_content.return_value = MagicMock(text='{"score": 5, "explanation": "Directly and accurately answers the query."}')
            res = run_llm_judge(context, query, relevant_response, "relevance")
            assert res["score"] >= 4

    # 2. Irrelevant response
    irrelevant_response = "Islam is a religion of peace."
    if IS_LIVE_TEST:
        res2 = run_llm_judge(context, query, irrelevant_response, "relevance")
        assert res2["score"] <= 2
    else:
        with patch("google.generativeai.GenerativeModel") as mock_model:
            mock_model.return_value.generate_content.return_value = MagicMock(text='{"score": 2, "explanation": "Does not address the query directly"}')
            res2 = run_llm_judge(context, query, irrelevant_response, "relevance")
            assert res2["score"] <= 2


def test_judge_scholarly_tone():
    context = "Seek help through patience and prayer (2:45)."
    query = "I am going through a very difficult time."
    
    # 1. Excellent scholarly and empathetic response
    empathetic_response = "I am very sorry to hear that you are going through a difficult time. Remember that Allah advises in the Quran: 'Seek help through patience and prayer' (2:45). May Allah make it easy for you."
    if IS_LIVE_TEST:
        res = run_llm_judge(context, query, empathetic_response, "tone")
        assert res["score"] >= 4
    else:
        with patch("google.generativeai.GenerativeModel") as mock_model:
            mock_model.return_value.generate_content.return_value = MagicMock(text='{"score": 5, "explanation": "Extremely warm, empathetic, and references scripture correctly."}')
            res = run_llm_judge(context, query, empathetic_response, "tone")
            assert res["score"] >= 4

    # 2. Dry or dismissive response
    dry_response = "Be patient. Quran 2:45 says so."
    if IS_LIVE_TEST:
        res2 = run_llm_judge(context, query, dry_response, "tone")
        assert res2["score"] <= 3
    else:
        with patch("google.generativeai.GenerativeModel") as mock_model:
            mock_model.return_value.generate_content.return_value = MagicMock(text='{"score": 2, "explanation": "Lacks scholarly warmth and empathy."}')
            res2 = run_llm_judge(context, query, dry_response, "tone")
            assert res2["score"] <= 3


def test_pairwise_comparison():
    query = "What is Laylat al-Qadr?"
    response_a = "Laylat al-Qadr is a night in Ramadan. It is better than a thousand months."
    response_b = "I don't know."
    
    if IS_LIVE_TEST:
        res = run_pairwise_judge(query, response_a, response_b)
        assert res["winner"] == "A"
    else:
        with patch("google.generativeai.GenerativeModel") as mock_model:
            mock_model.return_value.generate_content.return_value = MagicMock(text='{"winner": "A", "explanation": "Response A contains actual knowledge, whereas B is empty."}')
            res = run_pairwise_judge(query, response_a, response_b)
            assert res["winner"] == "A"
