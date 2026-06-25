Markdown
# Engineering Specification: Wearable Insights PoC (Phase 1)

This document serves as the complete, definitive technical specification for an autonomous LLM developer agent or engineering team to implement Phase 1 of the Wearable Insights Translation Engine.

---

## 1. System Topology & Data Flow

The system operates as a stateless, single-pass pipeline execution. It avoids complex database overhead by consuming point-in-time snapshot files and outputting a structured payload.


+-------------------------+ +-------------------------+ +-------------------------+
| Mock Data Generator | ---> | Comparison Engine | ---> | LLM Inference Layer |
| (Creates 30-Day History | | (Computes Baselines & | | (Applies Causal & |
| + Current Target) | | Semantic Variances) | | Actionable Framework) |
+-------------------------+ +-------------------------+ +-------------------------+
|
v
+-------------------------+
| Structured Markdown |
| Insight Output |
+-------------------------+

---

## 2. Component Specifications

### Step 1: Mock Data Generator (`mock_generator.py`)
This component synthesizes data profiles representing distinct lifestyle anomalies. It outputs a single JSON payload containing a 30-day historical baseline context alongside a highly specific "Current Day" anomaly.

#### Target Anomaly Profile: *The High-Stress/Sedentary Recovery Deficit*
*   **Historical Baseline:** High daily steps (8k–10k), low-to-moderate stress scores (30–40), high sleep scores (75–85), and high sleep HRV (50–60ms).
*   **Current Target Day:** Critically low steps (2,200), high daytime stress (78), dropped sleep score (61), and crashed nightly HRV (28ms).

```json
{
  "user_metadata": {
    "user_id": "usr_2026_dev_01",
    "age": 34,
    "gender": "Non-specified"
  },
  "current_day_metrics": {
    "date": "2026-06-17",
    "sleep": {
      "sleep_score": 61,
      "total_sleep_minutes": 340,
      "deep_sleep_minutes": 35,
      "rem_sleep_minutes": 40
    },
    "cardio_stress": {
      "average_stress_score": 78,
      "resting_heart_rate": 72,
      "nightly_hrv_rmssd_ms": 28
    },
    "activity": {
      "step_count": 2200,
      "active_minutes": 10
    }
  },
  "historical_30_day_averages": {
    "sleep_score_avg": 79,
    "total_sleep_minutes_avg": 460,
    "deep_sleep_minutes_avg": 78,
    "rem_sleep_minutes_avg": 85,
    "average_stress_score_avg": 36,
    "resting_heart_rate_avg": 62,
    "nightly_hrv_rmssd_ms_avg": 54,
    "step_count_avg": 8800,
    "active_minutes_avg": 45
  }
}
```

#### Step 2: Comparison & Analytics Engine (analytics_engine.py)
This Python module ingests the raw mock JSON, evaluates relative performance, and generates a structured intermediate context payload (llm_input_context.json).
Instead of relying on the LLM to calculate differences, the script applies the following logic:
```
$$\text{Percentage Variance} = \frac{\text{Current Value} - \text{Historical Average}}{\text{Historical Average}} \times 100$$
Categorization Rules:
$\text{Variance} > +15\% \implies$ "Significantly Elevated"
$\text{Variance} < -15\% \implies$ "Significantly Depressed"
$-15\% \le \text{Variance} \le +15\% \implies$ "Stable / Within Normal Baseline"
Generated Intermediate Payload Output:
JSON
{
  "analysis_date": "2026-06-17",
  "evaluated_metrics": {
    "sleep_quality": {
      "current_value": "61 points",
      "baseline_value": "79 points",
      "percentage_change": "-22.7%",
      "evaluation_tag": "Significantly Depressed"
    },
    "sleep_architecture_deep": {
      "current_value": "35 mins",
      "baseline_value": "78 mins",
      "percentage_change": "-55.1%",
      "evaluation_tag": "Critically Depressed"
    },
    "cardiovascular_stress_load": {
      "current_value": "78 points",
      "baseline_value": "36 points",
      "percentage_change": "+116.6%",
      "evaluation_tag": "Significantly Elevated"
    },
    "autonomic_recovery_hrv": {
      "current_value": "28 ms",
      "baseline_value": "54 ms",
      "percentage_change": "-48.1%",
      "evaluation_tag": "Significantly Depressed"
    },
    "physical_exertion_steps": {
      "current_value": "2200 steps",
      "baseline_value": "8800 steps",
      "percentage_change": "-75.0%",
      "evaluation_tag": "Significantly Depressed"
    }
  }
}
```

