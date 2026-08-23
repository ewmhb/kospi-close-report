from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import yfinance as yf
from pykrx import stock


KST = ZoneInfo("Asia/Seoul")
OUT = Path("site/index.html")


def latest_trading_day(now):
    day = now.date()
    for _ in range(10):
        key = day.strftime("%Y%m%d")
        if not stock.get_market_ohlcv_by_ticker(key, market="KOSPI").empty:
            return key
        day -= timedelta(days=1)
    raise RuntimeError("최근 코스피 거래일을 찾지 못했습니다.")


def signed(value, suffix=""):
    cls = "up" if value > 0 else "down" if value < 0 else "flat"
    arrow = "▲" if value > 0 else "▼" if value < 0 else "―"
    return f'<span class="{cls}">{arrow} {abs(value):,.2f}{suffix}</span>'


def get_news():
    url = "https://news.google.com/rss/search?q=%EC%BD%94%EC%8A%A4%ED%94%BC+%EC%A6%9D%EC%8B%9C&hl=ko&gl=KR&ceid=KR:ko"
    feed = feedparser.parse(url)
    return [(escape(x.title), escape(x.link)) for x in feed.entries[:5]]


def main():
    now = datetime.now(KST)
    day = latest_trading_day(now)
    ohlcv = stock.get_index_ohlcv(day, day, "1001")
    if ohlcv.empty:
        raise RuntimeError("코스피 지수 데이터를 불러오지 못했습니다.")
    row = ohlcv.iloc[-1]
    close = float(row["종가"])
    change = float(row.get("등락률", 0))

    cap = stock.get_market_cap_by_ticker(day, market="KOSPI").head(5)
    prices = stock.get_market_ohlcv_by_ticker(day, market="KOSPI")
    leaders = []
    for ticker in cap.index:
        name = stock.get_market_ticker_name(ticker)
        pct = float(prices.loc[ticker, "등락률"]) if ticker in prices.index else 0
        leaders.append((name, pct))

    investors = stock.get_market_trading_value_by_investor(day, day, "KOSPI")
    investor_rows = []
    for label in ("외국인", "기관합계", "개인"):
        value = int(investors.loc[label, "순매수"]) / 100_000_000 if label in investors.index else 0
        investor_rows.append((label.replace("기관합계", "기관"), value))

    fx = yf.download("KRW=X", period="5d", progress=False, auto_adjust=False)
    fx_close = float(fx["Close"].dropna().iloc[-1]) if not fx.empty else 0
    fx_prev = float(fx["Close"].dropna().iloc[-2]) if len(fx) > 1 else fx_close
    fx_change = (fx_close / fx_prev - 1) * 100 if fx_prev else 0
    news = get_news()

    breadth_up = int((prices["등락률"] > 0).sum())
    breadth_down = int((prices["등락률"] < 0).sum())
    volume_value = float(prices["거래대금"].sum()) / 1_000_000_000_000
    tone = "강세" if change > .5 else "약세" if change < -.5 else "보합권"
    summary = f"코스피는 {close:,.2f}로 마감해 {change:+.2f}%를 기록했습니다. 시장은 {tone}이었고 외국인·기관 수급과 원화 흐름이 핵심 변수였습니다."

    leader_html = "".join(f"<li><span>{escape(n)}</span>{signed(p, '%')}</li>" for n, p in leaders)
    investor_html = "".join(f"<li><span>{escape(n)}</span>{signed(v, '억')}</li>" for n, v in investor_rows)
    news_html = "".join(f'<li><a href="{u}" target="_blank" rel="noopener">{t}</a></li>' for t, u in news)

    html = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#07111f"><title>KOSPI Closing Brief</title>
