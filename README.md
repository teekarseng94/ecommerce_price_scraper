# E-commerce Price Scraper

This project consists of a multifunctional tool designed to scrape the prices of a set of products from different vendors via e-commerce websites such as Taobao, Tmall, and Jingdong.
The primary function is to compare the scraped prices and identify discounted offers to assist users in finding the best deals for their desired products.

## Example

We have a list of products, for instance: `"Danish Crown Ham Slices 800g"`, `"Danish Crown Barbecue Pork 500g"`, `"Danish Crown Sauce Pork Ribs 200g"`.
These keywords are used to search the e-commerce websites.

The goal is to generate a CSV file that contains the URL of the vendor, the price, and a boolean indicating whether the price is lower than the market price. 

![Project Screenshot](images/result.png)

The market price is given as a CSV file sourced from the official vendor of the products, for instance, Danish Crown.

![Project Screenshot](images/products_list.png)

## Installing and run

A step by step series of examples that tell you how to get a development environment running:

1. Clone the repo
```sh
git https://github.com/davide97l/merchants_price_scraper
```

2. Install Python packages
```sh
pip install -r requirements.txt
```

3. Run
```sh
python main.py --platforms jd taobao tmall
```

## Catalog format (easy, for normal users)

Your Excel file uses up to **3 columns**:

| product_name | promo_price | product_url |
|--------------|-------------|-------------|
| 大疆DJI Osmo Pocket 3 | 1319 | *(leave empty)* |
| 大疆 OSMO Pocket 4 Pro | 3138 | https://item.jd.com/100012345678.html |
| 西班牙风味香肠500g | 53.52 | *(leave empty)* |

What each column means:
- **product_name** — your own label / reference for the product. It is also the
  text used to **search JD** when no URL is given.
- **promo_price** — your benchmark price. It is used **only after scraping** to
  compare `scraped_price < promo_price`. The scraper **never searches for this
  price** — it is not a filter, just the number you want to beat.
- **product_url** — *optional*. Paste a JD product page link to scrape that exact
  page. Leave it empty to search by `product_name` instead.

Two ways each row is scraped:

- **Search mode** (product_url is empty): the scraper searches JD using
  `product_name`. Easy, but **may fail if JD blocks automated search results**.
- **Direct URL mode** (product_url is filled): the scraper opens the exact JD
  product page. **More stable** — recommended when search keeps failing.

Rules:
- The sheet can have **any name** (the app reads the **first sheet**).
- Only `product_name` and `promo_price` are required; `product_url` is optional.
- Save the file as **`inputs/catalog.xlsx`**.

A ready-made template is provided at **`inputs/catalog_template.xlsx`**. Just copy it,
edit the rows, and save it as `inputs/catalog.xlsx`. To (re)create the template
(close it in Excel first, or Windows will block the file):

```sh
python create_catalog_template.py
```

> Backward compatibility: if your Excel does **not** have `product_name`/`promo_price`
> columns, the app falls back to the old format (sheet `规格-概览（總表）`, product name
> in column 4, promo price in column 11).

## JD Login Setup First (important)

JD only shows real product data to a **logged-in, trusted browser**. If you scrape
without a trusted session, JD shows only grey loading boxes (a "skeleton" page).
There are **two ways** to set this up:

- **`--attach_chrome` (recommended):** log in using your **own normal Chrome**,
  confirm search works, then let the scraper attach to it. Most reliable, because
  JD often blocks a fresh scraper profile.
- **`--login_only` (alternative):** log in inside the scraper's **own** browser
  profile (`browser_profiles/jd`). Simpler, but JD may still block this profile.

### Recommended: attach to your own Chrome

**Step 1** — close all Chrome windows, then start Chrome with remote debugging
(PowerShell, from the project folder):

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="$PWD\browser_profiles\jd_manual" "https://global.jd.com/"
```

If your Chrome is 32-bit, use this path instead:

```powershell
& "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="$PWD\browser_profiles\jd_manual" "https://global.jd.com/"
```

**Step 2** — Chrome opens `global.jd.com`.

**Step 3** — in that Chrome, log in manually:
- scan the QR code (or use password),
- complete any captcha / security check,
- switch region if needed,
- **search a normal keyword, e.g. `小家电`, and confirm real product cards appear.**

**Step 4** — **keep that Chrome window open.**

**Step 5** — run the scraper in attach mode (a *separate* terminal):

```powershell
python main.py --platforms jd --match_mode general --overwrite --sleep_time 10 --attach_chrome
```

The scraper connects to your Chrome (`--chrome_debug_url`, default
`http://127.0.0.1:9222`), verifies JD search works, then scrapes in that same
trusted session. If JD is not ready, it stops safely and asks you to log in /
search `小家电` first.

### Alternative: the scraper's own profile

