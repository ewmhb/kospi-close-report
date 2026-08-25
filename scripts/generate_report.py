from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo
import json, os, re, time, urllib.parse, urllib.request

import feedparser
import yfinance as yf
from pykrx import stock

KST = ZoneInfo("Asia/Seoul")
OUT, CACHE = Path("site/index.html"), Path("work/cache")
FLOW_CACHE, BREADTH_CACHE = CACHE / "investor-flow.json", CACHE / "market-breadth.json"
YIELD_CACHE, NEWS_CACHE = CACHE / "korea-10y-yield.json", CACHE / "news.json"
DATA_WARNINGS=[]
LEADERS = {"삼성전자":("005930","005930.KS"),"SK하이닉스":("000660","000660.KS"),"현대차":("005380","005380.KS"),"삼성바이오로직스":("207940","207940.KS"),"LG에너지솔루션":("373220","373220.KS")}
SECTORS = {
    "반도체":("091230.KS",[("삼성전자","005930.KS"),("SK하이닉스","000660.KS"),("DB하이텍","000990.KS")]),
    "건설":("117700.KS",[("현대건설","000720.KS"),("GS건설","006360.KS"),("대우건설","047040.KS")]),
    "바이오·헬스케어":("143860.KS",[("삼성바이오로직스","207940.KS"),("셀트리온","068270.KS"),("SK바이오팜","326030.KS")]),
    "자동차":("091180.KS",[("현대차","005380.KS"),("기아","000270.KS"),("현대모비스","012330.KS")]),
    "2차전지":("305720.KS",[("LG에너지솔루션","373220.KS"),("삼성SDI","006400.KS"),("포스코퓨처엠","003670.KS")]),
    "금융":("091170.KS",[("KB금융","105560.KS"),("신한지주","055550.KS"),("하나금융지주","086790.KS")]),
}

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
def quote_history(ticker):
    frame=yf.download(ticker, period="6mo", progress=False, auto_adjust=False)
    close=frame["Close"].dropna(); values=close.to_numpy().reshape(-1)
    if len(values)<2: raise RuntimeError(f"시세 시계열 부족: {ticker}")
    history=[{"date":date.strftime("%Y.%m.%d"),"value":float(value)} for date,value in zip(close.index,values)]
    return float(values[-1]), (float(values[-1])/float(values[-2])-1)*100, history
def signed(value, suffix="", label=None):
    css="up" if value>0 else "down" if value<0 else "flat"; arrow="▲" if value>0 else "▼" if value<0 else "–"
    text=f"{abs(value):,.0f}" if suffix in ("억원","주") else f"{abs(value):,.2f}"
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

def breadth_naver(now):
    raw=fetch("https://finance.naver.com/sise/sise_index.naver?code=KOSPI", "euc-kr")
    text=re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", raw)))
    values={}
    for key in ("상승","보합","하락"):
        match=re.search(key+r"종목수\s*(\d+)", text)
        if not match: raise RuntimeError(f"네이버 시장폭 {key} 데이터 없음")
        values[key]=int(match.group(1))
    total=sum(values.values())
    return {"date":now.strftime("%m.%d"),"up":values["상승"],"down":values["하락"],"flat":values["보합"],"ratio":round(values["상승"]/total*100,1),"source":"네이버 금융"}

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
    b=None
    for fn in (breadth_naver,breadth_krx):
        try: b=fn(now); save(BREADTH_CACHE,b); break
        except Exception as exc: print(f"시장폭 조회 실패: {exc}")
    if b is None:
        try: b=load(BREADTH_CACHE); stale=True
        except Exception: pass
    try: t=technical()
    except Exception as exc: print(f"기술지표 조회 실패: {exc}"); t=None
    rows=""
    if b: rows=f'<li><span>상승 / 하락</span><strong>{b["up"]} / {b["down"]}</strong></li><li><span>보합 · 상승비율</span><strong>{b["flat"]} · {b["ratio"]:.1f}%</strong></li>'
    if t:
        rows+=f'<li><span>20일선</span><strong>{t["ma20"]:,.2f} · {"상회" if t["current"]>=t["ma20"] else "하회"}</strong></li><li><span>60일선</span><strong>{t["ma60"]:,.2f} · {"상회" if t["current"]>=t["ma60"] else "하회"}</strong></li><li><span>RSI(14)</span><strong>{t["rsi"]:.1f}</strong></li>'
    source=f'<p class="muted source">{b["date"]} · {b.get("source","저장값")}{" · 실시간 조회 실패로 직전 정상값" if stale else ""}</p>' if b else '<p class="muted source">시장폭 조회 실패 · 기술지표는 정상 표시</p>'
    return f'<ul>{rows}</ul>{source}'