<style>:root{{--bg:#07111f;--panel:#0d1a2b;--line:#203249;--text:#eef5ff;--muted:#8ea2bb;--up:#ff5d70;--down:#56a8ff;--accent:#5ce1b9}}*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(180deg,#07111f,#0a1524 46%,#07111f);color:var(--text);font-family:Inter,"Noto Sans KR",system-ui,sans-serif}}main{{width:min(1080px,100%);margin:auto;padding:28px 18px 70px}}header{{display:flex;justify-content:space-between;gap:20px;align-items:flex-end;padding:18px 0 28px}}.eyebrow{{color:var(--accent);font-size:12px;font-weight:800;letter-spacing:.14em}}h1{{font-size:clamp(30px,5vw,52px);margin:8px 0;letter-spacing:-.05em}}.muted{{color:var(--muted);font-size:13px}}.badge{{border:1px solid #2c4b61;border-radius:99px;padding:8px 12px;color:#bdeedc;font-size:12px}}.grid{{display:grid;grid-template-columns:repeat(12,1fr);gap:14px}}.card{{grid-column:span 4;background:linear-gradient(145deg,#102135ee,#0a1829f5);border:1px solid var(--line);border-radius:20px;padding:20px}}.wide{{grid-column:span 8}}.half{{grid-column:span 6}}.full{{grid-column:1/-1}}.label{{color:var(--muted);font-size:12px;font-weight:700}}.value{{font-size:30px;font-weight:800;margin:8px 0 4px}}.up{{color:var(--up)}}.down{{color:var(--down)}}.flat{{color:var(--accent)}}h2{{font-size:18px;margin:0 0 16px}}p{{line-height:1.65}}.summary{{font-size:18px;margin:0}}ul{{list-style:none;margin:0;padding:0}}li{{display:flex;justify-content:space-between;gap:14px;padding:13px 0;border-top:1px solid var(--line)}}li:first-child{{border-top:0;padding-top:0}}a{{color:#dceaff;text-decoration:none}}a:hover{{color:var(--accent)}}footer{{color:#6f849e;font-size:12px;text-align:center;padding-top:28px}}@media(max-width:760px){{header{{align-items:flex-start;flex-direction:column}}.card,.wide,.half{{grid-column:1/-1}}.card{{padding:17px;border-radius:17px}}}}</style></head><body><main>
<header><div><div class="eyebrow">MARKET CLOSE · KOREA</div><h1>KOSPI Closing Brief</h1><div class="muted">오늘 시장을 움직인 숫자와 이유를 3분 안에</div></div><div><div class="badge">장 마감 리포트</div><div class="muted" style="margin-top:8px">{now:%Y.%m.%d %H:%M} KST</div></div></header>
<section class="grid"><article class="card"><div class="label">KOSPI</div><div class="value">{close:,.2f}</div>{signed(change, '%')}</article><article class="card"><div class="label">USD / KRW</div><div class="value">{fx_close:,.2f}</div>{signed(fx_change, '%')}</article><article class="card"><div class="label">거래대금</div><div class="value">{volume_value:,.1f}조</div><div class="muted">유가증권시장 전체</div></article>
<article class="card wide"><h2>오늘의 한 문장</h2><p class="summary">{escape(summary)}</p></article><article class="card"><h2>투자자별 수급</h2><ul>{investor_html}</ul></article>
<article class="card half"><h2>시가총액 주요 종목</h2><ul>{leader_html}</ul></article><article class="card half"><h2>시장 폭</h2><div class="value">상승 {breadth_up}</div><div class="value">하락 {breadth_down}</div><p class="muted">보합 {len(prices)-breadth_up-breadth_down}종목</p></article>
<article class="card full"><h2>시장에 영향을 준 주요 뉴스</h2><ul>{news_html}</ul></article><article class="card half"><h2>기술적 체크</h2><p class="muted">이동평균선·RSI 등 상세 지표는 다음 버전에서 추가됩니다.</p></article><article class="card half"><h2>실적 & 공시</h2><p class="muted">DART API 키 연결 후 당일 주요 공시가 자동 표시됩니다.</p></article><article class="card full"><h2>다음 거래일 관전 포인트</h2><p>미국 증시와 반도체 흐름 · 원/달러 환율 · 외국인 현물 수급 · 주요 경제지표와 기업 공시</p><p class="muted">정보 제공 목적이며 투자 권유가 아닙니다. 데이터는 KRX·Yahoo Finance·Google News를 바탕으로 자동 생성됩니다.</p></article></section><footer>KOSPI Closing Brief · {day}</footer></main></body></html>'''
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()

