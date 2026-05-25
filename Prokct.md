# Final Assignment

## I. Project Requirements

### 1. Project Objective

The objective of this project is to design, implement, and document an end-to-end NLP system that solves a realistic industry or business problem.

This project must reflect real-world NLP practice, including problem formulation, data handling, model development, deployment considerations, and ethical responsibility.

Important: This is not a research-only or notebook-only project. Your system must be designed as if it were going into production.

### 2. Business Problem Definition

Requirements:

- Begin with a clear business use case where NLP provides measurable value.

Deliverables:

- Submit a Problem Definition Document, 1-2 pages, containing:
  - Business context and motivation
  - Target users or stakeholders
  - Description of the problem being solved
  - Explanation of why NLP is required
  - Success metrics, including:
    - Business metrics, for example cost reduction, time saved, efficiency
    - Technical metrics, for example accuracy, F1-score, latency

### 3. Development Infrastructure and Tooling

Requirements:

- Follow professional software development practices, including:
  - Programming language: Python
  - Version control: Git
  - Clear and modular project structure
  - Dependency management, for example `requirements.txt` or `pyproject.toml`

Deliverables:

- A source repository containing:
  - `src/` - source code
  - `data/` - data or data scripts
  - `models/` - trained models or checkpoints
  - `configs/` - configuration files
  - `tests/` - tests, where applicable
- A `README.md` explaining:
  - Environment setup
  - How to train the model
  - How to run inference
  - Basic logging or experiment tracking

### 4. Data Management

Requirements:

- Demonstrate responsible and structured data handling:
  - Data sourcing, public, synthetic, or anonymized
  - Data preprocessing and cleaning
  - Train/validation/test split
  - Handling missing, noisy, or biased data

Deliverables:

- Submit a Data Description Document including:
  - Data source and licensing, if applicable
  - Dataset size and language(s)
  - Preprocessing steps
  - Justification for data splits
  - Discussion of known limitations and potential biases

### 5. Model Selection and Optimization

Requirements:

- Select an appropriate NLP model, traditional ML or deep learning.
- Justify why the model fits the business problem.
- Implement at least basic hyperparameter tuning.
- Compare performance against at least one baseline.

Deliverables:

- Model architecture description
- Training procedure
- Evaluation results including:
  - Baseline comparison
  - Error analysis: what the model fails on and why
- Discussion of trade-offs:
  - Accuracy vs. speed
  - Model complexity vs. maintainability

### 6. Deployment

Requirements:

- The system must be deployable, not only trainable.
- Acceptable deployment formats include:
  - REST API
  - Web-based demo
  - Command-line interface
  - Batch processing pipeline
- Consider:
  - Latency
  - Scalability
  - Model versioning

Deliverables:

- A working inference pipeline
- Documentation describing:
  - User interaction
  - Input and output formats
- Discussion of deployment challenges and limitations

### 7. Agentic AI Component

Requirements:

- Include agentic behavior, such as:
  - Multi-step reasoning
  - Tool usage, for example search, APIs, databases
  - Decision-making based on intermediate outputs

Examples:

- A chatbot that retrieves documents before responding
- A system that routes inputs to different NLP models
- An application that asks clarifying questions

Deliverables:

- Description of the agent architecture
- Flow diagram or pseudocode
- Example interaction demonstrating agent decisions

### 8. Continual Learning and Monitoring

Requirements:

- Design conceptually for model evolution over time, even if full implementation is not feasible.

Deliverables:

- Continual learning strategy document describing:
  - How new data would be collected
  - How retraining or fine-tuning would occur
  - How performance degradation would be detected
- Proposed monitoring metrics
- Discussion of model drift risks and mitigation strategies

### 9. Data Privacy and Model Robustness

Requirements:

- Address:
  - Data privacy and security risks
  - Robustness to noisy or adversarial inputs

Deliverables:

- Privacy analysis covering:
  - Handling of personally identifiable information, PII
  - Anonymization or minimization strategies
- Robustness discussion including:
  - Out-of-domain inputs
  - Failure cases
- Mitigation strategies

### 10. Project Management and Teamwork

Requirements:

- Demonstrate team-style planning.

Deliverables:

- Project plan or timeline
- Task breakdown, roles may be simulated for solo work
- Reflection on how the project would scale in a real team environment

### 11. Ethics and Responsible AI

