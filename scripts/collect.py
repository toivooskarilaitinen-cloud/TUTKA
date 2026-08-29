#!/usr/bin/env python3
"""Collect strictly exceptional news candidates from live news search."""
from __future__ import annotations
import json, re, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/"data"; HISTORY=DATA/"history"
API="https://api.gdeltproject.org/api/v2/doc/doc"
GOOGLE_NEWS="https://news.google.com/rss/search"
QUERIES={
 "KULTTUURI":'(culture OR music OR film OR cinema OR literature OR art) (unexpected OR rare OR unprecedented OR record OR mystery OR resurgence OR breakthrough) sourcelang:english',
 "TEKNOLOGIA":'(technology OR semiconductor OR robotics OR artificial-intelligence OR spaceflight) (unexpected OR rare OR unprecedented OR record OR anomaly OR breakthrough OR reversal) sourcelang:english',
 "TALOUS":'(economy OR markets OR trade OR shipping OR inflation OR employment) (unexpected OR rare OR unprecedented OR record OR divergence OR plunge OR surge OR reversal) sourcelang:english',
 "URHEILU":'(sport OR football OR tennis OR hockey OR baseball OR basketball OR athletics) (unexpected OR rare OR unprecedented OR record OR upset OR streak OR first-ever) sourcelang:english'}
SIGNALS={"unprecedented":24,"first-ever":23,"first ever":23,"all-time":22,"rare":20,"record":18,"anomaly":22,"mystery":18,"unexpected":17,"reversal":19,"divergence":22,"breakthrough":16,"plunge":16,"collapse":17,"surge":13,"resurgence":15,"upset":16,"streak":12,"historic":14,"longest":15,"shortest":15,"largest":14,"smallest":14,"stuns":14}
LOW_VALUE=("live updates","opinion","podcast","newsletter","what to watch","preview","rumour","rumor")
TRUSTED=("reuters.com","apnews.com","bbc.","theguardian.com","ft.com","bloomberg.com","nature.com","science.org","espn.com","theathletic.com")

def fetch_gdelt(category,query):
 params=urllib.parse.urlencode({"query":query,"mode":"artlist","format":"json","maxrecords":75,"timespan":"12h","sort":"datedesc"})
 req=urllib.request.Request(f"{API}?{params}",headers={"User-Agent":"VAIMEA-TUTKA/0.1"})
 with urllib.request.urlopen(req,timeout=20) as response: payload=json.load(response)
 return [{**item,"category":category,"source_domain":urlparse(item.get("url","")).netloc.lower()} for item in payload.get("articles",[])]

def fetch_google_news(category,query):
 params=urllib.parse.urlencode({"q":f"{query.replace(' sourcelang:english','')} when:1d","hl":"en-US","gl":"US","ceid":"US:en"})
 req=urllib.request.Request(f"{GOOGLE_NEWS}?{params}",headers={"User-Agent":"Mozilla/5.0 (compatible; VAIMEA-TUTKA/0.2)"})
 with urllib.request.urlopen(req,timeout=20) as response: root=ET.fromstring(response.read())
 articles=[]
 for item in root.findall("./channel/item")[:75]:
  source=item.find("source"); source_url=source.get("url","") if source is not None else ""
  publisher=source.text if source is not None else ""; title=item.findtext("title",default="")
  if publisher and title.endswith(f" - {publisher}"): title=title[:-(len(publisher)+3)]
  articles.append({"category":category,"title":title,"url":item.findtext("link",default=""),"source_domain":urlparse(source_url).netloc.lower(),"publisher":publisher})
 return articles

def fetch(category,query):
 try:
  items=fetch_gdelt(category,query)
  if items: return items,"GDELT"
 except Exception as primary_error:
  primary=f"{type(primary_error).__name__}"
 else:
  primary="empty response"
 items=fetch_google_news(category,query)
 if not items: raise RuntimeError(f"GDELT {primary}; Google News empty response")
 return items,"Google News"

def words(title): return {w for w in re.findall(r"[a-z0-9]+",title.lower()) if len(w)>3}
def similarity(a,b):
 left,right=words(a),words(b); return len(left&right)/max(1,len(left|right))