#### Step 3: Prompt Engineering Framework & Inference
The generated context JSON is embedded directly into the prompt template. The system prompt enforces strict rules to prevent boring, math-heavy echoes and encourage practical, physiological coaching narratives.
Python
import os
from openai import OpenAI

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


def generate_wearable_insight(context_json_string):
    system_prompt = """You are a world-class human performance coach and digital health translation engine. 
Your single task is to translate cold, uninterpretable wearable metrics into an empathetic, physiologically coherent, and highly actionable diagnostic summary.

CRITICAL EXECUTION RULES:
1. NEVER output statements that merely echo raw calculations (e.g., DO NOT say: "Your sleep score dropped by 22.7% or is 61"). The user already knows their scores.
2. ALWAYS build a physiological narrative linking the metrics dynamically. Use your knowledge of human biology to explain the 'WHY' behind the data (e.g., connect low activity or high stress directly to poor deep sleep architecture and suppressed HRV).
3. EXPLICITLY frame feedback around the interdependency of sleep, autonomic nervous system stress (HRV), and physical exertion.
4. ABSOLUTELY FORBIDDEN: Do not offer formal medical diagnoses, do not mention clinical pathology, and do not tell the user to seek emergency medical attention unless an extreme anomaly is present. Keep it focused entirely on daily lifestyle optimizations.
5. Every single insight MUST conclude with exactly ONE highly explicit, physically actionable directive for the current day.

### IN-CONTEXT EXAMPLES FOR FORMAT AND TONE ###

[GOOD EXAMPLE]
"Your body is showing signs of an recovery deficit today. Last night's marked drop in your deep sleep duration and nightly Heart Rate Variability (HRV) is heavily tied to the elevated stress load your nervous system carried throughout the day. Because physical movement acts as a primary decompression valve for cognitive stress, your exceptionally low step count yesterday left your sympathetic nervous system ('fight-or-flight') highly active when your head hit the pillow, preventing your body from transitioning smoothly into restorative deep sleep cycles.
👉 To bounce back today: Dedicate 15 minutes to a brisk, continuous outdoor walk before sunset to burn off lingering stress hormones, then commit to a completely screen-free wind-down routine 45 minutes before sleep."

[BAD EXAMPLE]
"Your sleep score was 61 points yesterday which is Significantly Depressed compared to your baseline of 79 points. Your cardiovascular stress load was 78 points which is 116.6% higher than normal. Your physical exertion steps were down 75%. You need to sleep more and stress less."

### TARGET RUN DATA CONTEXT ###
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        temperature=0.4,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Analyze this user payload and generate the insight:\n{context_json_string}",
            },
        ],
    )

    return response.choices[0].message.content

3. Reference Implementation Blueprint (The Agent Checklist)
An LLM agent can execute this step-by-step checklist to build the working prototype application.
Phase 1 Execution Verification Routine
[ ] Task 1: Script Creation — Write mock_generator.py to create the target anomaly JSON payload file locally as raw_mock_wearable.json.
[ ] Task 2: Analytics Preprocessing — Write analytics_engine.py to ingest raw_mock_wearable.json, calculate percentage variances, apply the text assessment tags, and save the result as processed_context.json.
[ ] Task 3: Client Wrapper Implementation — Write inference_orchestrator.py to load the processed_context.json, construct the system prompt payload, call the LLM API endpoint, and format the output.
[ ] Task 4: Interface Rendering — Create a minimalist execution dashboard (app.py via a terminal CLI printout or a single-page Streamlit view) displaying the final formatted Markdown insight string alongside the input metric tags.
4. Expected Production Output Format
When the pipeline runs successfully, the final output delivered to the user UI will match this clean structure:
Your Body's Daily Performance Narrative
Your nervous system is currently operating in a recovery deficit. The notable drop in your deep sleep duration and nightly Heart Rate Variability (HRV) is a direct reflection of a highly elevated daytime stress load that your body failed to fully process.
Because physical movement acts as a natural offset to mental stress, yesterday’s highly sedentary pattern trapped your body in a sympathetic ('fight-or-flight') state. Without adequate physical exertion to expend this systemic tension, your heart rate remained elevated, cutting your restorative deep sleep window nearly in half.
Your Clear Action Step for Today:
The Fix: Schedule a mandatory 20-minute brisk walk outside during lunch or before 6:00 PM to lower cortisol levels, and avoid any caloric intake or blue-screen exposure for a full two hours before bed to give your HRV a chance to recover.
5. Architectural Sandbox for Future Phases
------------- END OF PHASE 1 SPECIFICATION -------------
To keep future iterations organized, do not modify the core components of this Phase 1 architecture. Instead, plan to extend them through modular layers:
Phase 2 Retrieval-Augmented Generation (RAG): Introduce a vector database containing parsed clinical and behavioral textbooks (e.g., sleep hygiene protocols, athletic recovery journals). The intermediate analytics payload will be converted into semantic search queries to pull precise, evidence-based recommendations into the prompt.
Phase 3 Native Sensor Direct API Integrations: Swap out the mock_generator.py component for direct OAuth2 integrations pointing directly to the web endpoints of providers like Apple HealthKit via Health Connect or the Oura Web API, mapping live cloud data directly into the established comparison schemas.

---

# Wearable Insights POC - Engineering Specification

## Document Information

| Field        | Value                                                                               |
| ------------ | ----------------------------------------------------------------------------------- |
| Project      | Wearable Insights POC                                                               |
| Version      | 1.0                                                                                 |
| Objective    | Demonstrate generation of interpretable and actionable insights from wearable data  |
| Phase        | MVP / POC                                                                           |
| Timeline     | 1-2 weeks                                                                           |
| Primary Goal | Validate end-to-end pipeline from wearable data ingestion to LLM-generated insights |

---

# 1. Problem Statement

Current wearable devices provide users with numerous scores and metrics such as:

* Sleep Score
* Stress Score
* Heart Rate
* Heart Rate Variability (HRV)
* SpO₂
* Activity Metrics
* Recovery Scores

While these metrics are useful, they are often not interpretable by end users and do not clearly indicate what actions should be taken.

The objective of this POC is to build a system that converts wearable metrics into understandable, actionable insights using trend analysis and Large Language Models.

Example:

Instead of:

> Your sleep score today is 65.

The system should generate:

> Your sleep quality has been consistently below your monthly baseline for the past week. This coincides with reduced daily activity levels and later bedtimes. Increasing daytime activity and maintaining a more consistent sleep schedule may help improve sleep quality.

---

# 2. Success Criteria

The POC is successful if it demonstrates:

1. Wearable data ingestion.
2. Historical trend computation.
3. Baseline comparison generation.
4. Structured interpretation generation.
5. User-friendly actionable insights.

The objective is not medical accuracy.

The objective is to demonstrate the feasibility of transforming wearable data into interpretable user guidance.

---

# 3. Scope

## Included

### Sleep Profiling

* Sleep duration
* Sleep score
* Sleep stages
* Sleep consistency
* Bedtime variability

### Heart Health / Recovery

* Resting heart rate
* Average heart rate
* HRV
* Stress score

### Lifestyle Context

* Steps
* Active minutes

### LLM Insight Generation

* Trend interpretation
* Comparative insights
* Action suggestions

---

## Excluded

### Phase 1

* Raw PPG processing
* ECG signal analysis
* Clinical recommendations
* Disease prediction
* RAG
* Personalized physiology models
* Multi-user population analytics
* Real-time streaming

---

# 4. High-Level Architecture

```text
Wearable Data
      |
      v
Data Ingestion Layer
      |
      v
Normalization Layer
      |
      v
Feature Engineering Layer
      |
      v
Trend & Baseline Engine
      |
      v
Comparison JSON Builder
      |
      v
LLM Insight Generator
      |
      v
User Insights
```

---

# 5. System Components

## Component 1: Data Ingestion

### Responsibility

Load wearable summary data.

### Initial Sources

#### Synthetic Data Generator

Primary source for MVP.

#### CSV Upload

Support importing:

```csv
date,sleep_duration,sleep_score,deep_sleep,rem_sleep,resting_hr,hrv,stress_score,steps
```

### Output

Canonical daily records.

---

## Component 2: Data Normalization

### Responsibility

Convert incoming data into a unified schema.

### Canonical Schema

```json
{
  "user_id": "user_001",
  "date": "2026-06-17",
  "sleep_duration_minutes": 420,
  "sleep_score": 72,
  "deep_sleep_minutes": 65,
  "rem_sleep_minutes": 80,
  "resting_hr": 63,
  "hrv": 42,
  "stress_score": 55,
  "steps": 8500,
  "active_minutes": 55
}
```

### Requirements

* Handle missing values
* Validate numeric ranges
* Store units consistently

---

## Component 3: Feature Engineering

### Responsibility

Generate derived metrics.

---

## Sleep Features

### Inputs

* Sleep duration
* Sleep stages
* Bedtime

### Derived Features

```python
sleep_duration_delta
sleep_score_delta
deep_sleep_delta
rem_sleep_delta
sleep_consistency_score
bedtime_shift
```

---

## Recovery Features

### Inputs

* Resting HR
* HRV
* Stress Score

### Derived Features

```python
resting_hr_delta
hrv_delta
stress_delta
```

---

## Activity Features

### Inputs

* Steps
* Active minutes

### Derived Features

```python
activity_delta
step_delta
```

---

# 6. Trend Engine

## Responsibility

Create user baselines.

---

## Baselines

### Daily

Current value.

### 7-Day Baseline

```python
mean(last_7_days)
```

### 30-Day Baseline

```python
mean(last_30_days)
```

### Weekday Baseline

Example:

Compare today's Tuesday with historical Tuesdays.

---

## Trend Detection

Supported labels:

```json
[
  "up",
  "down",
  "stable"
]
```

Example:

```json
{
  "sleep_duration_trend": "down",
  "stress_trend": "up"
}
```

---

# 7. Comparison Engine

## Responsibility

Create a structured summary for the LLM.

The LLM should never receive raw tables.

It should receive a compact comparison object.

---

## Output Schema

```json
{
  "sleep": {},
  "heart_health": {},
  "activity": {},
  "candidate_associations": []
}
```

---

## Sleep Section Example

```json
{
  "current_day": {
    "sleep_duration": 360,
    "sleep_score": 65
  },
  "baseline_7d": {
    "sleep_duration": 430,
    "sleep_score": 72
  },
  "baseline_30d": {
    "sleep_duration": 450,
    "sleep_score": 75
  },
  "deviation": {
    "sleep_duration": -70,
    "sleep_score": -10
  },
  "flags": [
    "below_baseline_sleep",
    "reduced_sleep_score"
  ]
}
```

---

# 8. Candidate Association Generator

## Responsibility

Generate simple relationships between metrics.

These are not causal.

These are hypothesis candidates.

---

## Rules

### Rule 1

```text
Sleep ↓
Stress ↑
```

Generate:

```json
{
  "relation": "poor_sleep_and_higher_stress_co_occur"
}
```

---

### Rule 2

```text
Steps ↓
Sleep ↓
```

Generate:

```json
{
  "relation": "lower_activity_and_lower_sleep_co_occur"
}
```

---

### Rule 3

```text
HRV ↓
Stress ↑
```

Generate:

```json
{
  "relation": "reduced_recovery_and_higher_stress_co_occur"
}
```

---

## Important

The system should never claim causation.

Only associations.

---

# 9. LLM Insight Generation

## Responsibility

Translate structured comparisons into actionable insights.

The LLM is an interpreter.

It is not responsible for analysis.

Analysis must happen before LLM invocation.

---

## Input

Comparison JSON.

---

## Output

```json
{
  "insights": [
    {
      "title": "",
      "summary": "",
      "action": "",
      "confidence": ""
    }
  ]
}
```

---

# 10. LLM Prompt Specification

## System Prompt

```text
You are a wearable insights assistant.

You receive structured trend summaries.

Your job is to convert them into actionable,
easy-to-understand observations.

Rules:

1. Use only provided data.
2. Never diagnose medical conditions.
3. Never claim causation.
4. Prefer:
   - may be associated with
   - could be linked to
   - appears related to

5. Explain:
   - what changed
   - why it may matter
   - one action the user can try

6. Keep insights concise.

7. Return valid JSON only.
```

---

# 11. Synthetic Data Generator

## Goal

Provide realistic demo data.

---

## Profiles

### Profile A

Healthy Consistent Sleeper

Characteristics:

```text
Sleep: Stable
Stress: Low
HRV: Stable
```

---

### Profile B

Poor Sleep Week

Characteristics:

```text
Sleep duration decreases
Stress increases
HRV decreases
```

---

### Profile C

Low Activity User

Characteristics:

```text
Low steps
Late bedtime
Reduced sleep quality
```

---

### Profile D

Recovery Decline

Characteristics:

```text
Resting HR increases
HRV decreases
Stress increases
```

---

## Duration

Generate:

```text
90 days
```

per profile.

---

# 12. API Specification

## POST /ingest

### Input

```json
{
  "records": [...]
}
```

### Output

```json
{
  "status": "success"
}
```

---

## POST /generate-insights

### Input

```json
{
  "user_id": "user_001",
  "analysis_date": "2026-06-17"
}
```

### Output

```json
{
  "insights": [...]
}
```

---

## GET /comparison-json

Returns generated comparison object.

Useful for debugging and evaluation.

---

# 13. Frontend Requirements

## Dashboard Sections

### Trend Cards

Display:

* Sleep Duration
* Sleep Score
* HRV
* Stress
* Resting HR

---

### Insight Cards

Display:

```text
Title

Summary

Suggested Action
```

---

### Explanation Section

Display:

```text
Generated from:
- Sleep trend
- Activity trend
- Stress trend
```

This improves trust and explainability.

---

# 14. Evaluation Plan

## Technical Validation

Verify:

* Ingestion works
* Feature generation works
* Trend computation works
* JSON generation works
* LLM output schema is valid

---

## Product Validation

Ask reviewers:

### Question 1

Would you rather see:

```text
Sleep Score = 65
```

or

```text
Your sleep quality has been below your
usual baseline for the past week.
```

### Question 2

Did the insight suggest a useful action?

### Question 3

Did the insight feel personalized?

---

# 15. Future Extensions

## Phase 2

### Additional Signals

* SpO₂
* Temperature
* Respiration Rate

### Better Reasoning

* Physiological rule engine
* RAG knowledge base
* Personalized recovery models

### Advanced Analytics

* Seasonal trends
* Behavioral clustering
* Recovery forecasting
* Sleep optimization recommendations

---

# 16. Deliverables

## Deliverable 1

Synthetic wearable dataset.

## Deliverable 2

Trend computation pipeline.

## Deliverable 3

Comparison JSON generator.

## Deliverable 4

LLM insight generation service.

## Deliverable 5

Simple dashboard demonstrating end-to-end functionality.

---

# MVP Definition

The MVP is complete when:

1. Synthetic wearable data can be loaded.
2. Trends can be calculated.
3. Comparisons against baseline can be generated.
4. LLM can generate actionable insights.
5. A dashboard displays trends and insights.

At that point the core hypothesis is validated:

> Wearable metrics can be transformed into interpretable and actionable insights using a trend-analysis layer and an LLM-based explanation layer.
