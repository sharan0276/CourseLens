# 📚 CourseLens: A Socratic AI Tutor for Active Learning

![CourseLens Banner](assets/output_screenshots/Socratic_Engine.png)

CourseLens is a high-quality AI tutoring system designed to turn passive reading into active learning. Unlike standard chatbots, CourseLens is built to prioritize teaching accuracy, grounding every interaction in provided lecture materials while using advanced AI patterns to manage context and relevancy.

![Overall Architecture](assets/architecture/overall_architecture.png)

---

## 💡 How it Works: The GRASP Approach

![Prompt Engineering Ideation](assets/architecture/ideation_of_prompt_triggers.png)

Instead of just answering questions, CourseLens follows a design philosophy we call **GRASP**. We wanted the system to feel like a real TA who is helpful but won't do the work for you.

*   **Gradual**: It starts by checking what the student already knows before diving into complex explanations.
*   **Reflective**: Every few turns, it summarizes the progress so the student can see how far they've come.
*   **Affirming**: It recognizes small breakthroughs ("Nice work!" or "Spot on!") to keep momentum high.
*   **Socratic**: It uses leading questions to help students find the answer themselves.
*   **Patient**: It stays in the "hinting" mode as long as needed, even if a student is rushing for a quick fix.

---

## 🛠️ Engineering Advantages

CourseLens is built to solve common AI challenges, ensuring the system remains fast, accurate, and faithful to the course curriculum.

### 1. Avoiding "Context Bloat"
Standard AI systems often get confused in long conversations when old, irrelevant messages clutter the memory. CourseLens solves this in two ways:
*   **Temporary Socratic History**: A specialized context window for tutoring that clears once a concept is mastered.
*   **Summarized Memory**: A `SummarizationEngine` that condenses the long conversation history into core facts, keeping code snippets exactly as they were without the extra "noise."

### 2. High-Accuracy Grounding (Hybrid Search)
To ensure the tutor always uses the most relevant lecture material, we use a **Hybrid Search** strategy:
*   **Semantic Search**: Finds the general meaning of a question.
*   **Keyword Search (BM25)**: Ensures exact matches for technical C++ terms like specific operators or functions.
*   **Material Priority**: The system explicitly ranks **Professor-Provided Slides** higher than web-scraped content to ensure the core learning comes from the official curriculum first.

### 3. Curriculum Controls & Filtering
*   **Week-Based Filtering**: Metadata filters ensure the AI doesn't talk about future concepts that haven't been taught yet in the syllabus.
*   **Topic-Based Filtration**: Automatically picks out topics from a student's question to search the knowledge base more precisely.

### 4. Dual-Model Logic
CourseLens uses a two-model pattern to keep things efficient:
*   **Assessor (Small Model)**: Quickly classifies what the student is asking and checks if their answers are "Correct" or a "Misconception."
*   **Generator (Main Model)**: Focuses on writing clear, helpful teaching responses based on the assessor's logic and the lecture materials.

---

## 📸 Technical Showcase

### The Socratic Engine in Action
The system identifies the student's stage of learning and provides hints grounded in the slides.
![Socratic Engine](assets/output_screenshots/Socratic_Engine.png)

### Multi-Source Web Scraping
When course materials are too brief, the system intelligently pulls in extra detail from trusted sites (GFG, LearnCpp).
![Lecture Material vs Web Result 1](assets/output_screenshots/Lecture_Material_vs_Web_Scrapping-1.png)
![Lecture Material vs Web Result 2](assets/output_screenshots/Lecture_Material_vs_Web_Scrapping-2.png)

### Visual RAG & Image Retrieval
The system automatically pulls in and shows relevant diagrams from the lecture slides.
![Image Retrieval](assets/output_screenshots/Image_Retrieval.png)

> [!NOTE]
> Detailed technical diagrams and the full library of output screenshots are available in the [assets](assets/) directory.

---

## 🚀 Setup & Run

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Start the System**:
   You will need to run the following in **two separate terminals**:

   *   **Terminal 1 (Backend API)**:
       ```bash
       python3 api.py
       ```
   *   **Terminal 2 (User Interface)**:
       ```bash
       streamlit run ui.py
       ```

---

*Developed by [Sharan Giri](https://www.linkedin.com/in/sharan-giri/) & [Jyothssena Gomatum Sreenivaasan](https://www.linkedin.com/in/gsjyothssena/). We focus on building goal-oriented AI systems that do more than just process text.*

---
*Developed for DS5500: Special Topics in Data Science.*
