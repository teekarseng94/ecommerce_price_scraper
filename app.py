# -*- coding: utf-8 -*-
"""
Streamlit landing page + control panel for the E-commerce Price Scraper.

This file does NOT rewrite the scraper. It simply:
  1) Shows a friendly SaaS-style landing page.
  2) Lets the user upload a catalog, pick options, and press a button.
  3) Calls the existing main() function in main.py to do the real work.
  4) Shows the results table and lets the user download the CSV report.

Run it with:   streamlit run app.py
"""

import os
import io
import glob
import shutil
import datetime
import contextlib

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# 0) Make sure we run from the project folder so relative paths like
#    'inputs/catalog.xlsx' and 'results/...' resolve correctly.
# ---------------------------------------------------------------------------
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_DIR)

INPUTS_DIR = os.path.join(PROJECT_DIR, "inputs")
COOKIES_DIR = os.path.join(PROJECT_DIR, "cookies")
CATALOG_PATH = os.path.join(INPUTS_DIR, "catalog.xlsx")

# Which cookie file each platform needs in order to be "logged in".
# (tmall reuses the taobao login, just like the scraper does.)
COOKIE_FILES = {
    "jd": os.path.join(COOKIES_DIR, "jd.pkl"),
    "taobao": os.path.join(COOKIES_DIR, "taobao.pkl"),
    "tmall": os.path.join(COOKIES_DIR, "taobao.pkl"),
}

# ---------------------------------------------------------------------------
# 1) Page configuration + a little bit of styling
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="E-commerce Price Scraper",
    page_icon="🛒",
    layout="wide",
)

