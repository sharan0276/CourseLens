# 📚 CourseLens: A Socratic AI Tutor for Deeper Learning

![CourseLens Banner](assets/output_screenshots/Socratic_Engine.png)

CourseLens is a project my partner and I built to help students move beyond just "finding the answer." As TAs, we noticed that many students rely on passive reading or shortcuts that don't lead to actual understanding. We built this engine to act as a digital tutor that guides students through concepts using Socratic dialogue.

---

## 💡 How it Works: The GRASP Approach

Instead of just answering questions, CourseLens follows a design philosophy we call **GRASP**. We wanted the system to feel like a real TA who is helpful but won't do the work for you.

*   **Gradual**: It starts by checking what the student already knows before diving into complex explanations.
*   **Reflective**: Every few turns, it summarizes the progress so the student can see how far they've come.
*   **Affirming**: It recognizes small breakthroughs ("Nice work!" or "Spot on!") to keep momentum high.
*   **Socratic**: It uses leading questions to help students find the answer themselves.
*   **Patient**: It stays in the "hinting" mode as long as needed, even if a student is rushing for a quick fix.

---

## 🛠️ The Architecture

### Socratic Logic
The system uses a simple state machine to manage the tutoring flow. It decides whether to **locate** a misconception, **lead** with a hint based on the lecture slides, or **debrief** once the student gets it. 

![System Design](assets/architecture/overall_architecture.png)

### Separate Socratic History
One of the key technical choices we made was keeping the **Socratic Dialogue in a separate history**. 
*   **Why?** Normal chat histories get bloated and cluttered with old context, which makes the AI slower and less accurate. 
*   **The Fix**: By separating the tutoring dialogue, we keep the "reasoning window" small and focused, ensuring the hints are always relevant to the current slide.

---

## 📊 Evaluation Results

We tested CourseLens to make sure it was actually helpful and grounded in the course materials.

*   **96% Faithfulness**: The system almost never "hallucinates" or makes up facts outside the course slides.
*   **81% Relevancy**: The answers stay strictly on-topic.
*   **Stress Tested**: We ran scenarios with "impatient" actors, and the system successfully held the Socratic line 100% of the time without leaking answers.

---

## 📸 Screenshots

````carousel
![ Tutoring Process](assets/output_screenshots/Socratic_Engine.png)
<!-- slide -->
![Web Research](assets/output_screenshots/Web_Scrapping.png)
<!-- slide -->
![Image Retrieval](assets/output_screenshots/Image_Retrieval.png)
````

---

## 🚀 Setup & Run

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
2. **Start the API**:
   ```bash
   python api.py
   ```
3. **Open the UI**:
   ```bash
   streamlit run ui.py
   ```

---

*Developed by [Sharan Giri](https://www.linkedin.com/in/sharan-giri/) & [Jyothssena Gomatum Sreenivaasan](https://www.linkedin.com/in/gsjyothssena/). We’re both interested in building goal-oriented AI systems—feel free to reach out!*

---
*Developed for DS5500: Special Topics in Data Science.*
