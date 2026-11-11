# Antigravity Git Automation Rule
- 코드 수정이나 기능 추가 작업이 성공적으로 완료되면, 수동 지시가 없더라도 항상 아래 Git 동기화를 스스로 실행할 것:
  1. `git add .`
  2. 작업 내용을 명확히 기술한 커밋 메시지 작성 (`git commit -m "..."`)
  3. 원격 저장소로 즉시 전송 (`git push origin main`)
- 최종 완료 보고 시 항상 방금 푸시된 커밋 해시와 메시지를 함께 출력할 것.
