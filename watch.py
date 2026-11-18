"""시부야 스카이 취소표 감시기.
창을 띄우지 않고 확인하다가, 원하는 시간대에 자리가 나면 "FOUND"를 출력하고 소리 낸 뒤 종료.
(Claude가 이 종료를 신호로 받아 내장 브라우저에서 예매 직전까지 골라 둠)

사용법:  python watch.py 날짜 시작시각 끝시각 [인원]
예)      python watch.py 2026-12-02 15:20 16:20 2
         → 12/2 입장 15:20~16:20 사이에 시작하는 시간대(15:20, 15:40, 16:00, 16:20)를 감시, 어른 2명

클라우드(GitHub Actions)에서는 환경변수로 동작이 바뀜:
  NTFY_TOPIC  → 자리가 나면 ntfy 앱으로 휴대폰 푸시 알림
  MAX_MINUTES → 이 시간만큼만 감시하고 종료(다음 실행이 이어받음)
"""
import os, sys, time, random, urllib.request
from playwright.sync_api import sync_playwright

# 해외 거주자용(영문) 페이지. 15시 전/후 플랜이 한 페이지에 다 있음
URL = "https://shibuyasky-ticket.triplabo.jp/en/product/prod_agqchhbawn64ljait24jy4xvm4"
INTERVAL = 50  # 초(+확인 시간 약 10초 = 약 1분마다). 너무 짧게 하면 차단될 수 있음
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
DEADLINE = time.time() + float(os.environ.get("MAX_MINUTES", "inf")) * 60

date, start, end = sys.argv[1:4]
people = int(sys.argv[4]) if len(sys.argv) > 4 else 1
plan = "(3:00 p.m.~)" if start >= "15:00" else "(~2:59 p.m.)"


def wanted(slot_text):  # "15:20〜15:39" → 시작 시각이 범위 안인가
    return start <= slot_text[:5] <= end


def check(page):
    """원하는 시간대 중 자리가 있는 첫 번째 칸을 돌려줌(없으면 None)."""
    page.goto(URL)
    page.wait_for_selector('[role="grid"] [title]', timeout=30000)
    if not page.locator(f'[title="{date}"]').count():
        page.locator('[class*="_navButton"]').last.click()  # 다음 달
    cell = page.locator(f'[title="{date}"]')
    if not cell.count() or "disabledCell" in (cell.get_attribute("class") or ""):
        print(time.strftime("%H:%M:%S"), date, "아직 판매 전이거나 날짜 전체 매진")
        return None
    cell.click()
    confirm = page.get_by_role("button", name="Confirm")
    if confirm.is_visible(timeout=3000):
        confirm.click()
    page.get_by_text(plan, exact=False).last.click()
    page.wait_for_timeout(1500)
    slots = page.locator('[class*="_timeSlot_"]')
    hit, report = None, []
    for i in range(slots.count()):
        s = slots.nth(i)
        text = s.inner_text().strip()
        if not wanted(text):
            continue
        cls = s.get_attribute("class") or ""
        state = "×" if "Disabled" in cls else "△" if "Limited" in cls else "○"
        report.append(f"{text[:5]} {state}")
        if state != "×" and not hit:
            hit = s
    print(time.strftime("%H:%M:%S"), date, " / ".join(report) or "해당 시간대 없음")
    return hit


with sync_playwright() as p:
    # 화면에 창을 띄우지 않는 브라우저로 확인만 함
    # 윈도우는 설치된 엣지, 클라우드(리눅스)는 Playwright 크로미움
    channel = "msedge" if sys.platform == "win32" else None
    page = p.chromium.launch(channel=channel, headless=True).new_page()
    while time.time() < DEADLINE:
        try:
            slot = check(page)
        except Exception as e:  # 페이지 늦게 뜸 등 → 다음 회차에 재시도
            print("확인 실패, 다시 시도:", str(e).splitlines()[0])
            slot = None
        if slot:
            msg = f"시부야 스카이 취소표! {date} {slot.inner_text().strip()[:5]} 입장 ({people}명)"
            print("FOUND", msg, flush=True)
            if NTFY_TOPIC:
                urllib.request.urlopen(urllib.request.Request(
                    f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode(),
                    headers={"Click": URL, "Priority": "urgent"}))
            if sys.platform == "win32":
                import winsound
                for _ in range(10):
                    winsound.Beep(1500, 400)
            break
        time.sleep(INTERVAL + random.randint(0, 5))
