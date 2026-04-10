import os, json

d = "CourseLens_data/chat_sessions"
for fname in os.listdir(d):
    if fname.endswith(".json"):
        with open(os.path.join(d, fname)) as f:
            data = json.load(f)
            print(fname, len(data.get("messages", [])))
