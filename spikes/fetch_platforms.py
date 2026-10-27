import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import httpx
from envload import load_env

env = load_env()
UA = env.get("HTTP_USER_AGENT") or "Mozilla/5.0"
KEY = env["TAVILY_API_KEY"]
OUT = Path(__file__).parent.parent / "backend" / "tests" / "fixtures" / "pages"
OUT.mkdir(parents=True, exist_ok=True)
PRODUCTS = ["2 mL disposable syringe with needle", "3-ply surgical face mask",
            "nitrile examination gloves size M powder-free", "IV cannula 20G", "urine bag 2000 mL"]
PLATFORMS = {"indiamart": "indiamart.com", "tradeindia": "tradeindia.com", "exportersindia": "exportersindia.com"}
SKIP = list(PLATFORMS.values()) + ["amazon", "flipkart", "alibaba", "youtube", "wikipedia"]
PRICE = re.compile(r"(₹|Rs\.?\s?\d|INR)")


def tavily_search(q, domains=None):
    body = {"api_key": KEY, "query": q, "max_results": 8}
    if domains:
        body["include_domains"] = domains
    r = httpx.post("https://api.tavily.com/search", json=body, timeout=40)
    return r.status_code, (r.json().get("results", []) if r.status_code == 200 else r.text[:200])


def trim(html):
    html = re.sub(r"<script\b(?![^>]*ld\+json)[^>]*>.*?</script>", "", html, flags=re.S | re.I)
    html = re.sub(r"<style\b[^>]*>.*?</style>", "", html, flags=re.S | re.I)
    html = re.sub(r"<svg\b.*?</svg>", "", html, flags=re.S | re.I)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    return html[:290_000]


def direct(url):
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=15, follow_redirects=True)
        return r.status_code, r.text
    except Exception as e:
        return type(e).__name__, ""


def extract(url):
    try:
        r = httpx.post("https://api.tavily.com/extract", json={"api_key": KEY, "urls": [url]}, timeout=60)
        if r.status_code != 200:
            return r.status_code, ""
        res = r.json().get("results", [])
        return 200, (res[0].get("raw_content") or "") if res else ""
    except Exception as e:
        return type(e).__name__, ""


targets = []  # (platform, url)
for name, dom in PLATFORMS.items():
    seen = []
    for p in PRODUCTS:
        st, res = tavily_search(p + " price manufacturer", [dom])
        if st != 200 or not isinstance(res, list):
            print("search fail", name, st, res); break
        for x in res:
            if x["url"] not in seen and len(seen) < 2:
                seen.append(x["url"])
        if len(seen) >= 2:
            break
    targets += [(name, u) for u in seen]
seen = []
for p in PRODUCTS:
    st, res = tavily_search(p + " manufacturer India factory price")
    for x in res if isinstance(res, list) else []:
        if not any(s in x["url"] for s in SKIP) and len(seen) < 2:
            seen.append(x["url"])
    if len(seen) >= 2:
        break
targets += [("manufacturer", u) for u in seen]

# product-detail pages found by hand-run Tavily searches (listing pages above are category pages)
targets += [("indiamart", "https://www.indiamart.com/proddetail/black-nitrile-examination-gloves-powder-free-manufacturer-for-medical-industrial-salon-use-2857901876988.html"), ("indiamart", "https://www.indiamart.com/proddetail/iv-cannula-20g-pink-2849116819233.html"), ("tradeindia", "https://www.tradeindia.com/products/pvc-urine-collection-bag-with-hanger-2-liter-capacity-naif-shubham-7718123.html"), ("manufacturer", "https://banshimedicare.com/gloves/nitrile-gloves-manufacturer")]
targets = [t for t in targets if not t[1].endswith(".pdf")]
counts = {}
for plat, url in targets:
    n = counts[plat] = counts.get(plat, 0) + 1
    ds, dhtml = direct(url)
    es, etext = extract(url)
    dp = bool(PRICE.search(dhtml)); ep = bool(PRICE.search(etext))
    print(f"{plat}_{n} {url}\n   direct: {ds} {len(dhtml.encode())}B price={dp} | extract: {es} {len(etext.encode())}B price={ep}")
    if ds == 200 and dhtml:
        (OUT / f"{plat}_{n}.html").write_text(trim(dhtml), encoding="utf-8")
    elif etext:
        # extract-only fallback: saved as text wrapped in html, marked
        (OUT / f"{plat}_{n}_extract.html").write_text("<!-- tavily extract text; direct fetch failed -->\n<pre>" + etext[:290_000] + "</pre>", encoding="utf-8")