Requirements:

- Critically assess the ethical implications of the system.

Deliverables:

- Ethics impact statement discussing:
  - Who benefits from the system
  - Who could be harmed
- Bias and fairness risks
- Explainability considerations for non-technical stakeholders
- Discussion of potential misuse

## II. Submission Requirement

Students must submit three components:

- A written report
- The complete source code
- A presentation slide deck

Note: Failure to submit any required component may result in a significant grade penalty.

### 1. Written Report

Format:

- Length: 10-15 pages, excluding references and appendices
- File type: PDF
- Font size: 11-12 pt
- Line spacing: 1.15-1.5
- Figures and tables must be clearly labeled and referenced

Content:

- The report must contain all information in Section I.

### 2. Source Code Submission

Format:

- Submission via Git repository link, public repo
- Repository must be complete and runnable

Required repository structure:

```text
project-root/
├── src/          # Core source code
├── data/         # Data or data-loading scripts
├── models/       # Trained models or checkpoints
├── configs/      # Configuration files
├── tests/        # Tests, if applicable
├── requirements.txt or pyproject.toml
└── README.md
```

The `README.md` must include:

- Project overview
- Environment setup instructions
- Dependency installation steps
- How to train the model
- How to run inference or the deployed system
- Description of deployment method

Code quality expectations:

- Code must be:
  - Well-organized and modular
  - Clearly commented where necessary
  - Reproducible; Docker is encouraged
- Hard-coded paths, credentials, or secrets are not allowed.
- Large datasets should not be committed directly; use download scripts.

### 3. Presentation Slides

Format:

- Length: 10-15 slides
- File type: PDF or PPTX

Slides must include:

- Title and team information
- Business problem and motivation
- Proposed NLP solution
- System architecture diagram
- Data overview
- Model and evaluation results
- Agentic AI component
- Deployment overview
- Ethics, privacy, and risks
- Key takeaways and future work

Presentation expectations:

- Slides should be visual and concise.
- Avoid dense text blocks.
- Diagrams and charts are strongly encouraged.
- Slides must align with the written report.

## III. Project List

1. Sign Language Translation System  
   Link: <https://www.wmt-slt.com/>

2. Resume Screening and Ranking System  
   Link: <https://github.com/Hunterdii/Smart-AI-Resume-Analyzer>

3. Knowledge Base Question-Answering System  
   Link: <https://github.com/LHRLAB/ChatKBQA>

4. Invoice and Receipt Processing System  
   Link: <https://github.com/ruizguille/invoice-processing>

5. Audiobook Generation System  
   Link: <https://github.com/denizsafak/abogen>

6. Vietnamese Handwriting Detection System  
   Link: To be defined by the student

7. Document-Level OCR System  
   Link: To be defined by the student

8. Exploratory Search of Scientific Literature System  
   Link: <https://github.com/NLP-Knowledge-Graph/NLP-KG-WebApp>

9. Citation Recommendation System  
   Link: <https://github.com/nianlonggu/SciLit>

10. Automatic Meeting Minutes and Action Item Extraction System  
    Link: <https://github.com/Zackriya-Solutions/meeting-minutes>

11. Fake News and Misinformation Detection System  
    Link: <https://github.com/KaiDMML/FakeNewsNet>

12. Model Drift Detection and Monitoring System for NLP  
    Link: <https://github.com/SeldonIO/alibi-detect>

13. Speech-to-Speech Translation System  
    Link: <https://github.com/facebookresearch/seamless_communication>

14. Structured Document-Level Translation System  
    Link: <https://aclanthology.org/2025.ijcnlp-long.38.pdf>

15. Document Image Machine Translation System  
    Link: <https://aclanthology.org/2025.acl-long.606.pdf>

16. Hate Speech and Toxicity Detection System  
    Link: <https://github.com/unitaryai/detoxify>

17. Multimodal Question-Answering System  
    Link: <https://github.com/facebookresearch/mmf>

18. Temporal Knowledge Graph Question-Answering System  
    Link: <https://github.com/cosmicexotic/TKGQA-Survey>

19. Text-to-Image Retrieval System  
    Link: <https://github.com/kingyiusuen/clip-image-search>

20. Text Search within Images System  
    Link: <https://github.com/kanchan2803/ImgToText>

21. Others  
    This is the project that your team proposes; it needs to be approved.
