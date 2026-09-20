# 🤖 AI Resume Screening Agent

> **An AI-powered resume screening and ranking system that transforms a job description into an explainable candidate evaluation pipeline.**

The **AI Resume Screening Agent** is an end-to-end recruitment intelligence system designed to automate the initial resume screening process.

Instead of simply generating a score, the system converts a **Job Description → Evaluation Rubric → Resume Analysis → Candidate Ranking → Explainable Results → CSV Export** pipeline into a structured workflow.

The goal is to make resume screening **faster, structured, evidence-based, and explainable**.

---

## ✨ What Does It Do?

A recruiter starts by providing a **Job Description**.

The system then:

```text
                ┌─────────────────────┐
                │   Job Description   │
                └──────────┬──────────┘
                           ↓
                ┌─────────────────────┐
                │   AI Rubric         │
                │   Generation        │
                └──────────┬──────────┘
                           ↓
                ┌─────────────────────┐
                │ Editable Evaluation │
                │      Criteria       │
                └──────────┬──────────┘
                           ↓
                ┌─────────────────────┐
                │   Resume Upload     │
                │   Multiple PDFs     │
                └──────────┬──────────┘
                           ↓
                ┌─────────────────────┐
                │ Resume Scoring      │
                │ & Analysis          │
                └──────────┬──────────┘
                           ↓
                ┌─────────────────────┐
                │ Candidate Rankings  │
                └──────────┬──────────┘
                           ↓
                ┌─────────────────────┐
                │ Explainable Results │
                └──────────┬──────────┘
                           ↓
                ┌─────────────────────┐
                │    CSV Export       │
                └─────────────────────┘
```

---

# 🎯 Project Objective

Traditional resume screening can become repetitive and difficult to scale when recruiters have to evaluate a large number of applications.

This project explores how an AI-based system can assist with the **first stage of candidate screening** by:

* Automatically creating evaluation criteria from a job description
* Allowing recruiters to modify those criteria
* Processing multiple resumes
* Evaluating candidates against the same rubric
* Providing criterion-level explanations
* Ranking candidates
* Exporting the results for further analysis

The system is designed around **structured evaluation rather than a simple AI-generated recommendation**.

---

# 🧩 Core Workflow

## 1️⃣ Job Description

The recruiter enters information about the role.

Example:

```text
Job Title:
AI Professional

Job Description:
We are looking for an AI professional who can design,
develop, and implement AI/ML solutions using modern
technologies such as LLMs, RAG, NLP, and machine learning.
```

The system uses this information as the foundation for candidate evaluation.

---

## 2️⃣ AI-Generated Evaluation Rubric

The system converts the job requirements into structured evaluation criteria.

Instead of asking:

> "Is this candidate good?"

the system evaluates candidates across defined dimensions.

For example:

```text
AI / ML Knowledge
NLP Skills
LLM Experience
RAG Experience
Project Experience
Model Optimization
```

Each criterion can then be reviewed and edited before resumes are processed.

This creates a consistent evaluation framework for all candidates.

---

## 3️⃣ Editable Rubric

The generated rubric is not treated as a fixed black box.

The recruiter can review and modify the criteria before continuing.

This allows the screening process to reflect the actual requirements of the role.

### Why this matters

A job description may contain requirements that need clarification or different weighting.

Giving the recruiter control over the rubric makes the system more practical than completely automatic screening.

---

# 📄 4️⃣ Bulk Resume Upload

The application supports uploading **multiple PDF resumes at once**.

```text
Resume_01.pdf
Resume_02.pdf
Resume_03.pdf
Resume_04.pdf
       ↓
   AI Processing
       ↓
Candidate Results
```

The frontend sends the resumes to the backend through the resume-processing API.

Each file is processed independently, allowing successful and failed files to be identified separately.

For example:

```text
Processed: 10 resumes

✓ 8 succeeded
✗ 2 failed
```

Failed files expose their individual error messages instead of silently disappearing.

---

# 🧠 5️⃣ Resume Scoring

Each resume is evaluated against the same generated rubric.

The system produces:

* Overall score
* Candidate summary
* Criterion-level scores
* Evidence-based justification

A simplified result looks like:

```text
Candidate: Resume_01.pdf

Total Score: 8.4 / 10

Summary:
Strong AI/ML background with relevant project experience.

Criteria:

AI/ML Knowledge
8/10
Strong evidence of practical AI/ML experience.

NLP Skills
9/10
Relevant NLP projects and technologies identified.

Model Optimization
1/10
No evidence found.
```

### Evidence over assumptions

One important design principle is that the system should not artificially inflate scores when a resume does not contain supporting evidence.

For example:

```text
Criterion: Model Optimization

Score: 1/10

Reason:
No evidence found.
```

This makes the evaluation more transparent and easier to inspect.

---

# 🏆 6️⃣ Candidate Rankings

After processing the resumes, candidates are ranked according to their total scores.

The ranking interface provides an expandable view for each candidate.

```text
#1  Candidate_A.pdf — 8.7/10
    └── Summary
    └── Criteria Breakdown
          ├── AI/ML Knowledge
          ├── NLP Skills
          ├── LLM Experience
          └── Project Experience

#2  Candidate_B.pdf — 8.1/10
    └── Summary
    └── Criteria Breakdown

#3  Candidate_C.pdf — 7.5/10
    └── Summary
    └── Criteria Breakdown
```

This allows recruiters to move from a high-level ranking into the reasoning behind an individual candidate's score.

---

# 📊 Explainable Evaluation

A major part of the project is making the results **inspectable**.

Instead of producing only:

```text
Candidate Score: 8.7
```

the system exposes:

```text
Candidate Score: 8.7

Why?

AI/ML Knowledge
8/10
→ Evidence found in relevant projects and experience.

NLP
9/10
→ Relevant NLP work identified.

Model Optimization
1/10
→ No supporting evidence found.
```

This creates a path from:

**Score → Criterion → Evidence / Justification**

rather than treating the AI output as an unexplained decision.

---

# 📥 CSV Export

The completed screening results can be exported as a CSV file.

The exported structure contains information such as:

| Candidate | Total Score | Summary              | Criterion Score |
| --------- | ----------: | -------------------- | --------------: |
| Resume A  |         8.7 | Strong AI background |               9 |
| Resume B  |         8.1 | Relevant experience  |               8 |
| Resume C  |         7.5 | Moderate match       |               7 |

Each criterion score becomes its own column, making the exported data easier to:

* Sort
* Filter
* Analyze
* Open in Excel
* Use for further research

The CSV is generated directly from the ranking data in the application.

---

# 🏗️ System Architecture

At a high level, the project follows a frontend → API → AI processing → results architecture.

```text
                         USER
                           │
                           ▼
                ┌───────────────────┐
                │ Streamlit Frontend│
                └─────────┬─────────┘
                          │
                          ▼
                ┌───────────────────┐
                │     Backend API   │
                └─────────┬─────────┘
                          │
             ┌────────────┴────────────┐
             ▼                         ▼
     ┌─────────────────┐       ┌─────────────────┐
     │ Rubric Creation │       │ Resume Processing│
     └────────┬────────┘       └────────┬────────┘
              │                         │
              └────────────┬────────────┘
                           ▼
                 ┌──────────────────┐
                 │ AI Evaluation    │
                 └────────┬─────────┘
                          ▼
                 ┌──────────────────┐
                 │ Candidate Scores │
                 │ & Explanations   │
                 └────────┬─────────┘
                          ▼
                 ┌──────────────────┐
                 │ Rankings + CSV   │
                 └──────────────────┘
```

---

# 🖥️ User Flow

The complete implemented flow through Phase 6 is:

```text
START
  │
  ▼
Create Job Description
  │
  ▼
Generate Rubric
  │
  ▼
Review / Edit Rubric
  │
  ▼
Upload Multiple Resumes
  │
  ▼
Process Resumes
  │
  ▼
View Success / Failure Status
  │
  ▼
Generate Candidate Rankings
  │
  ▼
Expand Candidate
  │
  ├── Summary
  ├── Total Score
  └── Criterion Breakdown
  │
  ▼
Download CSV
  │
  ▼
END
```

---

# 🛠️ Technology Stack

| Layer             | Technology           |
| ----------------- | -------------------- |
| Frontend          | Streamlit            |
| Backend           | Python API           |
| AI Layer          | LLM-based evaluation |
| Resume Input      | PDF                  |
| Data Processing   | Pandas               |
| API Communication | HTTP / Requests      |
| Export            | CSV                  |