```powershell
python main.py --platforms jd --login_only
```

A Chrome window opens; log in, pass security checks, wait for your account page,
then press Enter. Then scrape **without** `--attach_chrome`:

```powershell
python main.py --platforms jd --match_mode general --overwrite --sleep_time 10
```

Notes:
- Before scraping, the tool automatically checks JD is ready (login for
  `--login_only`, or a real test search for `--attach_chrome`). Add
  `--skip_login_check` to turn this off.
- Login/verification windows will not appear in headless mode — keep headless OFF.
- In attach mode, **keep your Chrome open** for the whole scrape.

### How many results (`--products_limit`, `--dedupe_by`, `--pages`, `--scroll_rounds`)

By default JD electronics come from a few big shops, so removing duplicates *by
merchant* would throw away most results. The tool now **dedupes by URL** (each
product URL is unique), so you keep many products.

- `--products_limit` (default 20): max products kept per search.
- `--dedupe_by` (default `url`): `url` | `merchant` | `product_name` | `none`.
- `--pages` (default 1): how many JD search result pages to scrape.
- `--scroll_rounds` (default 5): how many times to scroll each page (loads more
  lazy cards before extracting).

Examples:

```powershell
# Get 30 JD results:
python main.py --platforms jd --match_mode general --overwrite --sleep_time 10 --attach_chrome --verify_keyword dji --products_limit 30 --dedupe_by url

# Get 50 JD results from 2 pages:
python main.py --platforms jd --match_mode general --overwrite --sleep_time 10 --attach_chrome --verify_keyword dji --products_limit 50 --pages 2 --dedupe_by url

# Keep all results, no dedupe:
python main.py --platforms jd --match_mode general --overwrite --sleep_time 10 --attach_chrome --verify_keyword dji --products_limit 50 --dedupe_by none
```

Results are saved as both `full_catalog.csv` (UTF-8 with BOM, so Chinese shows
correctly in Excel) and `full_catalog.xlsx`.

### Match mode (`--match_mode`)

Some products (food) are matched by weight like `500g`; others (electronics like DJI
cameras) have no weight. Choose how to search with `--match_mode`:

- `auto` (default): use weight matching if the name has a weight (e.g. `500g`), otherwise search by name.
- `general`: always search by name — best for electronics.
- `weight`: always match by weight — best for food with weights.

### Beginner run commands

```sh
# Recommended for a mixed catalog (auto-detects each product):
python main.py --platforms jd --match_mode auto --prefix ""

# Electronics only (e.g. DJI):
python main.py --platforms jd --match_mode general --prefix ""

# Food products that have weights, with a brand prefix:
python main.py --platforms jd --match_mode weight --prefix "丹麦皇冠"
```

Extra options:
- `--overwrite` — scrape again even if a result file already exists.
- Results are saved to `results/YYYYMMDD_HHMMSS/full_catalog.csv` (date **and** time,
  so a new run never gets blocked by an older run).

## Run Streamlit App

Prefer a friendly web page instead of the command line? Use the Streamlit app:

```sh
pip install -r requirements.txt
streamlit run app.py
```

This opens a landing page in your browser where you can upload a catalog, pick
marketplaces, set options, run the price check, view the results table, and
download a CSV report — no coding needed.

> Note: The first time you scrape a marketplace you must log in manually so the
> app can save your login. If a login is missing, the app will tell you which
> platform needs it and how to create it. Keep "Headless mode" OFF the first
> time so you can see the browser and solve any captcha.

## Challenges and Solutions

During the development of this project, I faced several technical obstacles, and here's how I addressed them:

- **Platform Authentication:** Most platforms require user authentication for product scraping. To tackle this, the program is designed to authenticate only once during the first execution, after which the session cookies are saved and reused for subsequent sessions.

- **Bot Detection:** E-commerce platforms employ various measures to identify and block bots. To overcome this, the program incorporates several methods to simulate human-like behavior:
    - **Randomized Requests:** The program generates random user-agents and introduces random intervals between each request to avoid pattern detection.
    - **Captcha Alert:** The program alerts the user when a captcha appears, allowing for manual resolution.
    - **Stealth Scraping:** Used stealth scraping libraries such as [playwright-stealth](https://pypi.org/project/playwright-stealth/) to further enhance the human-like browsing behavior.
    - **Rotating proxy IP:** TODO.

- **Product Matching:** Frequently, the products retrieved may have slightly different names compared to the searched product. To address this issue, the program leverages a Language Model to verify the similarity between the scraped product name and the searched product name. This approach aids in filtering out false positives, ensuring only relevant product data is considered.

These strategies help ensure successful and uninterrupted scraping of product data from e-commerce websites.

## Support this project

If you found this project interesting please support me by giving it a ⭐, I would really appreciate it 😀