def leader_history_naver(code):
    p=TableRows(); p.feed(fetch(f"https://finance.naver.com/item/frgn.naver?code={code}&page=1","euc-kr")); data=[]
    for row in p.rows:
        if len(row)>=7 and re.fullmatch(r"\d{4}\.\d{2}\.\d{2}",row[0]):
            close=int(row[1].replace(",","")); institution=int(row[5].replace(",","").replace("+","")); foreign=int(row[6].replace(",","").replace("+","")); personal=-(institution+foreign)
            data.append((row[0][5:],close,personal,foreign,institution))
    if len(data)<5: raise RuntimeError("네이버증권 최근 5거래일 데이터 없음")
    return data[:5],"네이버증권 · 개인은 기관·외국인 순매매량의 반대값으로 계산"


def leader_history_krx(code, now):
    start=(now.date()-timedelta(days=16)).strftime("%Y%m%d"); end=now.strftime("%Y%m%d")
    prices=stock.get_market_ohlcv_by_date(start,end,code); flows=stock.get_market_trading_volume_by_date(start,end,code)
    if prices is None or prices.empty or flows is None or flows.empty: raise RuntimeError("KRX 최근 데이터 없음")
    merged=prices[["종가"]].join(flows,how="left").tail(5); data=[]
    for day,row in reversed(list(merged.iterrows())):
        personal=round(float(row.get("개인",0))); foreign=round(float(row.get("외국인합계",row.get("외국인",0)))); institution=round(float(row.get("기관합계",row.get("기관",0))))
        data.append((day.strftime("%m.%d"),round(float(row["종가"])),personal,foreign,institution))
    return data,"KRX"


def leader_history_html(code, now):
    data=None; source=""
    for index,fn in enumerate((lambda:leader_history_naver(code),lambda:leader_history_krx(code,now))):
        try:
            data,source=fn()
            if index: DATA_WARNINGS.append(f"{code} KRX 대체")
            break
        except Exception as exc: print(f"종목 5일 데이터 조회 실패({code}): {exc}")
    if not data:
        DATA_WARNINGS.append(f"{code} 상세 조회 실패")
        return '<div class="muted stock-error">최근 5거래일 상세 데이터를 불러오지 못했습니다.</div>'
    rows="".join(f'<tr><td>{day}</td><td class="num">{close:,.0f}원</td><td>{signed(personal,"주")}</td><td>{signed(foreign,"주")}</td><td>{signed(institution,"주")}</td></tr>' for day,close,personal,foreign,institution in data)
    return '<div class="stock-table-wrap"><table class="stock-table"><thead><tr><th>날짜</th><th>종가</th><th>개인(추정)</th><th>외국인</th><th>기관</th></tr></thead><tbody>'+rows+f'</tbody></table><div class="muted stock-note">순매수량 · 단위: 주 · {source}</div></div>'


def sector_html():
    all_tickers=[]
    for sector_ticker,candidates in SECTORS.values(): all_tickers.extend([sector_ticker]+[ticker for _,ticker in candidates])
    frame=yf.download(sorted(set(all_tickers)),period="10d",progress=False,auto_adjust=False,group_by="ticker",threads=True)
    changes={}
    for ticker in set(all_tickers):
        try:
            values=frame[ticker]["Close"].dropna().to_numpy().reshape(-1)
            if len(values)>=2: changes[ticker]=(float(values[-1])/float(values[-2])-1)*100
        except Exception as exc: print(f"섹터 구성 종목 조회 실패({ticker}): {exc}")
    cards=[]
    for sector,(sector_ticker,candidates) in SECTORS.items():
        sector_change=changes.get(sector_ticker,0.0)
        if sector_ticker not in changes: DATA_WARNINGS.append(f"{sector} 섹터 조회 실패")
        available=[(name,changes[ticker]) for name,ticker in candidates if ticker in changes]
        stock_name,stock_change=max(available,key=lambda x:abs(x[1])) if available else ("조회 실패",0.0)
        cards.append(f'<div class="sector-item"><div class="sector-head"><strong>{escape(sector)}</strong>{signed(sector_change,"%")}</div><div class="sector-stock"><span>오늘의 주요 종목 · {escape(stock_name)}</span>{signed(stock_change,"%")}</div></div>')
    return '<div class="sector-grid">'+"".join(cards)+'</div><p class="muted source">섹터 등락률은 국내 섹터 ETF 기준 · 주요 종목은 후보군 중 당일 절대 등락률이 가장 큰 종목이며 투자 추천이 아닙니다.</p>',changes