st.markdown(
    """
    <style>
      /* Hero banner */
      .hero {
        background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
        padding: 3rem 2rem;
        border-radius: 18px;
        color: white;
        text-align: center;
        margin-bottom: 1.5rem;
      }
      .hero h1 { font-size: 2.6rem; margin-bottom: 0.4rem; }
      .hero p  { font-size: 1.25rem; opacity: 0.95; }

      /* Simple card look for sections */
      .card {
        background: #ffffff;
        border: 1px solid #eceff4;
        border-radius: 14px;
        padding: 1.25rem 1.5rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        height: 100%;
      }
      .card h3 { margin-top: 0; }

      .step-num {
        display: inline-block;
        width: 34px; height: 34px; line-height: 34px;
        background: #4f46e5; color: white; border-radius: 50%;
        text-align: center; font-weight: 700; margin-bottom: 0.5rem;
      }
      .footer {
        text-align: center; color: #6b7280; font-size: 0.9rem;
        margin-top: 2.5rem; padding-top: 1rem; border-top: 1px solid #eceff4;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# We use "session state" (Streamlit's memory) to remember whether the user
# has clicked "Start Price Check" so we can reveal the tool below.
if "show_tool" not in st.session_state:
    st.session_state.show_tool = False


# ===========================================================================
#  LANDING PAGE
# ===========================================================================

# ---- 1. Hero section ------------------------------------------------------
st.markdown(
    """
    <div class="hero">
        <h1>🛒 E-commerce Price Scraper</h1>
        <p>Compare product prices across JD, Taobao, and Tmall.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

col_a, col_b, col_c = st.columns([1, 1, 1])
with col_b:
    if st.button("🚀 Start Price Check", use_container_width=True, type="primary"):
        st.session_state.show_tool = True

st.write("")

# ---- 2. Problem section ---------------------------------------------------
st.subheader("The Problem")
st.markdown(
    "Sellers and buyers waste hours **manually checking product prices** across "
    "multiple marketplaces. Prices change often, promotions come and go, and "
    "copying numbers into a spreadsheet by hand is slow and error-prone."
)

# ---- 3. Solution section --------------------------------------------------
st.subheader("The Solution")
st.markdown(
    "This app lets you **upload a product list**, automatically **scrape "
    "marketplace prices**, **compare them against your promo price**, and "
    "**generate a CSV report** — all from one screen, no coding required."
)

# ---- 4. Features section --------------------------------------------------
st.subheader("Features")
f1, f2, f3 = st.columns(3)
with f1:
    st.markdown(
        '<div class="card"><h3>📥 Upload & configure</h3>'
        "• Upload an Excel catalog<br>"
        "• Select platforms: JD, Taobao, Tmall<br>"
        "• Set product prefix / brand name</div>",
        unsafe_allow_html=True,
    )
with f2:
    st.markdown(
        '<div class="card"><h3>⚙️ Run the scraper</h3>'
        "• Set a scraping delay<br>"
        "• Run the price check<br>"
        "• Human-like, one product at a time</div>",
        unsafe_allow_html=True,
    )
with f3:
    st.markdown(
        '<div class="card"><h3>📊 Get results</h3>'
        "• View a results table<br>"
        "• See which prices beat your promo<br>"
        "• Download a CSV report</div>",
        unsafe_allow_html=True,
    )

st.write("")

# ---- 5. How it works section ---------------------------------------------
st.subheader("How It Works")
s1, s2, s3, s4 = st.columns(4)
with s1:
    st.markdown('<div class="card"><span class="step-num">1</span>'
                "<h3>Upload</h3>Upload your product catalog (Excel).</div>",
                unsafe_allow_html=True)
with s2:
    st.markdown('<div class="card"><span class="step-num">2</span>'
                "<h3>Choose</h3>Choose marketplaces to check.</div>",
                unsafe_allow_html=True)
with s3:
    st.markdown('<div class="card"><span class="step-num">3</span>'
                "<h3>Run</h3>Run the price check.</div>",
                unsafe_allow_html=True)
with s4:
    st.markdown('<div class="card"><span class="step-num">4</span>'
                "<h3>Download</h3>Download your CSV report.</div>",
                unsafe_allow_html=True)

st.write("")

# ---- 6. Pricing / MVP section --------------------------------------------
st.subheader("Pricing")
p1, p2 = st.columns(2)
with p1:
    st.markdown(
        '<div class="card"><h3>Free Trial (MVP)</h3>'
        "✅ Manual run<br>✅ CSV export<br>✅ Compare against promo price<br>"
        "<br><b>$0</b> — you are using this now.</div>",
        unsafe_allow_html=True,
    )
with p2:
    st.markdown(
        '<div class="card"><h3>Pro (Coming soon)</h3>'
        "🔜 Scheduled monitoring<br>🔜 Price-drop alerts<br>"
        "🔜 Multi-catalog dashboards<br><br><b>Future paid version.</b></div>",
        unsafe_allow_html=True,
    )

st.divider()


# ===========================================================================
#  THE TOOL  (revealed after clicking "Start Price Check")
# ===========================================================================
st.header("🔎 Price Check Tool")

if not st.session_state.show_tool:
    st.info("Click **🚀 Start Price Check** above to open the tool.")
else:
    # ---- Step 1: JD Login Setup -----------------------------------------
    st.markdown("#### 1) JD Login Setup (do this first)")
    st.info(
        "JD may block a **new automation browser profile**. The most reliable way "
        "is to open a **normal Chrome** session, log in to JD manually, confirm "
        "search works, then let the scraper **attach** to that Chrome."
    )

    if "jd_login_verified" not in st.session_state:
        st.session_state.jd_login_verified = False
    if "use_attach" not in st.session_state:
        st.session_state.use_attach = True

    st.markdown(
        "**Step A — open Chrome with remote debugging.** Close all Chrome windows "
        "first, then run this in a terminal (in this project folder):"
    )
    st.code(
        '& "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
        '--remote-debugging-port=9222 '
        '--user-data-dir="$PWD\\browser_profiles\\jd_manual" "https://global.jd.com/"',
        language="powershell",
    )
    st.caption("If Chrome is 32-bit, use `C:\\Program Files (x86)\\Google\\Chrome\\"
               "Application\\chrome.exe` instead.")
    st.markdown(
        "**Step B — in that Chrome:** log in (scan QR), pass any security checks, "
        "switch region if needed, and **search a normal keyword like `小家电`** to "
        "confirm real product cards appear. **Keep this Chrome open.**"
    )

    confirmed = st.checkbox(
        "I have opened Chrome, logged in to JD, and confirmed search results are visible."
    )
    st.session_state.use_attach = st.checkbox(
        "Use attached Chrome session (recommended)", value=st.session_state.use_attach,
        help="When on, the scraper connects to your own Chrome (127.0.0.1:9222) "
             "instead of a scraper profile.",
    )

    if st.button("✅ Verify JD is ready"):
        try:
            from scraper_jd import JDScraper
            j = JDScraper()
            with st.spinner("Checking JD…"):
                if st.session_state.use_attach:
                    if not confirmed:
                        st.warning("Please tick the confirmation box first.")
                        st.session_state.jd_login_verified = False
                    else:
                        j.attach_chrome = True
                        st.session_state.jd_login_verified = j.ensure_attached_ready(headless=False)
                else:
                    st.session_state.jd_login_verified = j.check_login_status(headless=True)
        except Exception as e:  # noqa: BLE001
            st.session_state.jd_login_verified = False
            st.error(f"Could not run the JD check: {e}")

    if st.session_state.jd_login_verified:
        st.success("JD is ready ✅ — you can run the scraper below.")
    else:
        st.warning("JD not verified yet. Do Steps A & B, then click **Verify JD is ready**.")

    with st.expander("Alternative: use the scraper's own profile (--login_only)"):
        st.markdown(
            "If you prefer not to attach, you can log in inside the scraper's own "
            "profile instead (less reliable if JD blocks it):"
        )
        st.code(".\\.venv\\Scripts\\python.exe main.py --platforms jd --login_only",
                language="powershell")
        st.caption("Then uncheck 'Use attached Chrome session' above and click Verify.")

    # ---- Step 2: Upload the Excel catalog --------------------------------
    st.markdown("#### 2) Upload your product catalog (Excel)")
    st.markdown(
        "Your Excel needs up to **3 columns** (first sheet, any sheet name):\n\n"
        "| product_name | promo_price | product_url *(optional)* |\n"
        "|---|---|---|\n"
        "| 大疆DJI Osmo Pocket 3 | 1319 | *(leave empty)* |\n"
        "| 大疆 OSMO Pocket 4 Pro | 3138 | https://item.jd.com/100012345678.html |\n"
    )
    with st.expander("What do these columns mean? (click to read)"):
        st.markdown(
            "- **product_name** — your label for the product; also the text used to "
            "**search JD** when no URL is given.\n"
            "- **promo_price** — your benchmark price. Used **only after scraping** to "
            "flag rows where `scraped_price < promo_price`. The scraper **never "
            "searches for this price**.\n"
            "- **product_url** *(optional)* — paste a JD product link to scrape that "
            "exact page; leave empty to search by name.\n\n"
            "**Search mode** (no product_url): uses **product_name**, the scraper "
            "searches JD. Easy, but *may fail if JD blocks search results*.\n\n"
            "**Direct URL mode** (product_url filled): the scraper opens the **exact "
            "product page**. *More stable for JD* — use this if search keeps failing."
        )
    uploaded = st.file_uploader(
        "Upload an .xlsx file (it will be saved as inputs/catalog.xlsx).",
        type=["xlsx"],
    )

    # ---- Step 3: Options -------------------------------------------------
    st.markdown("#### 3) Choose your options")
    c1, c2 = st.columns(2)
    with c1:
        platforms = st.multiselect(
            "Marketplaces to check",
            options=["jd", "taobao", "tmall"],
            default=["jd"],
            help="Pick one or more platforms to scrape.",
        )
        prefix = st.text_input(
            "Product prefix / brand name (optional)",
            value="",
            help="Leave empty for most cases. Only fill this in to add a brand in "
                 "front of every product name (e.g. 丹麦皇冠 for food products).",
        )
        match_mode = st.selectbox(
            "Match mode",
            options=["auto", "general", "weight"],
            index=0,
            help="auto = pick automatically per product. "
                 "general = search by name (best for electronics like DJI). "
                 "weight = match by weight like 500g (best for food).",
        )
    with c2:
        sleep_time = st.number_input(
            "Scraping delay between actions (seconds)",
            min_value=0.0, max_value=60.0, value=5.0, step=1.0,
            help="Higher = slower but safer (less likely to be blocked).",
        )
        headless_choice = st.selectbox(
            "Headless mode (hide the browser window)?",
            options=["No (recommended, lets you solve captchas)", "Yes"],
            index=0,
        )
    headless = headless_choice.startswith("Yes")

    # ---- Result controls (how many results, how to dedupe) ---------------
    st.markdown("**Results**")
    r1, r2, r3, r4 = st.columns(4)
    with r1:
        products_limit = st.number_input(
            "Products limit", min_value=1, max_value=200, value=20, step=1,
            help="Max products to keep per search.",
        )
    with r2:
        dedupe_by = st.selectbox(
            "Dedupe by", options=["url", "merchant", "product_name", "none"], index=0,
            help="How to remove duplicates. 'url' keeps the most results; "
                 "'merchant' drops many when one shop sells several products.",
        )
    with r3:
        pages = st.number_input(
            "Pages", min_value=1, max_value=10, value=1, step=1,
            help="How many JD search result pages to scrape.",
        )
    with r4:
        scroll_rounds = st.number_input(
            "Scroll rounds", min_value=1, max_value=20, value=5, step=1,
            help="How many times to scroll each page to load lazy product cards.",
        )

    # ---- Step 4: Run -----------------------------------------------------
    st.markdown("#### 4) Run the price check")
    # Only enable the Run button once JD login is verified (when JD is selected).
    jd_selected = "jd" in platforms
    run_blocked = jd_selected and not st.session_state.jd_login_verified
    if run_blocked:
        st.warning("Please complete **Step 1: JD Login Setup** and click "
                   "**Verify JD login** before running.")
    run_clicked = st.button("▶️ Run Price Scraper", type="primary", disabled=run_blocked)

    if run_clicked:
        # --- Validate the user's choices before doing anything heavy ------
        if uploaded is None:
            st.error("Please upload an Excel catalog first.")
            st.stop()
        if not platforms:
            st.error("Please select at least one marketplace.")
            st.stop()

        # --- Taobao/Tmall still use cookie files; check those only --------
        missing = sorted(
            {p for p in platforms if p != "jd" and not os.path.isfile(COOKIE_FILES[p])}
        )
        if missing:
            needed = ", ".join(
                sorted({os.path.basename(COOKIE_FILES[p]) for p in missing})
            )
            st.error(
                "You are not logged in yet for: **" + ", ".join(missing) + "**.\n\n"
                "These platforms need a saved login file (" + needed + ") inside the "
                "`cookies/` folder. Run once in a terminal, log in by hand, then retry:\n\n"
                "```\npython main.py --platforms " + " ".join(missing) + "\n```"
            )
            st.stop()

        # --- Save the uploaded file to inputs/catalog.xlsx ----------------
        try:
            os.makedirs(INPUTS_DIR, exist_ok=True)
            # Keep a backup of any existing catalog, just in case.
            if os.path.isfile(CATALOG_PATH):
                shutil.copyfile(CATALOG_PATH, CATALOG_PATH + ".bak")
            with open(CATALOG_PATH, "wb") as f:
                f.write(uploaded.getbuffer())
            st.success("Catalog saved to inputs/catalog.xlsx ✅")
        except Exception as e:  # noqa: BLE001
            st.error(f"Could not save your Excel file: {e}")
            st.stop()

        # --- Run the existing scraper -------------------------------------
        st.info(
            "The scraper is running. A browser may open — this can take a while. "
            "Please keep this tab open. Progress log appears below when it finishes."
        )

        log_buffer = io.StringIO()
        run_ok = False
        try:
            # Imported here so the landing page still loads even if the
            # scraper modules have a problem.
            import main as scraper_main

            with st.spinner("Scraping prices… please wait."):
                # Capture the scraper's print() output so we can show it.
                with contextlib.redirect_stdout(log_buffer):
                    # Login is verified separately (Step 1), and Streamlit cannot
                    # answer the terminal login prompt, so skip the in-run check.
                    scraper_main.main(prefix, float(sleep_time), headless, platforms,
                                      match_mode=match_mode, require_login_check=False,
                                      attach_chrome=st.session_state.get("use_attach", False),
                                      products_limit=int(products_limit), dedupe_by=dedupe_by,
                                      pages=int(pages), scroll_rounds=int(scroll_rounds))
            run_ok = True
        except KeyboardInterrupt:
            st.error("The run was interrupted.")
        except Exception as e:  # noqa: BLE001
            st.error(
                "The scraper stopped with an error. This is often caused by a "
                "captcha, a login timeout, or a catalog that doesn't match the "
                "expected format.\n\n"
                f"Technical detail: `{e}`"
            )

        # Always show the captured log so the user can see what happened.
        log_text = log_buffer.getvalue()
        if log_text.strip():
            with st.expander("See detailed progress log"):
                st.text(log_text)

        # --- Load and show the results ------------------------------------
        # main() writes to results/<YYYYMMDD_HHMMSS>/full_catalog.csv, so we
        # pick the most recently created full_catalog.csv.
        candidates = glob.glob(
            os.path.join(PROJECT_DIR, "results", "*", "full_catalog.csv")
        )
        result_csv = max(candidates, key=os.path.getmtime) if candidates else None

        if result_csv and os.path.isfile(result_csv):
            try:
                df = pd.read_csv(result_csv)
                stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                st.success(f"Done! Found {len(df)} rows of results.")
                st.markdown("#### 4) Results")
                st.dataframe(df, use_container_width=True)
                st.download_button(
                    "⬇️ Download CSV report",
                    data=df.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"price_report_{stamp}.csv",
                    mime="text/csv",
                )
            except Exception as e:  # noqa: BLE001
                st.error(f"Results were created but could not be read: {e}")
        else:
            if run_ok:
                st.warning(
                    "The scraper finished but no results file was created. "
                    "This usually means no matching products were found."
                )
            else:
                st.info(
                    "No results file was produced. Fix the issue above and try again."
                )

# ---- 7. Footer ------------------------------------------------------------
st.markdown(
    '<div class="footer">Use responsibly and follow each marketplace’s terms.'
    "</div>",
    unsafe_allow_html=True,
)
