import os
import re
import sys
from dotenv import load_dotenv

# Ensure UTF-8 output encoding for console prints (especially on Windows)
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Load environment variables
load_dotenv()

from scraper_jd import JDScraper
from scraper_taobao import TaobaoScraper
from scraper_tmall import TmallScraper
import pandas as pd
import datetime
import argparse


def process_dataset(df, promo_price, product_name, dedupe_by='url'):
    """Turn raw scraped rows into the final CSV format. Works for BOTH
    general mode and weight mode, since both return the same base columns.

    dedupe_by controls how duplicate rows are removed:
      'url'          -> one row per product URL (recommended; each URL is unique)
      'merchant'     -> one row per shop (old behaviour; drops many results)
      'product_name' -> one row per product name
      'none'         -> keep everything
    """
    base_cols = ['platform', 'merchant', 'product_name', 'price', 'url']
    extra_cols = [c for c in ['match_score', 'source_url_type'] if c in df.columns]
    df = df[base_cols + extra_cols]
    df = df.reset_index(drop=True)
    df['price'] = df['price'].astype(float)
    df['promo_price'] = float(promo_price)
    df['searched_product'] = str(product_name)
    df['is_under_promo_price'] = df['price'].apply(lambda x: True if x < float(promo_price) else False)
    if dedupe_by in ('url', 'merchant', 'product_name') and dedupe_by in df.columns:
        df = df.drop_duplicates(subset=dedupe_by, keep='first')
    # dedupe_by == 'none' (or unknown) -> keep all rows
    return df


def has_weight(product_name):
    """True if the product name contains a weight like 500g or 2kg.
    Used by match_mode 'auto' to decide between weight and general search."""
    return bool(re.search(r'\d+\s*(?:kg|g)\b', str(product_name), flags=re.IGNORECASE))


def load_catalog(path='inputs/catalog.xlsx'):
    """Read the product catalog.

    First tries the EASY 2-column format on the first sheet:
        product_name | promo_price
    (sheet name can be anything, column order does not matter).

    If those two columns are not found, falls back to the OLD format:
        sheet '规格-概览（總表）', product name from column 3, promo price from column 10.

    An OPTIONAL third column `product_url` is supported: if a row has a JD
    product URL, the scraper opens that page directly instead of searching.

    Returns three lists: (product_names, promo_prices, product_urls).
    """
    xl = pd.ExcelFile(path)

    # --- Try the simple format (2 required columns + optional product_url) ---
    first_sheet = xl.sheet_names[0]
    df = xl.parse(first_sheet)
    # Map lower-cased/trimmed column names -> real column names
    cols = {str(c).strip().lower(): c for c in df.columns}
    if 'product_name' in cols and 'promo_price' in cols:
        has_url = 'product_url' in cols
        # Only require product_name + promo_price to be present.
        sub = df.dropna(subset=[cols['product_name'], cols['promo_price']])
        product_names = sub[cols['product_name']].astype(str).str.strip().tolist()
        promo_prices = sub[cols['promo_price']].tolist()
        if has_url:
            product_urls = [
                (str(u).strip() if pd.notna(u) and str(u).strip() else None)
                for u in sub[cols['product_url']].tolist()
            ]
        else:
            product_urls = [None] * len(product_names)
        print(f"Loaded {len(product_names)} products using the simple format "
              f"from sheet '{first_sheet}'"
              f"{' (with product_url column)' if has_url else ''}.")
        return product_names, promo_prices, product_urls

    # --- Fall back to the old fixed format ---
    print("Simple 'product_name'/'promo_price' columns were not found. "
          "Falling back to the old format (sheet '规格-概览（總表）', columns 3 and 10).")
    df_old = xl.parse('规格-概览（總表）')
    promo_prices = df_old.iloc[:, 10].dropna().tolist()[1:]
    product_names = df_old.iloc[:, 3].dropna().tolist()
    product_urls = [None] * len(product_names)
    return product_names, promo_prices, product_urls


