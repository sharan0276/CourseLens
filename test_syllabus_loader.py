import sys
from config.syllabus_loader import SyllabusLoader

def test_syllabus_loader():
    print("Testing SyllabusLoader...\n")
    loader = SyllabusLoader(config_path="config/syllabus_topics.json")
    
    # Test get_topics(3)
    print("--- Test get_topics(3) ---")
    topics_3 = loader.get_topics(3)
    if not topics_3:
        print("FAIL: Expected topics for lecture 3 but got nothing.")
    else:
        print(f"SUCCESS: Topics for lecture 3 ({len(topics_3)} items):")
        print(topics_3)
    print("\n")
    
    # Test get_topics(99)
    print("--- Test get_topics(99) ---")
    topics_99 = loader.get_topics(99)
    if topics_99 == []:
        print("SUCCESS: Handled missing lecture 99 gracefully returning []")
    else:
        print(f"FAIL: Expected empty list but got: {topics_99}")
    print("\n")

    # Test get_all_topics_up_to(2)
    print("--- Test get_all_topics_up_to(2) ---")
    all_topics = loader.get_all_topics_up_to(2)
    print(f"All topics up to lecture 2 (Total {len(all_topics)} items):")
    print(all_topics)

if __name__ == "__main__":
    test_syllabus_loader()