def korea_10y_naver():
    history=[]
    for page in range(1,7):
        p=TableRows(); p.feed(fetch("https://finance.naver.com/marketindex/interestDailyQuote.naver?marketindexCd=IRR_GOVT10Y"+f"&page={page}", "euc-kr"))
        for row in p.rows:
            if len(row)>=2 and re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", row[0]):
                history.append({"date":row[0],"value":float(row[1].replace(",",""))})
    history=sorted({x["date"]:x for x in history}.values(),key=lambda x:x["date"])
    if len(history)<2: raise RuntimeError("한국 국고채 10년물 시계열 없음")
    return {"date":history[-1]["date"][5:],"value":history[-1]["value"],"change":history[-1]["value"]-history[-2]["value"],"history":history,"source":"네이버 금융"}
def korea_10y_ecos():
    api_key=os.environ.get("ECOS_API_KEY")
    if not api_key: raise RuntimeError("ECOS_API_KEY 미설정")
    end=datetime.now(KST).date(); start=end-timedelta(days=150)
    url=(f"https://ecos.bok.or.kr/api/StatisticSearch/{api_key}/json/kr/1/200/817Y002/D/"
         f"{start:%Y%m%d}/{end:%Y%m%d}/010210000")
    payload=json.loads(fetch(url)); rows=payload.get("StatisticSearch",{}).get("row",[])
    history=[{"date":f'{x["TIME"][:4]}.{x["TIME"][4:6]}.{x["TIME"][6:8]}',"value":float(x["DATA_VALUE"])} for x in rows]
    history=sorted(history,key=lambda x:x["date"])
    if len(history)<2: raise RuntimeError("한국은행 ECOS 국고채 10년물 시계열 없음")
    return {"date":history[-1]["date"][5:],"value":history[-1]["value"],"change":history[-1]["value"]-history[-2]["value"],"history":history,"source":"한국은행 ECOS"}
def korea_10y_tooly():
    p=TableRows(); p.feed(fetch("https://tooly.deluxo.co.kr/data/rates/treasury-10y"))
    history=[]
    for row in p.rows:
        if len(row)>=2 and re.fullmatch(r"\d{4}-\d{2}",row[0]):
            history.append({"date":row[0],"value":float(row[1].replace("%",""))})
    history=sorted({x["date"]:x for x in history}.values(),key=lambda x:x["date"])
    if len(history)<2: raise RuntimeError("ECOS 월평균 국고채 10년물 시계열 없음")
    return {"date":history[-1]["date"],"value":history[-1]["value"],"change":history[-1]["value"]-history[-2]["value"],"history":history,"source":"한국은행 ECOS 월평균 · Tooly"}
def korea_10y_yahoo():
    f=yf.download("KR10YT=RR", period="6mo", progress=False, auto_adjust=False)
    values=f["Close"].dropna().to_numpy().reshape(-1)
    if len(values)<2: raise RuntimeError("Yahoo 한국 국채 10년물 데이터 없음")
    dates=[x.strftime("%Y.%m.%d") for x in f["Close"].dropna().index]
    history=[{"date":date,"value":float(value)} for date,value in zip(dates,values)]
    return {"date":dates[-1][5:],"value":float(values[-1]),"change":float(values[-1]-values[-2]),"history":history,"source":"Yahoo Finance"}
def trend_chart(history, aria_label, value_format):
    points=history[-60:]
    if len(points)<2: return '<div class="muted chart-empty">추이 데이터 없음</div>'
    values=[x["value"] for x in points]; low=min(values); high=max(values); span=max(high-low,.05)
    coords=[]
    for i,value in enumerate(values):
        x=8+i*464/(len(values)-1); y=112-(value-low)*88/span
        coords.append(f"{x:.1f},{y:.1f}")
    return f'''<div class="trend-chart"><svg viewBox="0 0 480 128" role="img" aria-label="{aria_label}"><line x1="8" y1="112" x2="472" y2="112" class="chart-axis"/><polyline points="{' '.join(coords)}" class="chart-line"/><circle cx="{coords[-1].split(',')[0]}" cy="{coords[-1].split(',')[1]}" r="4" class="chart-dot"/><text x="8" y="18">{value_format.format(high)}</text><text x="8" y="126">{points[0]['date'][5:]}</text><text x="472" y="126" text-anchor="end">{points[-1]['date'][5:]}</text></svg></div>'''
