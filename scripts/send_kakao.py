import json
import os
import sys
import urllib.parse
import urllib.request


def post(url, data, headers=None):
    body = urllib.parse.urlencode(data).encode()
    request = urllib.request.Request(url, data=body, headers=headers or {}, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def get(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def main():
    client_id = os.environ.get("KAKAO_REST_API_KEY")
    client_secret = os.environ.get("KAKAO_CLIENT_SECRET")
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN")
    report_url = os.environ.get("REPORT_URL")
    summary = os.environ.get("REPORT_SUMMARY", "오늘의 코스피 장 마감 리포트가 발행되었습니다.")
    if not all((client_id, refresh_token, report_url)):
        print("카카오 알림용 환경변수가 없어 발송을 건너뜁니다.")
        return

    token_data = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
    }
    if client_secret:
        token_data["client_secret"] = client_secret
    token = post("https://kauth.kakao.com/oauth/token", token_data)
    access_token = token["access_token"]
    if token.get("refresh_token"):
        print("::warning::카카오 리프레시 토큰이 갱신되었습니다. 저장소 Secret을 새 값으로 교체해야 합니다.")

    report_link = {"web_url": report_url, "mobile_web_url": report_url}
    template = {
        "object_type": "text",
        "text": summary[:180],
        "link": report_link,
        "buttons": [{"title": "리포트 보기", "link": report_link}],
    }
    result = post(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        {"template_object": json.dumps(template, ensure_ascii=False)},
        {"Authorization": f"Bearer {access_token}", "Content-Type": "application/x-www-form-urlencoded"},
    )
    if result.get("result_code") != 0:
        raise RuntimeError(f"카카오 발송 실패: {result}")
    print("카카오톡 나에게 보내기 완료")

    if os.environ.get("SEND_TO_FRIENDS", "false").lower() != "true":
        print("수동 테스트 실행이므로 친구 발송을 건너뜁니다.")
        return

    auth_headers = {"Authorization": f"Bearer {access_token}"}
    friends = get(
        "https://kapi.kakao.com/v1/api/talk/friends?limit=100&order=asc",
        auth_headers,
    ).get("elements", [])
    receiver_uuids = [friend["uuid"] for friend in friends if friend.get("uuid")]
    if not receiver_uuids:
        print("카카오톡 수신 가능한 앱 친구가 없어 친구 발송을 건너뜁니다.")
        return

    sent_count = 0
    for start in range(0, len(receiver_uuids), 5):
        batch = receiver_uuids[start:start + 5]
        friend_result = post(
            "https://kapi.kakao.com/v1/api/talk/friends/message/default/send",
            {
                "receiver_uuids": json.dumps(batch),
                "template_object": json.dumps(template, ensure_ascii=False),
            },
            {**auth_headers, "Content-Type": "application/x-www-form-urlencoded"},
        )
        successful = friend_result.get("successful_receiver_uuids", [])
        sent_count += len(successful)
        if len(successful) != len(batch):
            raise RuntimeError("일부 친구에게 카카오톡 발송이 실패했습니다.")
    print(f"카카오톡 친구 {sent_count}명에게 보내기 완료")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise
