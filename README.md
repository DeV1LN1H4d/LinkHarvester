# Link Harvester — রিয়েল‑টাইম ওয়েবসাইট লিংক এক্সট্রাক্টর

যেকোনো সাইট (যেমন `example.com`) থেকে **রিয়েল‑টাইমে** সব লিংক এক্সট্রাক্ট করে কনসোলে দেখায় এবং **ডোমেইনের নামে** `.txt` ও `.csv` ফাইলে সেভ করে। একই ডোমেইনের HTML পেজগুলো **ক্রল** করে; এক্সটার্নাল লিংকগুলো **সেভ** হয় কিন্তু **ক্রল হয় না**।  

> স্ক্রিপ্টের নাম: `Link Harvester`

---

## প্রধান বৈশিষ্ট্য

- **রিয়েল‑টাইম আউটপুট**: নতুন লিংক সাথে সাথে কনসোলে দেখায়, উপরে লাইভ স্ট্যাটস প্যানেল (Rich UI)。
- **বিস্তৃত কভারেজ**: `<a href>`, `<link href>`, `<script src>`, `<img src|srcset>`, `<iframe src>`, `<video|audio|source src>`, `<form action>`, `meta refresh`—সব URL ধরা হয়。
- **ইন্টারনাল‑ক্রল/এক্সটার্নাল‑সেভ**: internal HTML পেজ ক্রল করে; external লিংক সেভ করেই থামে。
- **নরমালাইজেশন**: রিলেটিভ→অ্যাবসোলিউট, ফ্রাগমেন্ট বাদ, default port drop, পাথ ক্লিনআপ。
- **আউটপুট ফাইল**: `{ডোমেইন}-links.txt` ও `{ডোমেইন}-links.csv` (কলাম: `link, internal, source_page`)。
- **Robots.txt রেসপেক্ট** (ডিফল্ট), চাইলে `--ignore-robots`。
- **সাবডোমেইন ইনক্লুডেড** (ডিফল্ট), চাইলে `--no-subdomains`。
- **ফাস্ট ও অ্যাসিঙ্ক**: `aiohttp` + কনকারেন্সি (ওয়ার্কার সংখ্যা কনফিগারেবল)。
- **গ্রেসফুল স্টপ**: `Ctrl+C` দিলে যতটুকু হয়েছে ততটুকু ফাইলে থেকে যায়।

---

## সিস্টেম রিকোয়ারমেন্ট

- **Python** 3.9+
- Windows / macOS / Linux – যেকোনো একটিতে কাজ করবে

---

## ইন্সটলেশন

```bash
pip install aiohttp beautifulsoup4 tldextract rich
```

> (ঐচ্ছিক) ভার্চুয়াল এনভাইরনমেন্ট ব্যবহার করলে ভালো হয়:
>
> - macOS/Linux: `python3 -m venv .venv && source .venv/bin/activate`
> - Windows: `py -m venv .venv && .venv\Scripts\activate`

---

## ব্যবহার (Quick Start)

1) স্ক্রিপ্টটি `linkharvester.py` নামে সেভ করুন।  
2) রান করুন:

```bash
python linkharvester.py example.com
```

আরও কনফিগ সহ উদাহরণ:

```bash
# বেশি ওয়ার্কার ও বেশি পেজ, আউটপুট আলাদা ফোল্ডারে
python linkharvester.py https://example.com -w 20 -m 20000 --outdir outputs

# robots.txt উপেক্ষা করে
python linkharvester.py example.com --ignore-robots

# সাবডোমেইন বাদ দিয়ে শুধু মেইন হোস্ট
python linkharvester.py example.com --no-subdomains

# শান্ত মোড (শুধু স্ট্যাটস প্যানেল)
python linkharvester.py example.com --quiet

# কাস্টম ইউজার-এজেন্ট
python linkharvester.py example.com --ua "Mozilla/5.0 (compatible; MyCrawler/1.0)"
```

---

## CLI অপশনসমূহ