def yield_html():
    stale=False
    d=None
    for fn in (korea_10y_ecos,korea_10y_tooly,korea_10y_naver,korea_10y_yahoo):
        try: d=fn(); save(YIELD_CACHE,d); break
        except Exception as exc: print(f"한국 국채 10년물 조회 실패: {exc}")
    if d is None:
        try: d=load(YIELD_CACHE); stale=True; DATA_WARNINGS.append("국고채 저장값 사용")
        except Exception: return '<div class="label">한국 국채 10년물</div><div class="value">–</div><div class="muted">조회 실패</div>'
    if "월평균" in d.get("source",""): DATA_WARNINGS.append("국고채 월평균")
    chart=trend_chart(d.get("history",[]),"한국 국고채 10년물 금리 추이","{:.2f}%")
    return f'<div class="label">한국 국고채 10년물</div><div class="value">{d["value"]:.3f}%</div>{signed(d.get("change",0),"%p")}{chart}<div class="muted">최근 추이 · {d["date"]} · {d.get("source","저장값")}{" · 직전 정상값" if stale else ""}</div>'

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
    except Exception as exc:
        print(f"주요뉴스 조회 실패: {exc}")
        try: items=load(NEWS_CACHE)["items"]; stale=True
        except Exception: return '<li><span class="muted">주요 뉴스를 불러오지 못했습니다.</span></li>'
    rows=[]
    for x in items:
        stamp=datetime.fromtimestamp(x.get("published",0),KST).strftime("%m.%d %H:%M") if x.get("published") else ""
        rows.append(f'<li class="news"><a href="{escape(x["link"])}" target="_blank" rel="noopener">{escape(x["title"])}</a><small>{stamp}</small></li>')
    return "".join(rows)+(f'<p class="muted source">실시간 조회 실패로 직전 정상 뉴스</p>' if stale else "")


def watchpoints(kospi_change, fx_change, sector_changes):
    points=[]
    if abs(kospi_change)>=1: points.append(f'KOSPI 변동성 확대({kospi_change:+.2f}%) 이후 방향성')
    if abs(fx_change)>=.3: points.append(f'원·달러 환율 변동({fx_change:+.2f}%)과 외국인 수급')
    sector_moves=[(name,sector_changes.get(info[0])) for name,info in SECTORS.items() if info[0] in sector_changes]
    if sector_moves:
        name,change=max(sector_moves,key=lambda x:abs(x[1])); points.append(f'{name} 섹터 강도({change:+.2f}%) 지속 여부')
    points.append('외국인·기관 수급의 연속성')
    return " · ".join(points[:3])


def status_html():
    unique=list(dict.fromkeys(DATA_WARNINGS))
    if not unique: return '<div class="status ok">모든 데이터 정상</div>'
    return f'<div class="status warn" title="{escape(" · ".join(unique))}">일부 대체 데이터 · {len(unique)}건</div>'


def validate_report(html, now):
    checks={
        "그래프 3개":html.count('class="trend-chart"')==3,
        "섹터 6개":html.count('class="sector-item"')==6,
        "주요 종목 상세 5개":html.count('class="stock-detail"')==5,
        "리포트 기준일":now.strftime("%Y.%m.%d") in html,
        "KOSPI 값":"<div class=\"label\">KOSPI</div><div class=\"value\">" in html,
        "환율 값":"<div class=\"label\">USD / KRW</div><div class=\"value\">" in html,
    }
    failed=[name for name,ok in checks.items() if not ok]
    if failed: raise RuntimeError("발송 전 리포트 검사 실패: "+", ".join(failed))

