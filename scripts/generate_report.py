from datetime import datetime
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo
import re
import urllib.request
import feedparser
import yfinance as yf

KST = ZoneInfo("Asia/Seoul")
OUT = Path("site/index.html")
LEADERS = {"삼성전자":"005930.KS","SK하이닉스":"000660.KS","현대차":"005380.KS","삼성바이오로직스":"207940.KS","LG에너지솔루션":"373220.KS"}


class TableRows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None


def investor_flows(now):
    url = (
        "https://finance.naver.com/sise/investorDealTrendDay.naver"
        f"?bizdate={now:%Y%m%d}&sosok=0&page=1"
    )
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.naver.com/sise/sise_trans_style.naver?sosok=0",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()
    parser = TableRows()
    parser.feed(raw.decode("euc-kr", errors="replace"))
    for row in parser.rows:
        if len(row) >= 4 and re.fullmatch(r"\d{2}\.\d{2}", row[0]):
            values = [int(value.replace(",", "").replace("+", "")) for value in row[1:4]]
            return row[0], dict(zip(("개인", "외국인", "기관"), values))
    raise RuntimeError("네이버증권 코스피 투자자별 수급 데이터가 없습니다.")


def flow_html(now):
    try:
        trade_date, flows = investor_flows(now)
        items = []
        for name, value in flows.items():
            direction = "순매수" if value > 0 else "순매도" if value < 0 else "보합"
            items.append(f"<li><span>{name}</span>{signed(value, '억원', label=direction)}</li>")
        return f'<ul>{"".join(items)}</ul><p class="muted source">{trade_date} · 네이버증권 · 단위: 억원</p>'
    except Exception as exc:
        print(f"투자자별 수급 조회 실패: {exc}")
        return '<p class="muted">네이버증권 수급 데이터를 확인하지 못했습니다.</p>'

def quote(ticker):
    frame = yf.download(ticker, period="10d", progress=False, auto_adjust=False)
    values = frame["Close"].dropna().to_numpy().reshape(-1)
    if len(values) < 2: raise RuntimeError(f"시세 데이터 부족: {ticker}")
    current, previous = float(values[-1]), float(values[-2])
    return current, (current / previous - 1) * 100

def signed(value, suffix="", label=None):
    css = "up" if value > 0 else "down" if value < 0 else "flat"
    arrow = "▲" if value > 0 else "▼" if value < 0 else "―"
    text = f"{abs(value):,.0f}" if suffix == "억원" else f"{abs(value):,.2f}"
    prefix = f"{label} " if label else ""
    return f'<span class="{css}">{prefix}{arrow} {text}{suffix}</span>'