| অপশন | ডিফল্ট | ব্যাখ্যা |
|---|---:|---|
| `url` (পজিশনাল) | — | টার্গেট সাইট (যেমন `example.com` বা সম্পূর্ণ `https://...`) |
| `-w`, `--workers` | 12 | একসাথে কত রিকোয়েস্ট চলবে |
| `-m`, `--max-pages` | 10000 | সর্বোচ্চ কতটি পেজ ক্রল করবে (internal HTML) |
| `--ignore-robots` | `False` | দিলে robots.txt উপেক্ষা করবে |
| `--no-subdomains` | `False` | দিলে সাবডোমেইন ক্রল করবে না |
| `--timeout` | 20 | প্রতিটি রিকোয়েস্টের টাইমআউট (সেকেন্ড) |
| `--ua` | বিল্ট-ইন | কাস্টম User‑Agent স্ট্রিং |
| `--quiet` | `False` | দিলে per‑link লাইন আউটপুট বন্ধ থাকবে |
| `-o`, `--outdir` | `.` | আউটপুট ফোল্ডার |

---

## আউটপুট

- **টেক্সট**: `example.com-links.txt`  
- **CSV**: `example.com-links.csv`  
  CSV কলাম:  
  - `link` — পাওয়া সম্পূর্ণ URL  
  - `internal` — `yes`/`no`  
  - `source_page` — কোন পেজ থেকে লিংকটি পাওয়া গেছে

উদাহরণ ফাইলনেম গুলোতে “`example.com`” শব্দটা **registered domain** থেকে তৈরি (যেমন `sub.a.b.example.co.uk` → `example.co.uk`)।

---

## কীভাবে কাজ করে (সংক্ষেপে)

1. টার্গেট পেজ ফেচ করে **HTML** কিনা যাচাই করে।  
2. BeautifulSoup দিয়ে বিভিন্ন ট্যাগ/অ্যাট্রিবিউট থেকে URL সংগ্রহ করে (`href/src/srcset/form action/meta refresh`)।  
3. URL **নরমালাইজ** করা হয় (রিলেটিভ→অ্যাবসোলিউট, ফ্রাগমেন্ট বাদ, ডিফল্ট পোর্ট বাদ, পাথ ক্লিন)।  
4. **ইন্টারনাল/এক্সটার্নাল** হিসেবে আলাদা করা হয়; সব লিংক **ডিডুপ** হয়।  
5. ইন্টারনাল **HTML** পেজগুলো কিউতে পড়ে আবার ক্রল হয়; বাইনারি/অ-HTML লিংক শুধু সেভ হয়।  
6. রিয়েল‑টাইমে কনসোলে দেখায় এবং `.txt` ও `.csv`‑এ সঙ্গে সঙ্গে লিখে দেয়।

---

## পারফরম্যান্স টিপস

- বড় সাইটে `-w` (ওয়ার্কার) একটু বাড়ান, তবে সার্ভারের রিসোর্স মাথায় রাখুন।  
- সাইট খুব বড় হলে `-ম` কমিয়ে নিন বা `--no-subdomains` দিন।  
- `--quiet` দিলে কনসোল I/O কমে, স্পিড বাড়তে পারে।  
- টাইমআউট বাড়াতে/কমাতে `--timeout` ব্যবহার করুন।  
- কিছু সাইট কাস্টম UA না দিলে ব্লক করতে পারে—`--ua` দিন।

---

## সীমাবদ্ধতা

- **JS‑রেন্ডারড কনটেন্ট** (SPA ইত্যাদি) যেখানে লিংকগুলো জাভাস্ক্রিপ্টে তৈরি হয়—HTML থেকে ধরা নাও পড়তে পারে। রেন্ডারিংসহ ভ্যারিয়েন্ট (Playwright/Selenium) দরকার হলে আলাদা করে যুক্ত করা যাবে।  
- **লগইন/অথ** লাগা পেজ ক্রল করবে না।  
- **রেট‑লিমিট/ফায়ারওয়াল** থাকলে ধীর হতে পারে বা ব্লক হতে পারে।  
- নন‑HTML (PDF/ইমেজ/ভিডিও/আর্কাইভ) ফেচ করা হয় না—শুধু লিংক সেভ হয়।

---

## নৈতিক ও আইনগত নোট

সাইটের **Terms of Service**, **robots.txt**, ও স্থানীয় আইন মেনে চলুন। নিজের সার্ভিস বা শেখার প্রয়োজনে ব্যবহার করুন; অতিরিক্ত লোড বা অননুমোদিত স্ক্র্যাপিং এড়িয়ে চলুন।

---

## লাইসেন্স

[**License**](https://github.com/DeV1LN1H4d/LinkHarvester/blob/main/LICENSE)

---

**শুরু করতে এক লাইনে:**

```bash
python linkharvester.py example.com
```