def main():
    now=datetime.now(KST); kospi,kospi_change,kospi_history=quote_history("^KS11"); fx,fx_change,fx_history=quote_history("KRW=X")
    leaders=[]
    for name,(code,ticker) in LEADERS.items():
        try: leaders.append((name,code,quote(ticker)[1]))
        except Exception: leaders.append((name,code,0.0))
    tone="강세" if kospi_change>.5 else "약세" if kospi_change<-.5 else "보합권"
    summary=f"코스피는 {kospi:,.2f}로 마감해 전 거래일 대비 {kospi_change:+.2f}%를 기록했습니다. 시장은 {tone} 흐름을 보였습니다."
    investors,health,bond,news=flow_html(now),health_html(now),yield_html(),news_html(now)
    sectors,sector_changes=sector_html(); watch=watchpoints(kospi_change,fx_change,sector_changes)
    kospi_chart=trend_chart(kospi_history,"KOSPI 최근 60거래일 추이","{:,.0f}")
    fx_chart=trend_chart(fx_history,"원·달러 환율 최근 60거래일 추이","{:,.0f}원")
    leader_html="".join(f'<li class="leader-row"><details class="stock-detail"><summary><span>{escape(n)}</span>{signed(p,"%")}</summary>{leader_history_html(code,now)}</details></li>' for n,code,p in leaders)
    stock_style='''.leader-row{display:block}.stock-detail{width:100%}.stock-detail summary{display:flex;justify-content:space-between;gap:14px;cursor:pointer;list-style:none}.stock-detail summary::-webkit-details-marker{display:none}.stock-detail summary span:first-child:before{content:"＋";color:var(--accent);margin-right:8px}.stock-detail[open] summary span:first-child:before{content:"－"}.stock-table-wrap{overflow-x:auto;margin-top:14px;padding-top:12px;border-top:1px solid var(--line)}.stock-table{width:100%;min-width:520px;border-collapse:collapse;font-size:12px}.stock-table th,.stock-table td{padding:9px 7px;text-align:right;white-space:nowrap;border-bottom:1px solid #1b3047}.stock-table th:first-child,.stock-table td:first-child{text-align:left}.stock-table th{color:var(--muted);font-weight:700}.stock-table .num{color:var(--text);font-weight:700}.stock-note{margin-top:9px;text-align:right}.stock-error{padding:16px 0 4px}'''
    stock_style+='''.sector-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.sector-item{border:1px solid var(--line);border-radius:14px;padding:14px;background:#0b1929}.sector-head,.sector-stock{display:flex;justify-content:space-between;align-items:center;gap:10px}.sector-head strong{font-size:15px}.sector-stock{margin-top:10px;padding-top:10px;border-top:1px solid #1b3047;color:var(--muted);font-size:12px}.sector-stock .up,.sector-stock .down,.sector-stock .flat{font-size:12px;white-space:nowrap}@media(max-width:760px){.sector-grid{grid-template-columns:1fr 1fr}}@media(max-width:480px){.sector-grid{grid-template-columns:1fr}}'''
    stock_style+='''.status{margin-top:8px;border-radius:99px;padding:6px 10px;font-size:11px;text-align:center}.status.ok{color:#bdeedc;border:1px solid #2c5b50;background:#0c2a24}.status.warn{color:#ffd38b;border:1px solid #6b512b;background:#2a2112}'''
    style=''':root{--line:#203249;--text:#eef5ff;--muted:#8ea2bb;--up:#ff5d70;--down:#56a8ff;--accent:#5ce1b9}*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#07111f,#0a1524 46%,#07111f);color:var(--text);font-family:Inter,"Noto Sans KR",system-ui,sans-serif}main{width:min(1080px,100%);margin:auto;padding:28px 18px 70px}header{display:flex;justify-content:space-between;gap:20px;align-items:flex-end;padding:18px 0 28px}.eyebrow{color:var(--accent);font-size:12px;font-weight:800;letter-spacing:.14em}h1{font-size:clamp(30px,5vw,52px);margin:8px 0;letter-spacing:-.05em}.muted{color:var(--muted);font-size:13px}.source{margin:12px 0 0}.badge{border:1px solid #2c4b61;border-radius:99px;padding:8px 12px;color:#bdeedc;font-size:12px}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:14px}.card{grid-column:span 4;background:linear-gradient(145deg,#102135ee,#0a1829f5);border:1px solid var(--line);border-radius:20px;padding:20px}.wide{grid-column:span 8}.half{grid-column:span 6}.full{grid-column:1/-1}.label{color:var(--muted);font-size:12px;font-weight:700}.value{font-size:30px;font-weight:800;margin:8px 0 4px}.up{color:var(--up)}.down{color:var(--down)}.flat{color:var(--accent)}.trend-chart{margin:12px 0 8px}.trend-chart svg{display:block;width:100%;height:auto;overflow:visible}.trend-chart text{fill:var(--muted);font-size:10px}.chart-axis{stroke:#29415b;stroke-width:1}.chart-line{fill:none;stroke:var(--accent);stroke-width:3;stroke-linecap:round;stroke-linejoin:round}.chart-dot{fill:var(--accent);stroke:#dffff6;stroke-width:2}.chart-empty{padding:24px 0}h2{font-size:18px;margin:0 0 16px}p{line-height:1.65}.summary{font-size:18px;margin:0}ul{list-style:none;margin:0;padding:0}li{display:flex;justify-content:space-between;gap:14px;padding:13px 0;border-top:1px solid var(--line)}li:first-child{border-top:0;padding-top:0}a{color:#dceaff;text-decoration:none}.news{align-items:flex-start}.news a{flex:1}.news small{color:var(--muted);white-space:nowrap}footer{color:#6f849e;font-size:12px;text-align:center;padding-top:28px}@media(max-width:760px){header{align-items:flex-start;flex-direction:column}.card,.wide,.half{grid-column:1/-1}.card{padding:17px;border-radius:17px}.news{display:block}.news small{display:block;margin-top:6px}}'''
    html=f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KOSPI Closing Brief</title><style>{style}</style></head><body><main><header><div><div class="eyebrow">MARKET CLOSE · KOREA</div><h1>KOSPI Closing Brief</h1><div class="muted">오늘 시장의 핵심 숫자와 이유를 3분 안에</div></div><div><div class="badge">장 마감 리포트</div><div class="muted">{now:%Y.%m.%d %H:%M} KST</div></div></header><section class="grid"><article class="card"><div class="label">KOSPI</div><div class="value">{kospi:,.2f}</div>{signed(kospi_change,'%')}</article><article class="card"><div class="label">USD / KRW</div><div class="value">{fx:,.2f}</div>{signed(fx_change,'%')}</article><article class="card">{bond}</article><article class="card wide"><h2>오늘의 한 문장</h2><p class="summary">{escape(summary)}</p></article><article class="card"><h2>투자자별 수급</h2>{investors}</article><article class="card half"><h2>시가총액 주요 종목</h2><ul>{leader_html}</ul></article><article class="card half"><h2>시장폭 &amp; 기술지표</h2>{health}</article><article class="card full"><h2>주요 뉴스</h2><ul>{news}</ul></article><article class="card half"><h2>실적 &amp; 공시</h2><p class="muted">DART API 연결 후 표시합니다.</p></article><article class="card half"><h2>다음 거래일 관전 포인트</h2><p>미국 증시 · 반도체 · 환율 · 외국인 수급</p></article><article class="card full"><p class="muted">정보 제공 목적이며 투자 권유가 아닙니다. Yahoo Finance, 네이버 금융, KRX 및 Google News RSS 기반.</p></article></section><footer>KOSPI Closing Brief</footer></main></body></html>'''
    html=html.replace("</style>",stock_style+"</style>",1).replace(
        f'<div class="value">{kospi:,.2f}</div>{signed(kospi_change,"%")}</article>',
        f'<div class="value">{kospi:,.2f}</div>{signed(kospi_change,"%")}{kospi_chart}<div class="muted">최근 60거래일</div></article>',
        1,
    ).replace(
        f'<div class="value">{fx:,.2f}</div>{signed(fx_change,"%")}</article>',
        f'<div class="value">{fx:,.2f}</div>{signed(fx_change,"%")}{fx_chart}<div class="muted">최근 60거래일</div></article>',
        1,
    )
    html=html.replace(
        f'<article class="card full"><h2>주요 뉴스</h2><ul>{news}</ul></article><article class="card half"><h2>실적 &amp; 공시</h2><p class="muted">DART API 연결 후 표시합니다.</p></article>',
        f'<article class="card full"><h2>섹터 현황</h2>{sectors}</article><article class="card half"><h2>주요 뉴스</h2><ul>{news}</ul></article>',
        1,
    )
    html=html.replace('<div class="badge">장 마감 리포트</div>','<div class="badge">장 마감 리포트</div>'+status_html(),1)
    html=html.replace('<p>미국 증시 · 반도체 · 환율 · 외국인 수급</p>',f'<p>{escape(watch)}</p>',1)
    validate_report(html,now)
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(html,encoding="utf-8"); print(summary)

if __name__=="__main__": main()
