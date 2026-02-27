import subprocess
import sys

REMOTE = "origin"
BRANCH = "masterdjq"

def run(cmd):
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(result.returncode)

# 커밋 메시지 입력
commit_message = input("커밋 메시지를 입력하세요: ").strip()

if not commit_message:
    print("커밋 메시지가 비어 있습니다. 종료합니다.")
    sys.exit(1)

# 전체 파일 대상
run(["git", "add", "."])
run(["git", "commit", "-m", commit_message])
run(["git", "push", REMOTE, BRANCH])