def main(prefix, sleep_time, headless, platforms, match_mode='auto', overwrite=False,
         login_only=False, require_login_check=True,
         attach_chrome=False, chrome_debug_url='http://127.0.0.1:9222',
         verify_keyword='dji', products_limit=20, dedupe_by='url',
         pages=1, scroll_rounds=5):
    platform_classes = {'jd': JDScraper, 'taobao': TaobaoScraper, 'tmall': TmallScraper}
    platforms = [platform_classes[p](sleep_time=sleep_time, products_limit=products_limit)
                 for p in platforms]

    # Tell the JD scraper how to run (attach mode, pagination, scrolling, etc.).
    for platform in platforms:
        if isinstance(platform, JDScraper):
            platform.attach_chrome = attach_chrome
            platform.chrome_debug_url = chrome_debug_url
            platform.verify_keyword = verify_keyword
            platform.pages = pages
            platform.scroll_rounds = scroll_rounds

    # --login_only: just set up the login (e.g. JD QR scan), then stop. No scraping.
    if login_only:
        for platform in platforms:
            if hasattr(platform, 'ensure_logged_in'):
                ok = platform.ensure_logged_in(headless=headless, force_login=True)
                if ok:
                    print('JD login setup completed. You can now run scraping.')
                else:
                    print('JD login was NOT verified. Please run the login setup again:')
                    print(f'  python main.py --platforms {platform.store_name} --login_only')
            else:
                print(f'{platform.store_name} does not need a separate login step.')
        return

    now = datetime.datetime.now()
    # Include the time (HHMMSS), not just the date, so a new run never gets
    # blocked by results from an earlier run on the same day.
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    save_dir = f'results/{timestamp}'

    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    # Check if OpenAI key is present for GPT filtering
    openai_key = os.getenv('OPENAI_KEY')
    use_gpt = 1
    if not openai_key:
        print("Warning: OPENAI_KEY is not set in the environment. Running without GPT filtering (use_gpt=0).")
        use_gpt = 0

    # Make sure platforms that need a login are actually ready BEFORE scraping.
    if require_login_check:
        checked = []
        for platform in platforms:
            if getattr(platform, 'attach_chrome', False):
                # Attach mode: check the user's OWN Chrome + that JD search works.
                print(f'Attach mode: checking your Chrome and that {platform.store_name} '
                      'search works...')
                if platform.ensure_attached_ready(headless=headless):
                    checked.append(platform)
                else:
                    print('JD is not ready. Please manually login and search 小家电 in the '
                          'opened Chrome until real product cards appear. Then run the '
                          'scraper again.')
            elif hasattr(platform, 'ensure_logged_in'):
                print(f'Checking {platform.store_name} login before scraping...')
                if platform.ensure_logged_in(headless=headless):
                    checked.append(platform)
                else:
                    print(f'{platform.store_name} is not logged in, so it will be skipped.')
                    print(f'Please run:  python main.py --platforms {platform.store_name} --login_only')
            else:
                checked.append(platform)
        platforms = checked
        if not platforms:
            print('No ready platforms available to scrape. Exiting.')
            return

    # Load the catalog (simple format first, old format as fallback).
    product_names, promo_prices, product_urls = load_catalog('inputs/catalog.xlsx')
    print(pd.DataFrame({'product_name': product_names, 'promo_price': promo_prices}))

    tot_products = len(product_names)
    for i in range(tot_products):
        product_name = product_names[i]
        promo_price = promo_prices[i]
        product_url = product_urls[i] if i < len(product_urls) else None

        # Only add a prefix if the user actually provided one.
        if prefix and not product_name.startswith(prefix):
            product_name = prefix + product_name

        # Decide how to search for this product.
        mode = match_mode
        if mode == 'auto':
            mode = 'weight' if has_weight(product_name) else 'general'

        for platform in platforms:
            using_url = bool(product_url) and hasattr(platform, 'scrape_product_by_url')
            label = 'direct-url' if using_url else mode
            print(f'Scraping product : {product_name} ({i+1}/{tot_products}) '
                  f'from {platform.store_name} [mode: {label}]')
            df_path = os.path.join(save_dir, f'{product_name}_{platform.store_name}.csv')
            empty_df_path = os.path.join(save_dir, f'empty_{product_name}_{platform.store_name}.csv')

            # Skip already-scraped products unless --overwrite is set.
            if not overwrite and (os.path.isfile(df_path) or os.path.isfile(empty_df_path)):
                print(f"{df_path} already scraped (use --overwrite to redo)")
                continue

            try:
                if using_url:
                    # A product URL was given: open the item page directly.
                    product_dict = platform.scrape_product_by_url(
                        product_url, headless=headless)
                elif mode == 'weight':
                    product_dict = platform.scrape_product_info_by_weight(
                        product_name, use_gpt=use_gpt, verbose=1, headless=headless)
                else:  # 'general'
                    product_dict = platform.scrape_product_info(
                        product_name, headless=headless)
            except Exception as e:
                # One product failing should never stop the whole run.
                print(f'Error while scraping "{product_name}" from {platform.store_name}: {e}')
                print('Skipping this product and continuing to the next one.')
                product_dict = []
            if product_dict is None:
                product_dict = []

            if len(product_dict) == 0:
                print(f'No suitable items found for {product_name}')
                df = pd.DataFrame()
                df_path = empty_df_path
            else:
                df = pd.DataFrame(product_dict)
                df = process_dataset(df, promo_price, product_name, dedupe_by=dedupe_by)
                print(f'[debug] Kept after dedupe_by={dedupe_by}: {len(df)}')
            # utf-8-sig so Chinese opens correctly in Excel (fixes garbled text).
            df.to_csv(df_path, index=False, encoding='utf-8-sig')
            print(f'[debug] Final CSV rows: {len(df)}')
            print(f'Product catalog saved to {df_path}')

    df_list = []
    for filename in os.listdir(save_dir):
        if filename.endswith('.csv') and not filename.endswith('full_catalog.csv') and not 'empty' in filename:
            file_path = os.path.join(save_dir, filename)
            df = pd.read_csv(file_path)
            df_list.append(df)
    if df_list:
        full_df = pd.concat(df_list, ignore_index=True)
        csv_path = os.path.join(save_dir, 'full_catalog.csv')
        full_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f'Full catalog saved to {csv_path}')
        # Also write an Excel file that normal users can open directly.
        try:
            xlsx_path = os.path.join(save_dir, 'full_catalog.xlsx')
            full_df.to_excel(xlsx_path, index=False)
            print(f'Full catalog (Excel) saved to {xlsx_path}')
        except Exception as e:
            print(f'Could not write Excel file: {e}')
    else:
        print('No products were successfully scraped, so no full_catalog.csv was created.')
        print("Check the 'debug' folder for screenshots and HTML of what the site showed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Process some arguments.')
    parser.add_argument('--prefix', type=str, default='',
                        help='Optional text added in front of every product name (e.g. a brand). '
                             'Default is empty. Only used if you pass it.')
    parser.add_argument('--sleep_time', type=float, default=5.0, help='Sleep time for the scraper')
    parser.add_argument('--headless', type=bool, default=False, help='Whether to run the scraper in headless mode')
    parser.add_argument('--platforms', nargs='+', default=['jd'], help='List of platforms to use')
    parser.add_argument('--match_mode', type=str, default='auto',
                        choices=['general', 'weight', 'auto'],
                        help="How to match products. 'general' = search by name (good for electronics), "
                             "'weight' = match by weight like 500g (good for food), "
                             "'auto' = pick weight if the name has a weight, otherwise general.")
    parser.add_argument('--overwrite', action='store_true',
                        help='Scrape again even if a result CSV already exists.')
    parser.add_argument('--login_only', action='store_true',
                        help='Only open the JD login flow (scan QR / verify), then exit without scraping.')
    parser.add_argument('--require_login_check', action='store_true', default=True,
                        help='Check JD login before scraping (default: ON).')
    parser.add_argument('--skip_login_check', dest='require_login_check', action='store_false',
                        help='Skip the JD login check before scraping.')
    parser.add_argument('--attach_chrome', action='store_true',
                        help='Attach to your own Chrome (started with --remote-debugging-port) '
                             'instead of a scraper profile. Recommended when JD blocks the '
                             'scraper profile.')
    parser.add_argument('--chrome_debug_url', type=str, default='http://127.0.0.1:9222',
                        help='CDP URL of your Chrome for --attach_chrome (default 127.0.0.1:9222).')
    parser.add_argument('--verify_keyword', type=str, default='dji',
                        help='Keyword used to verify JD search works before scraping (default: dji).')
    parser.add_argument('--products_limit', type=int, default=20,
                        help='Max products to keep per search (default: 20).')
    parser.add_argument('--dedupe_by', type=str, default='url',
                        choices=['url', 'merchant', 'product_name', 'none'],
                        help="How to remove duplicate rows (default: url). 'merchant' "
                             "drops many results for shops with several products.")
    parser.add_argument('--pages', type=int, default=1,
                        help='How many JD search result pages to scrape (default: 1).')
    parser.add_argument('--scroll_rounds', type=int, default=5,
                        help='How many times to scroll each page to load lazy cards (default: 5).')

    args = parser.parse_args()
    main(args.prefix, args.sleep_time, args.headless, args.platforms,
         match_mode=args.match_mode, overwrite=args.overwrite,
         login_only=args.login_only, require_login_check=args.require_login_check,
         attach_chrome=args.attach_chrome, chrome_debug_url=args.chrome_debug_url,
         verify_keyword=args.verify_keyword, products_limit=args.products_limit,
         dedupe_by=args.dedupe_by, pages=args.pages, scroll_rounds=args.scroll_rounds)