---

# 📁 Project Structure

A simplified representation of the project:

```text
AI-Resume-Screening-Agent/
│
├── frontend/
│   └── app.py
│
├── backend/
│   └── ...
│
├── tests/
│   └── ...
│
├── resumes/
│   └── ...
│
├── README.md
└── requirements.txt
```

> The exact backend structure can evolve as additional modules are introduced.

---

# 🧪 Current Project Status

### Phase 1 — Foundation

* [x] Job description input
* [x] Initial project pipeline

### Phase 2 — AI Rubric Generation

* [x] Generate evaluation criteria from job description
* [x] Structured evaluation approach

### Phase 3 — Rubric Editing

* [x] Display generated rubric
* [x] Allow recruiter modifications
* [x] Maintain consistent rubric usage during screening

### Phase 4 — Resume Processing

* [x] PDF resume upload
* [x] Multiple resume upload
* [x] API-based resume processing
* [x] Per-resume success/failure handling

### Phase 5 — Candidate Ranking

* [x] Candidate scoring
* [x] Overall ranking
* [x] Expandable candidate results
* [x] Criterion-level score breakdown
* [x] Candidate summaries
* [x] Justifications

### Phase 6 — Export & Usability

* [x] CSV generation
* [x] Downloadable ranking results
* [x] Flat tabular export for analysis

---

# 🔍 What Makes This Project Different?

This project is not designed as simply:

```text
Resume → LLM → Score
```

Instead, it follows a structured pipeline:

```text
Job Description
       ↓
Evaluation Rubric
       ↓
Human Review
       ↓
Resume Processing
       ↓
Criterion-Based Evaluation
       ↓
Evidence / Justification
       ↓
Ranking
       ↓
Exportable Results
```

This separation makes the screening process easier to understand, inspect, and extend.

---

# 📌 Design Principles

### 1. Structured Evaluation

Candidates are evaluated against explicit criteria instead of an undefined overall prompt.

### 2. Consistency

The same rubric is reused across candidates so that evaluations remain comparable.

### 3. Explainability

Scores are accompanied by summaries and criterion-level justifications.

### 4. Evidence-Based Scoring

When supporting evidence is missing from a resume, the system should not assume that the candidate possesses the skill.

### 5. Human-in-the-Loop

The recruiter can inspect and modify the rubric before candidate evaluation.

### 6. Data Export

Results are available outside the application through CSV export.

---

# 🚀 Current Milestone

> **Phase 6 Complete**

The project currently supports the complete screening workflow:

```text
             JOB DESCRIPTION
                    ↓
             AI-GENERATED RUBRIC
                    ↓
              RUBRIC EDITING
                    ↓
             MULTI-PDF UPLOAD
                    ↓
             RESUME PROCESSING
                    ↓
             CANDIDATE SCORING
                    ↓
              RANKED RESULTS
                    ↓
          EXPLAINABLE BREAKDOWN
                    ↓
                CSV EXPORT
```

The core product flow from **job description to ranked, explainable candidate results** is implemented through Phase 6.

---

# 🔮 Roadmap

The next stage of development will extend the system beyond basic resume screening toward **systematic evaluation of potential bias in AI-assisted recruitment**.

Planned areas include:

* Controlled synthetic resume pairs
* Demographic-adjacent proxy testing
* Comparative scoring analysis
* Bias measurements
* Audit reporting

> **Phase 7 and beyond are intentionally kept outside the current implementation scope of this README milestone.**

---

# 💡 Project Vision

The long-term goal is not simply to build another resume parser.

It is to explore a more important question:

> **Can AI-assisted recruitment systems evaluate candidates consistently, transparently, and fairly?**

The project therefore evolves from:

**Automated Screening**

→ **Explainable Screening**

→ **Auditable AI Screening**

---

# 👨‍💻 Project

**AI Resume Screening Agent**

Built as an AI/ML engineering project exploring:

* Large Language Models
* Resume Intelligence
* Structured Evaluation
* Explainable AI
* Automated Candidate Ranking
* AI-Assisted Recruitment

---

<p align="center">

**Built with Python • Streamlit • AI • Data**

</p>
