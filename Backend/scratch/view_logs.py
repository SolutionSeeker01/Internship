import os
log_file = "e:/Internship/Backend/utils/logs/app.log"
if os.path.exists(log_file):
    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        print("".join(lines[-100:]))
else:
    print("Log file does not exist")
