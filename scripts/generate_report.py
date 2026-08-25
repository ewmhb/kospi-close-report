from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo
import json, re, time, urllib.parse, urllib.request

import feedparser
import yfinance as yf
from pykrx import stock

KST = ZoneInfo("Asia/Seoul")
OUT, CACHE = Path("site/index.html"), Path("work/cache")
FLOW_CACHE, BREADTH_CACHE = CACHE / "investor-flow.json", CACHE / "market-breadth.json"
YIELD_CACHE, NEWS_CACHE = CACHE / "korea-10y-yield.json", CACHE / "news.json"
LEADERS = {"삼성전자":"005930.KS","SK하이닉스":"000660.KS","현대차":"005380.KS","삼성바이오로직스":"207940.KS","LG에너지솔루션":"373220.KS"}

class TableRows(HTMLParser):
    def __init__(self): super().__init__(); self.rows=[]; self.row=None; self.cell=None
    def handle_starttag(self, tag, attrs):
        if tag == "tr": self.row=[]
        elif tag in ("td","th") and self.row is not None: self.cell=[]
    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in ("td","th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split())); self.cell=None
        elif tag == "tr" and self.row is not None:
            if self.row: self.rows.append(self.row)
            self.row=None

def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
def load(path): return json.loads(path.read_text(encoding="utf-8"))
def fetch(url, encoding="utf-8"):
    req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0 (KOSPIClosingBrief)","Cache-Control":"no-cache"})
    with urllib.request.urlopen(req, timeout=20) as res: return res.read().decode(encoding, errors="replace")
def quote(ticker, period="10d"):
    frame=yf.download(ticker, period=period, progress=False, auto_adjust=False)
    values=frame["Close"].dropna().to_numpy().reshape(-1)
    if len(values)<2: raise RuntimeError(f"시세 데이터 부족: {ticker}")
    return float(values[-1]), (float(values[-1])/float(values[-2])-1)*100
def signed(value, suffix="", label=None):
    css="up" if value>0 else "down" if value<0 else "flat"; arrow="▲" if value>0 else "▼" if value<0 else "–"
    text=f"{abs(value):,.0f}" if suffix=="억원" else f"{abs(value):,.2f}"
    return f'<span class="{css}">{(label+" ") if label else ""}{arrow} {text}{suffix}</span>'

def investor_naver(now):
    p=TableRows(); p.feed(fetch("https://finance.naver.com/sise/investorDealTrendDay.naver"+f"?bizdate={now:%Y%m%d}&sosok=01&page=1", "euc-kr"))
    for row in p.rows:
        if len(row)>=4 and re.fullmatch(r"(?:\d{2}\.)?\d{2}\.\d{2}", row[0]):
            return row[0], dict(zip(("개인","외국인","기관"), [int(x.replace(",","").replace("+","")) for x in row[1:4]]))
    raise RuntimeError("네이버증권 수급 데이터 없음")
def investor_krx(now):
    last=None
    for offset in range(8):
        day=now.date()-timedelta(days=offset); ymd=day.strftime("%Y%m%d")
        try:
            f=stock.get_market_trading_value_by_investor(ymd, ymd, "KOSPI")
            if f is None or f.empty or "순매수" not in f.columns: continue
            flows={}
            for name in ("개인","외국인","기관합계"): flows["기관" if name=="기관합계" else name]=round(float(f.loc[name,"순매수"])/100_000_000)
            return day.strftime("%m.%d"), flows
        except Exception as exc: last=exc
    raise RuntimeError(f"KRX 수급 데이터 없음: {last}")
def flow_html(now):
    stale=False
    for source, fn in (("네이버증권",investor_naver),("KRX",investor_krx)):
        try:
            date, flows=fn(now); save(FLOW_CACHE,{"date":date,"flows":flows,"source":source}); break
        except Exception as exc: print(f"{source} 수급 조회 실패: {exc}")
    else:
        d=load(FLOW_CACHE); date,flows,source,stale=d["date"],d["flows"],f'최근 저장값({d.get("source","이전 조회")})',True
    rows="".join(f'<li><span>{name}</span>{signed(value,"억원","순매수" if value>0 else "순매도" if value<0 else "보합")}</li>' for name,value in flows.items())
    return f'<ul>{rows}</ul><p class="muted source">{date} · {source}{" · 실시간 조회 실패로 직전 정상값" if stale else ""} · 단위: 억원</p>'

def breadth_krx(now):
    last=None
    for offset in range(8):
        day=now.date()-timedelta(days=offset); ymd=day.strftime("%Y%m%d")
        try:
            f=stock.get_market_ohlcv_by_ticker(ymd, market="KOSPI")
            if f is None or f.empty or "등락률" not in f.columns: continue
            rates=f["등락률"].dropna(); up=int((rates>0).sum()); down=int((rates<0).sum()); flat=int((rates==0).sum()); total=up+down+flat
            if total<100: continue
            return {"date":day.strftime("%m.%d"),"up":up,"down":down,"flat":flat,"ratio":round(up/total*100,1),"source":"KRX"}
        except Exception as exc: last=exc
    raise RuntimeError(f"KRX 시장폭 데이터 없음: {last}")
def technical():
    f=yf.download("^KS11", period="6mo", progress=False, auto_adjust=False); c=f["Close"].dropna().to_numpy().reshape(-1)
    if len(c)<61: raise RuntimeError("기술지표 시계열 부족")
    changes=[float(c[i]-c[i-1]) for i in range(len(c)-14,len(c))]; gain=sum(max(x,0) for x in changes)/14; loss=sum(max(-x,0) for x in changes)/14
    return {"current":float(c[-1]),"ma20":float(c[-20:].mean()),"ma60":float(c[-60:].mean()),"rsi":100 if loss==0 else 100-100/(1+gain/loss)}
def health_html(now):
    stale=False
    try: b=breadth_krx(now); save(BREADTH_CACHE,b)
    except Exception as exc: print(f"시장폭 조회 실패: {exc}"); b=load(BREADTH_CACHE); stale=True
    try: t=technical()
    except Exception as exc: print(f"기술지표 조회 실패: {exc}"); t=None
    rows=f'<li><span>상승 / 하락</span><strong>{b["up"]} / {b["down"]}</strong></li><li><span>보합 · 상승비율</span><strong>{b["flat"]} · {b["ratio"]:.1f}%</strong></li>'
    if t:
        rows+=f'<li><span>20일선</span><strong>{t["ma20"]:,.2f} · {"상회" if t["current"]>=t["ma20"] else "하회"}</strong></li><li><span>60일선</span><strong>{t["ma60"]:,.2f} · {"상회" if t["current"]>=t["ma60"] else "하회"}</strong></li><li><span>RSI(14)</span><strong>{t["rsi"]:.1f}</strong></li>'
    return f'<ul>{rows}</ul><p class="muted source">{b["date"]} · {b.get("source","KRX")}{" · 실시간 조회 실패로 직전 정상값" if stale else ""}</p>'

def korea_10y_naver():
    p=TableRows(); p.feed(fetch("https://finance.naver.com/marketindex/interestDailyQuote.naver?marketindexCd=IRR_GOVT10Y&page=1", "euc-kr"))
    for row in p.rows:
        if len(row)>=2 and re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", row[0]):
            return {"date":row[0][5:],"value":float(row[1].replace(",","")),"change":float(row[2].replace(",","")) if len(row)>2 else 0,"source":"네이버 금융"}
    raise RuntimeError("한국 국채 10년물 데이터 없음")
def yield_html():
    stale=False
    try: d=korea_10y_naver(); save(YIELD_CACHE,d)
    except Exception as exc: print(f"한국 국채 10년물 조회 실패: {exc}"); d=load(YIELD_CACHE); stale=True
    return f'<div class="label">한국 국채 10년물</div><div class="value">{d["value"]:.3f}%</div>{signed(d.get("change",0),"%p")}<div class="muted">{d["date"]} · {d.get("source","저장값")}{" · 직전 정상값" if stale else ""}</div>'

def latest_news(now):
    entries=[]
    for query in ("코스피 증시 when:1d","한국 증시 when:1d","코스피 외국인 기관 when:1d"):
        url=f'https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=ko&gl=KR&ceid=KR:ko&_={int(time.time())}'
        for x in feedparser.parse(fetch(url)).entries:
            try: published=parsedate_to_datetime(x.published).timestamp()
            except Exception: published=0
            entries.append({"title":x.title,"link":x.link,"published":published})
    unique={}
    for item in sorted(entries,key=lambda x:x["published"],reverse=True): unique.setdefault(re.sub(r"\s+-\s+[^-]+$","",item["title"]).strip(),item)
    items=list(unique.values())[:5]
    if not items: raise RuntimeError("최신 뉴스 없음")
    save(NEWS_CACHE,{"items":items,"saved_at":now.isoformat()}); return items
def news_html(now):
    stale=False
    try: items=latest_news(now)
    except Exception as exc: print(f"주요뉴스 조회 실패: {exc}"); items=load(NEWS_CACHE)["items"]; stale=True
    rows=[]
    for x in items:
        stamp=datetime.fromtimestamp(x.get("published",0),KST).strftime("%m.%d %H:%M") if x.get("published") else ""
        rows.append(f'<li class="news"><a href="{escape(x["link"])}" target="_blank" rel="noopener">{escape(x["title"])}</a><small>{stamp}</small></li>')
    return "".join(rows)+(f'<p class="muted source">실시간 조회 실패로 직전 정상 뉴스</p>' if stale else "")

def main():
    now=datetime.now(KST); kospi,kospi_change=quote("^KS11"); fx,fx_change=quote("KRW=X")
    leaders=[]
    for name,ticker in LEADERS.items():
        try: leaders.append((name,quote(ticker)[1]))
        except Exception: leaders.append((name,0.0))
    tone="강세" if kospi_change>.5 else "약세" if kospi_change<-.5 else "보합권"
    summary=f"코스피는 {kospi:,.2f}로 마감해 전 거래일 대비 {kospi_change:+.2f}%를 기록했습니다. 시장은 {tone} 흐름을 보였습니다."
    investors,health,bond,news=flow_html(now),health_html(now),yield_html(),news_html(now)
    leader_html="".join(f"<li><span>{escape(n)}</span>{signed(p,'%')}</li>" for n,p in leaders)
    style=''':root{--line:#203249;--text:#eef5ff;--muted:#8ea2bb;--up:#ff5d70;--down:#56a8ff;--accent:#5ce1b9}*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#07111f,#0a1524 46%,#07111f);color:var(--text);font-family:Inter,"Noto Sans KR",system-ui,sans-serif}main{width:min(1080px,100%);margin:auto;padding:28px 18px 70px}header{display:flex;justify-content:space-between;gap:20px;align-items:flex-end;padding:18px 0 28px}.eyebrow{color:var(--accent);font-size:12px;font-weight:800;letter-spacing:.14em}h1{font-size:clamp(30px,5vw,52px);margin:8px 0;letter-spacing:-.05em}.muted{color:var(--muted);font-size:13px}.source{margin:12px 0 0}.badge{border:1px solid #2c4b61;border-radius:99px;padding:8px 12px;color:#bdeedc;font-size:12px}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:14px}.card{grid-column:span 4;background:linear-gradient(145deg,#102135ee,#0a1829f5);border:1px solid var(--line);border-radius:20px;padding:20px}.wide{grid-column:span 8}.half{grid-column:span 6}.full{grid-column:1/-1}.label{color:var(--muted);font-size:12px;font-weight:700}.value{font-size:30px;font-weight:800;margin:8px 0 4px}.up{color:var(--up)}.down{color:var(--down)}.flat{color:var(--accent)}h2{font-size:18px;margin:0 0 16px}p{line-height:1.65}.summary{font-size:18px;margin:0}ul{list-style:none;margin:0;padding:0}li{display:flex;justify-content:space-between;gap:14px;padding:13px 0;border-top:1px solid var(--line)}li:first-child{border-top:0;padding-top:0}a{color:#dceaff;text-decoration:none}.news{align-items:flex-start}.news a{flex:1}.news small{color:var(--muted);white-space:nowrap}footer{color:#6f849e;font-size:12px;text-align:center;padding-top:28px}@media(max-width:760px){header{align-items:flex-start;flex-direction:column}.card,.wide,.half{grid-column:1/-1}.card{padding:17px;border-radius:17px}.news{display:block}.news small{display:block;margin-top:6px}}'''
    html=f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KOSPI Closing Brief</title><style>{style}</style></head><body><main><header><div><div class="eyebrow">MARKET CLOSE · KOREA</div><h1>KOSPI Closing Brief</h1><div class="muted">오늘 시장의 핵심 숫자와 이유를 3분 안에</div></div><div><div class="badge">장 마감 리포트</div><div class="muted">{now:%Y.%m.%d %H:%M} KST</div></div></header><section class="grid"><article class="card"><div class="label">KOSPI</div><div class="value">{kospi:,.2f}</div>{signed(kospi_change,'%')}</article><article class="card"><div class="label">USD / KRW</div><div class="value">{fx:,.2f}</div>{signed(fx_change,'%')}</article><article class="card">{bond}</article><article class="card wide"><h2>오늘의 한 문장</h2><p class="summary">{escape(summary)}</p></article><article class="card"><h2>투자자별 수급</h2>{investors}</article><article class="card half"><h2>시가총액 주요 종목</h2><ul>{leader_html}</ul></article><article class="card half"><h2>시장폭 &amp; 기술지표</h2>{health}</article><article class="card full"><h2>주요 뉴스</h2><ul>{news}</ul></article><article class="card half"><h2>실적 &amp; 공시</h2><p class="muted">DART API 연결 후 표시합니다.</p></article><article class="card half"><h2>다음 거래일 관전 포인트</h2><p>미국 증시 · 반도체 · 환율 · 외국인 수급</p></article><article class="card full"><p class="muted">정보 제공 목적이며 투자 권유가 아닙니다. Yahoo Finance, 네이버 금융, KRX 및 Google News RSS 기반.</p></article></section><footer>KOSPI Closing Brief</footer></main></body></html>'''
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(html,encoding="utf-8"); print(summary)

if __name__=="__main__": main()
