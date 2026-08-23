# KOSPI Closing Brief

평일 장 마감 후 코스피 지수, 환율, 수급, 시가총액 상위 종목과 주요 뉴스를 자동으로 정리해 GitHub Pages에 게시하고 카카오톡 `나에게 보내기`로 알립니다.

## 운영 시각

- 평일 16:20 KST
- GitHub Actions 예약 실행 특성상 실제 시작은 수 분 지연될 수 있습니다.
- 최근 거래일 데이터를 찾지 못하면 작업이 실패하며 잘못된 리포트를 발행하지 않습니다.

## 필요한 GitHub Actions Secrets

- `KAKAO_REST_API_KEY`
- `KAKAO_CLIENT_SECRET`
- `KAKAO_REFRESH_TOKEN`

키와 토큰은 코드나 커밋에 저장하지 않습니다.
