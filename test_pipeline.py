from services.chat.pipeline import ChatPipeline
from domain.chat_session import ChatSession

def main():
    pipe = ChatPipeline()
    session = ChatSession(session_id="test", student_id="test_student")
    
    q = "what are goals of software engineering?"
    print(f"Query: {q}")
    result = pipe.process_message(session, q, lecture_number=10)
    print("Result:", result.reply)

if __name__ == "__main__":
    main()