def kind(title):
 t=title.lower()
 if any(x in t for x in ("record","first-ever","first ever","all-time","longest","shortest")): return "RECORD WATCH"
 if any(x in t for x in ("divergence","reversal","despite","while")): return "DIVERGENCE"
 if any(x in t for x in ("rare","mystery","strange","unusual")): return "ODDITY"
 if any(x in t for x in ("anomaly","unprecedented","plunge","collapse")): return "ANOMALY"
 return "SIGNAL"
def score(article,peers):
 title=article.get("title",""); lower=title.lower(); points=45+sum(v for k,v in SIGNALS.items() if re.search(rf"\b{re.escape(k)}\b",lower))
 domain=article.get("source_domain") or urlparse(article.get("url","")).netloc.lower()
 if any(source in domain for source in TRUSTED): points+=7
 corroborating={(p.get("source_domain") or urlparse(p.get("url","")).netloc) for p in peers if p is not article and similarity(title,p.get("title",""))>=.42}
 corroborating.discard("")
 return min(99,points+min(14,len(corroborating)*5)),len(corroborating)+1
def question(category): return {"KULTTUURI":"Miksi tämä ilmiö poikkeaa kulttuurin tavallisesta kierrosta?","TEKNOLOGIA":"Onko tämä yksittäinen havainto vai merkki teknologisen suunnan muutoksesta?","TALOUS":"Mitä tämä kertoo ennen kuin tavalliset talousmittarit ehtivät reagoida?","URHEILU":"Onko kyse aidosta poikkeamasta vai nopeasti korjaantuvasta sattumasta?"}[category]

def main():
 DATA.mkdir(exist_ok=True); HISTORY.mkdir(exist_ok=True); raw=[]; errors=[]; providers={}
 for category,query in QUERIES.items():
  try:
   items,provider=fetch(category,query); raw.extend(items); providers[category]=provider
  except Exception as exc: errors.append(f"{category}: {type(exc).__name__}: {str(exc)[:120]}")
  time.sleep(2)
 grouped=defaultdict(list)
 for item in raw: grouped[item["category"]].append(item)
 candidates=[]
 for item in raw:
  title=re.sub(r"\s+"," ",item.get("title","")).strip()
  if len(title)<35 or any(term in title.lower() for term in LOW_VALUE): continue
  value,sources=score(item,grouped[item["category"]])
  if value<75: continue
  domain=item.get("source_domain") or urlparse(item.get("url","")).netloc.lower()
  if not any(trusted in domain for trusted in TRUSTED) and sources<2: continue
  source=item.get("publisher") or (item.get("source_domain") or urlparse(item.get("url","")).netloc).removeprefix("www.")
  candidates.append({"category":item["category"],"type":kind(title),"score":value,"title":title,"question":question(item["category"]),"why":f"Otsikossa on poikkeavuussignaali ja havaintoa tukee {sources} toisistaan riippumatonta uutislähdettä tai historiallista avainsanaa.","source":source,"url":item.get("url",""),"age":"TUORE"})
 chosen=[]; counts=defaultdict(int); seen=[]
 for item in sorted(candidates,key=lambda x:x["score"],reverse=True):
  if counts[item["category"]]>=2 or any(similarity(item["title"],t)>=.5 for t in seen): continue
  counts[item["category"]]+=1; seen.append(item["title"]); chosen.append(item)
  if len(chosen)==8: break
 for index,item in enumerate(chosen,1): item["id"]=f"{index:02d}"
 now=datetime.now(timezone.utc); date=now.date().isoformat(); snapshot={"date":date,"generated_at":now.isoformat(),"updated":now.strftime("%H:%M UTC"),"rejected":max(0,len(raw)-len(chosen)),"findings":chosen,"errors":errors,"providers":providers,"method_version":"v0.3"}
 text=json.dumps(snapshot,ensure_ascii=False,indent=2); (DATA/"latest.json").write_text(text,encoding="utf-8"); (HISTORY/f"{date}.json").write_text(text,encoding="utf-8")
 entries=[]
 for path in sorted(HISTORY.glob("*.json"),reverse=True):
  try:
   day=json.loads(path.read_text(encoding="utf-8")); entries.append({"date":day["date"],"count":len(day.get("findings",[])),"file":f"history/{path.name}"})
  except Exception: pass
 (DATA/"archive.json").write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding="utf-8")
 print(f"TUTKA: {len(chosen)} published, {snapshot['rejected']} rejected, {len(errors)} errors")
if __name__=="__main__": main()