def main():
    now = datetime.now(KST)
    kospi, kospi_change = quote("^KS11")
    fx, fx_change = quote("KRW=X")
    leaders = []
    for name, ticker in LEADERS.items():
        try: leaders.append((name, quote(ticker)[1]))
        except Exception: leaders.append((name, 0.0))
    feed = feedparser.parse("https://news.google.com/rss/search?q=%EC%BD%94%EC%8A%A4%ED%94%BC+%EC%A6%9D%EC%8B%9C&hl=ko&gl=KR&ceid=KR:ko")
    news = [(escape(x.title), escape(x.link)) for x in feed.entries[:5]]
    tone = "강세" if kospi_change > .5 else "약세" if kospi_change < -.5 else "보합권"
    summary = f"코스피는 {kospi:,.2f}로 마감해 전 거래일 대비 {kospi_change:+.2f}%를 기록했습니다. 시장은 {tone} 흐름을 보였습니다."
    investors_html = flow_html(now)
    leader_html = "".join(f"<li><span>{escape(n)}</span>{signed(p,'%')}</li>" for n,p in leaders)
    news_html = "".join(f'<li><a href="{u}" target="_blank" rel="noopener">{t}</a></li>' for t,u in news)
    style = ''':root{--line:#203249;--text:#eef5ff;--muted:#8ea2bb;--up:#ff5d70;--down:#56a8ff;--accent:#5ce1b9}*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#07111f,#0a1524 46%,#07111f);color:var(--text);font-family:Inter,"Noto Sans KR",system-ui,sans-serif}main{width:min(1080px,100%);margin:auto;padding:28px 18px 70px}header{display:flex;justify-content:space-between;gap:20px;align-items:flex-end;padding:18px 0 28px}.eyebrow{color:var(--accent);font-size:12px;font-weight:800;letter-spacing:.14em}h1{font-size:clamp(30px,5vw,52px);margin:8px 0;letter-spacing:-.05em}.muted{color:var(--muted);font-size:13px}.source{margin:12px 0 0}.badge{border:1px solid #2c4b61;border-radius:99px;padding:8px 12px;color:#bdeedc;font-size:12px}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:14px}.card{grid-column:span 4;background:linear-gradient(145deg,#102135ee,#0a1829f5);border:1px solid var(--line);border-radius:20px;padding:20px}.wide{grid-column:span 8}.half{grid-column:span 6}.full{grid-column:1/-1}.label{color:var(--muted);font-size:12px;font-weight:700}.value{font-size:30px;font-weight:800;margin:8px 0 4px}.up{color:var(--up)}.down{color:var(--down)}.flat{color:var(--accent)}h2{font-size:18px;margin:0 0 16px}p{line-height:1.65}.summary{font-size:18px;margin:0}ul{list-style:none;margin:0;padding:0}li{display:flex;justify-content:space-between;gap:14px;padding:13px 0;border-top:1px solid var(--line)}li:first-child{border-top:0;padding-top:0}a{color:#dceaff;text-decoration:none}footer{color:#6f849e;font-size:12px;text-align:center;padding-top:28px}@media(max-width:760px){header{align-items:flex-start;flex-direction:column}.card,.wide,.half{grid-column:1/-1}.card{padding:17px;border-radius:17px}}'''
    html = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KOSPI Closing Brief</title><style>{style}</style></head><body><main><header><div><div class="eyebrow">MARKET CLOSE · KOREA</div><h1>KOSPI Closing Brief</h1><div class="muted">오늘 시장을 움직인 숫자와 이유를 3분 안에</div></div><div><div class="badge">장 마감 리포트</div><div class="muted">{now:%Y.%m.%d %H:%M} KST</div></div></header><section class="grid"><article class="card"><div class="label">KOSPI</div><div class="value">{kospi:,.2f}</div>{signed(kospi_change,'%')}</article><article class="card"><div class="label">USD / KRW</div><div class="value">{fx:,.2f}</div>{signed(fx_change,'%')}</article><article class="card"><div class="label">업데이트</div><div class="value">16:20</div><div class="muted">평일 KST</div></article><article class="card wide"><h2>오늘의 한 문장</h2><p class="summary">{escape(summary)}</p></article><article class="card"><h2>투자자별 수급</h2>{investors_html}</article><article class="card half"><h2>시가총액 주요 종목</h2><ul>{leader_html}</ul></article><article class="card half"><h2>시장 폭 & 기술 지표</h2><p class="muted">공식 데이터 연결 후 표시됩니다.</p></article><article class="card full"><h2>주요 뉴스</h2><ul>{news_html}</ul></article><article class="card half"><h2>실적 & 공시</h2><p class="muted">DART API 연결 후 표시됩니다.</p></article><article class="card half"><h2>다음 거래일 관전 포인트</h2><p>미국 증시 · 반도체 · 환율 · 외국인 수급</p></article><article class="card full"><p class="muted">정보 제공 목적이며 투자 권유가 아닙니다. Yahoo Finance, 네이버증권 및 Google News RSS 기반.</p></article></section><footer>KOSPI Closing Brief</footer></main></body></html>'''
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(summary)

if __name__ == "__main__": main()
