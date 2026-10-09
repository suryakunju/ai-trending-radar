"""Daily AI repo radar for AI with Surya.

Uses GitHub's official search API (no scraping) to find Python repos that are
gaining stars, keeps a daily star history, and writes:
  data/trending.md    - the list the morning report reads
  data/trending.json  - same list, machine-readable
  data/stars.json     - star history used to work out "stars today"
Only the Python standard library is used.
"""
import datetime as dt
import json
import os
import pathlib
import time
import urllib.parse
import urllib.request

DATA = pathlib.Path("data")
HISTORY_FILE = DATA / "stars.json"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
TODAY = dt.datetime.now(dt.timezone.utc).date()
KEEP_DAYS = 21       # how long star history is kept
WATCH_DAYS = 10      # repos not seen by any search for this long drop off
TOP_N = 40

AI_WORDS = [
    "ai", "llm", "agent", "agents", "agentic", "gpt", "claude", "gemini", "openai",
    "anthropic", "rag", "mcp", "model", "models", "transformer", "diffusion",
    "embedding", "embeddings", "inference", "fine-tune", "finetune", "fine-tuning",
    "machine-learning", "deep-learning", "neural", "multimodal", "vision", "speech",
    "voice", "tts", "asr", "chatbot", "copilot", "prompt", "reasoning", "robot",
    "robotics", "data", "analytics", "dataset", "vector", "retrieval", "automation",
    "workflow", "nlp", "ocr", "genai", "generative", "lora", "vllm", "ollama",
]


def days_ago(n):
    return (TODAY - dt.timedelta(days=n)).isoformat()


# Each query returns up to 100 repos. Together they form the day's watch list.
QUERIES = [
    f"language:python created:>={days_ago(7)} stars:>=20",
    f"language:python created:>={days_ago(30)} stars:>=100",
    f"language:python created:>={days_ago(120)} stars:>=500",
    f"language:python pushed:>={days_ago(2)} stars:>=1000 created:>={days_ago(365)}",
]
for topic in ["llm", "ai-agents", "agents", "mcp", "rag", "generative-ai",
              "large-language-models", "agentic-ai", "llm-agent", "robotics"]:
    QUERIES.append(f"language:python topic:{topic} pushed:>={days_ago(3)} stars:>=200")


def search(query):
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
        {"q": query, "sort": "stars", "order": "desc", "per_page": 100})
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ai-trending-radar",
        **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}),
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r).get("items", [])
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and attempt < 2:
                time.sleep(30)  # search API limit is 30 calls a minute
                continue
            print(f"Query failed ({e.code}): {query}")
            return []
        except Exception as e:  # network hiccup
            print(f"Query error: {query}: {e}")
            time.sleep(5)
    return []


def is_ai(repo):
    text = " ".join([
        repo.get("name") or "", repo.get("description") or "",
        " ".join(repo.get("topics") or []),
    ]).lower().replace("_", "-")
    words = set(text.replace("/", " ").replace(",", " ").replace(".", " ").split())
    words |= set(repo.get("topics") or [])
    return any(w in words for w in AI_WORDS) or any(
        k in text for k in ("llm", "agent", "gpt", "rag ", "mcp"))


def main():
    DATA.mkdir(exist_ok=True)
    history = json.loads(HISTORY_FILE.read_text()) if HISTORY_FILE.exists() else {}

    found = {}
    for q in QUERIES:
        for item in search(q):
            found[item["full_name"]] = item
        time.sleep(2.5)
    print(f"Found {len(found)} repos from {len(QUERIES)} searches")
    if not found:
        raise SystemExit("No results from GitHub search; keeping yesterday's files.")

    today = TODAY.isoformat()
    for name, item in found.items():
        h = history.setdefault(name, {"stars": {}})
        h["stars"][today] = item["stargazers_count"]
        h["last_seen"] = today
        h["info"] = {
            "url": item["html_url"],
            "description": (item.get("description") or "").strip(),
            "topics": item.get("topics") or [],
            "created": item["created_at"][:10],
            "pushed": item["pushed_at"][:10],
            "language": item.get("language"),
            "archived": item.get("archived", False),
            "fork": item.get("fork", False),
        }

    # Drop old history and repos that fell off every search.
    cutoff = days_ago(KEEP_DAYS)
    watch_cutoff = days_ago(WATCH_DAYS)
    for name in list(history):
        h = history[name]
        h["stars"] = {d: s for d, s in h["stars"].items() if d >= cutoff}
        if h.get("last_seen", "") < watch_cutoff or not h["stars"]:
            del history[name]

    rows = []
    for name, h in history.items():
        if h.get("last_seen") != today:
            continue
        info = h["info"]
        if info["archived"] or info["fork"]:
            continue
        stars = h["stars"][today]
        earlier = sorted(d for d in h["stars"] if d < today)
        if earlier:
            prev_day = earlier[-1]
            gap = (TODAY - dt.date.fromisoformat(prev_day)).days or 1
            per_day = (stars - h["stars"][prev_day]) / gap
            how = "measured"
        else:
            age = max((TODAY - dt.date.fromisoformat(info["created"])).days, 1)
            if age > 30:
                continue  # older repo seen for the first time: wait for a real measurement
            per_day = stars / age
            how = "estimate (new repo, stars / age)"
        week = None
        week_day = days_ago(7)
        older = [d for d in h["stars"] if d <= week_day]
        if older:
            week = stars - h["stars"][max(older)]
        rows.append({
            "repo": name, "url": info["url"], "description": info["description"],
            "stars": stars, "stars_today": round(per_day), "how": how,
            "stars_7d": week, "created": info["created"], "pushed": info["pushed"],
            "topics": info["topics"], "ai_related": is_ai({
                "name": name, "description": info["description"], "topics": info["topics"]}),
        })

    rows.sort(key=lambda r: r["stars_today"], reverse=True)
    top = [r for r in rows if r["stars_today"] > 0][:TOP_N]

    HISTORY_FILE.write_text(json.dumps(history, indent=0, sort_keys=True))
    (DATA / "trending.json").write_text(json.dumps(
        {"date": today, "source": "GitHub search API (official), daily star deltas",
         "repos": top}, indent=2))

    lines = [
        f"# AI repo radar, {today}",
        "",
        "Python repos gaining the most stars in the last day, from GitHub's official search API.",
        "\"measured\" = real change since the last run; \"estimate\" = new repo, total stars divided by its age in days.",
        "",
        "| # | Repo | Stars today | Total | 7 days | AI? | Created | What it is |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(top, 1):
        desc = r["description"].replace("|", "/")[:160]
        tag = "" if r["how"] == "measured" else " (est.)"
        lines.append(
            f"| {i} | [{r['repo']}]({r['url']}) | {r['stars_today']:,}{tag} | {r['stars']:,} | "
            f"{'' if r['stars_7d'] is None else format(r['stars_7d'], ',')} | "
            f"{'yes' if r['ai_related'] else 'no'} | {r['created']} | {desc} |")
    (DATA / "trending.md").write_text("\n".join(lines) + "\n")
    print(f"Wrote {len(top)} repos to data/trending.md")


if __name__ == "__main__":
    main()
