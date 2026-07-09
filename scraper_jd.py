from scraper_base import BaseScraper, DESKTOP_USER_AGENT
import time
import os
import re
import urllib.parse
from playwright.sync_api import sync_playwright


def save_debug_artifacts(page, name, debug_dir='debug'):
    """Save a screenshot and the page HTML so a non-technical user can see
    what the website actually showed (captcha, login page, empty results, etc.).
    Wrapped in try/except so saving debug info never crashes the scraper."""
    try:
        os.makedirs(debug_dir, exist_ok=True)
        screenshot_path = os.path.join(debug_dir, f'{name}.png')
        html_path = os.path.join(debug_dir, f'{name}.html')
        page.screenshot(path=screenshot_path, full_page=True)
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(page.content())
        print(f'[debug] Screenshot saved to: {screenshot_path}')
        print(f'[debug] Page HTML saved to : {html_path}')
    except Exception as e:
        print(f'[debug] Could not save debug files: {e}')


class JDScraper(BaseScraper):
    # Folder where JD's persistent browser profile is stored. The SAME browser
    # that you log in with is reused for scraping, so JD sees a consistent
    # session/fingerprint instead of cookies copied from another browser.
    PROFILE_DIR = os.path.join('browser_profiles', 'jd')

    # Fallback selectors for JD desktop product cards, tried in this order.
    JD_PRODUCT_SELECTORS = [
        '#J_goodsList .gl-item',
        '.goods-list-v2 .gl-item',
        'li.gl-item',
        '.gl-item',
        'li[data-sku]',
        '[data-sku]',
    ]

    # Fallback selectors for the homepage search box.
    SEARCH_INPUT_SELECTORS = ['#key', 'input[name="keyword"]', 'input[type="text"]']

    # Fallback selectors for the homepage search button.
    SEARCH_BUTTON_SELECTORS = ['button.button', '.form .button', '.search-m .button',
                               'button[aria-label="搜索"]']

    # Fallback selectors used when extracting each product card.
    NAME_SELECTORS = ['.p-name em', '.p-name a', '.p-name', 'a[title]']
    PRICE_SELECTORS = ['.p-price i', '.p-price', '.J_price i', '.price']
    MERCHANT_SELECTORS = ['.p-shop a', '.p-shop', '.curr-shop']
    # Safe URL selectors only — never a bare a[href] (that grabs chat/cart links).
    URL_SELECTORS = ['a[href*="item.jd.com"]', 'a[href*="item.jd.hk"]',
                     '.p-img a[href]', '.p-name a[href]']

    # Selectors that indicate JD is still showing grey "skeleton" placeholders.
    SKELETON_SELECTORS = ['[class*="skeleton"]', '[class*="Skeleton"]',
                          '[class*="placeholder"]', '[class*="sk-"]',
                          '[class*="loading"]']

    # Selectors for the JD ITEM (product detail) page.
    ITEM_NAME_SELECTORS = ['.sku-name', '.itemInfo-wrap .sku-name', 'div.sku-name',
                           '.product-intro .sku-name']
    ITEM_PRICE_SELECTORS = ['.summary-price .price', '.p-price .price', 'span.price',
                            '.price .p-price']
    ITEM_MERCHANT_SELECTORS = ['.J-hove-wrap .name', '#popbox .mname', '.shopName',
                               '.name .shopname']

    # URLs we care about when logging network traffic (why the page won't load).
    NETWORK_KEYWORDS = ['search', 'so', 'ware', 'item', 'api', 'jd.com', '3.cn']

    # Words that appear on JD's security / captcha / slider verification pages.
    CAPTCHA_KEYWORDS = ['验证一下', '购物无忧', 'captcha', '安全验证', '滑块']

    # Text seen on JD LOGIN pages (means NOT logged in).
    LOGIN_MARKERS = ['扫码登录', '请登录', '手机扫码', '立即注册', '忘记密码',
                     '短信登录', '账户登录', '欢迎登录']
    # Text seen when LOGGED IN on the JD account / home page.
    ACCOUNT_MARKERS = ['我的京东', '退出', '个人中心', '我的关注', '我的收藏', '安全等级']

    def __init__(self, products_limit=10, sleep_time=0):
        super().__init__(products_limit, sleep_time)
        # Kept for compatibility, but JD no longer uses cookies/jd.pkl.
        self.cookies_path = 'cookies/jd.pkl'
        self.cookies_name = 'jd'
        self.url = 'https://www.jd.com'
        self.login_url = 'https://passport.jd.com/new/login.aspx'
        self.store_name = 'jd'
        # Attach mode: connect to the user's own already-logged-in Chrome
        # (started with --remote-debugging-port) instead of a scraper profile.
        # main.py sets these from the CLI flags.
        self.attach_chrome = False
        self.chrome_debug_url = 'http://127.0.0.1:9222'
        # Keyword used by verify_jd_ready() to confirm JD search works.
        self.verify_keyword = 'dji'
        # How many search result pages to scrape, and how many times to scroll
        # each page (to load JD's lazy-loaded product cards). main.py sets these.
        self.pages = 1
        self.scroll_rounds = 5

    # ----------------------------- small helpers --------------------------- #
    @staticmethod
    def _safe_filename(text, maxlen=60):
        """Turn a product name into a safe filename (keeps letters, numbers,
        and Chinese characters; replaces spaces; drops other punctuation)."""
        out = []
        for ch in str(text):
            if ch.isalnum() or ord(ch) > 127:  # keep letters/digits and CJK
                out.append(ch)
            elif ch.isspace():
                out.append('_')
        slug = ''.join(out).strip('_')
        return slug[:maxlen] or 'product'

    def _detect_captcha(self, page):
        """Return True if the page text looks like a security / captcha page."""
        try:
            content = page.content().lower()
        except Exception:
            return False
        return any(k.lower() in content for k in self.CAPTCHA_KEYWORDS)

    def _is_risk_page(self, page):
        """Return True if JD sent us to a risk / security verification page.
        Checks both the URL (risk_handler) and the page text (captcha words)."""
        try:
            url = (page.url or '').lower()
        except Exception:
            url = ''
        if 'risk_handler' in url:
            return True
        return self._detect_captcha(page)

    def _looks_like_homepage(self, page):
        """Return True if JD redirected us to the homepage instead of a search
        results page (so there will be no product cards)."""
        try:
            url = (page.url or '').lower()
        except Exception:
            url = ''
        if 'from=pc_search_sd' in url:
            return True
        if 'search.jd.com' in url or 'list.jd.com' in url:
            return False
        return 'jd.com' in url

    def _count_skeletons(self, page):
        """Count grey 'skeleton' placeholder blocks currently on the page."""
        total = 0
        for sel in self.SKELETON_SELECTORS:
            try:
                total += len(page.query_selector_all(sel))
            except Exception:
                pass
        return total

    def _count_empty_divs(self, page):
        """Count empty <div> blocks (grey boxes usually have no text/children)."""
        try:
            return page.evaluate(
                """() => {
                    let n = 0;
                    const ds = document.querySelectorAll('div');
                    for (const d of ds) {
                        if (!d.children.length && !(d.innerText || '').trim()) n++;
                        if (n > 300) break;
                    }
                    return n;
                }"""
            )
        except Exception:
            return 0

    def _looks_like_skeleton(self, page):
        """True if JD is showing only the loading shell (grey boxes), using
        several signals instead of just counting one class name."""
        if self._find_product_cards(page):
            return False
        try:
            url = (page.url or '').lower()
        except Exception:
            url = ''
        on_search = ('search.jd.com' in url) or ('list.jd.com' in url)
        try:
            text = ' '.join((page.inner_text('body') or '').split())
        except Exception:
            text = ''
        low_text = len(text) < 50
        # On the search page with almost no visible text = still loading.
        if on_search and low_text:
            return True
        # Or lots of empty grey blocks / skeleton-classed elements.
        return self._count_skeletons(page) > 0 or self._count_empty_divs(page) > 30

    @staticmethod
    def _scroll_page(page, steps=5, pause=1.0):
        """Scroll down slowly a few times so JD loads its lazy product cards."""
        for _ in range(steps):
            try:
                page.mouse.wheel(0, 1200)
            except Exception:
                pass
            time.sleep(pause)

    def _handle_captcha(self, page, headless=False, rewait_selector=None):
        """If a captcha/security page is detected, let the user solve it by hand.
        In headless mode we cannot show the window, so we just warn."""
        if not self._detect_captcha(page):
            return
        print('Security check / captcha detected on JD.')
        if headless:
            print('Cannot solve a captcha while running in headless mode. '
                  'Please re-run with headless mode turned OFF.')
            return
        input('Please solve the verification in the browser window, then press Enter here to continue...')
        if rewait_selector:
            try:
                page.wait_for_selector(rewait_selector, timeout=10000)
            except Exception:
                pass

    def _find_product_cards(self, page, verbose=False):
        """Try each fallback selector, print how many each finds, and return
        the first non-empty list of product cards."""
        best = []
        for sel in self.JD_PRODUCT_SELECTORS:
            try:
                found = page.query_selector_all(sel)
            except Exception:
                found = []
            if verbose:
                print(f'[debug] selector {sel!r:26} -> {len(found)} items')
            if found and not best:
                best = found
        return best

    def _wait_for_products(self, page, timeout=90, interval=3, verbose=False):
        """Wait (up to `timeout` seconds) for JD's product cards to appear,
        checking every `interval` seconds and scrolling slowly meanwhile.
        Handles JD's grey skeleton placeholders that take a while to hydrate."""
        waited = 0
        while waited < timeout:
            items = self._find_product_cards(page)
            if items:
                if verbose:
                    print(f'[debug] Product cards appeared after ~{waited}s.')
                return items
            print(f'Waiting for JD product cards... {waited}s / {timeout}s')
            try:
                page.mouse.wheel(0, 800)
            except Exception:
                pass
            time.sleep(interval)
            waited += interval
        return self._find_product_cards(page, verbose=verbose)

    @staticmethod
    def _first_text(item, selectors):
        """Return the first non-empty text found among the given child selectors."""
        for sel in selectors:
            try:
                el = item.query_selector(sel)
                if el is not None:
                    txt = (el.inner_text() or '').strip()
                    if txt:
                        return txt
            except Exception:
                continue
        return None

    @staticmethod
    def _first_text_page(page, selectors):
        """Like _first_text but searches the whole page (for item detail pages)."""
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el is not None:
                    txt = (el.inner_text() or '').strip()
                    if txt:
                        return txt
            except Exception:
                continue
        return None

    @staticmethod
    def _first_href(item, selectors):
        """Return the first non-empty href found among the given child selectors."""
        for sel in selectors:
            try:
                el = item.query_selector(sel)
                if el is not None:
                    href = el.get_attribute('href')
                    if href:
                        return href
            except Exception:
                continue
        return None

    @staticmethod
    def _parse_price(raw):
        """Safely turn a price string like '￥1,319.00' into a float, or None."""
        if not raw:
            return None
        cleaned = raw.replace('￥', '').replace('¥', '').replace(',', '').strip()
        m = re.search(r'\d+(?:\.\d+)?', cleaned)
        return float(m.group()) if m else None

    @staticmethod
    def _price_from_text(text):
        """Find a price like ￥1,319 inside a block of card text, or None."""
        if not text:
            return None
        m = re.search(r'[￥¥]\s*([0-9][0-9,]*(?:\.\d+)?)', text)
        if m:
            return float(m.group(1).replace(',', ''))
        return None

    def _extract_from_item_links(self, page, verbose=False):
        """Last-resort extraction: if there are no product cards, look for links
        to item.jd.com / item.jd.hk and build basic rows from nearby text."""
        products = []
        seen = set()
        links = []
        for sel in ['a[href*="item.jd.com"]', 'a[href*="item.jd.hk"]']:
            try:
                links.extend(page.query_selector_all(sel))
            except Exception:
                pass
        for a in links:
            try:
                href = a.get_attribute('href')
                if not href:
                    continue
                if not href.startswith('http'):
                    href = 'https:' + href
                key = href.split('?')[0]
                if key in seen:
                    continue
                name = (a.inner_text() or '').strip() or (a.get_attribute('title') or '').strip()
                if not name:
                    continue
                price = None
                try:
                    card = a.evaluate_handle(
                        "el => el.closest('li') || el.closest('.gl-item') || el.parentElement")
                    card_el = card.as_element() if card else None
                    if card_el is not None:
                        price = self._price_from_text(card_el.inner_text())
                except Exception:
                    price = None
                seen.add(key)
                products.append({
                    'product_name': name[:200],
                    'price': price,
                    'merchant': '未知商家',
                    'url': href,
                    'platform': self.store_name,
                })
            except Exception:
                continue
        if verbose:
            print(f'[debug] item-link fallback found {len(products)} rows.')
        return products

    # ------------------------ modern extraction ---------------------------- #
    # JavaScript that does the heavy lifting IN the page: it walks every JD
    # product link, climbs to the real product "card" container, and reads the
    # name / price / merchant from that container's text. Running it in the page
    # is far more reliable than guessing CSS child selectors from Python.
    _EXTRACT_JS = r"""
    (searched) => {
        const results = [];
        const cardsSample = [];
        const validUrls = [];
        const rejectedUrls = [];
        const seen = new Set();
        const priceRe = /[￥¥]\s*([0-9][0-9,]*(?:\.\d+)?)/;
        const pureNum = /^[¥￥]?\s*[0-9][0-9,]*(?:\.[0-9]+)?\s*$/;
        const skipLine = /已售|评价|万\+|条评价|加入购物车|对比|关注|优惠券|满[0-9]|降价|排序|综合|销量|价格|自营|旗舰店|专营店|专卖店|券/;
        // Hosts that are NEVER a product page.
        const rejectHost = /(chat|cart|search|shop|mall|passport|help|feedback|compare)\.jd\.com|jd\.com\/(help|feedback)/i;

        // Pull a numeric product id (>=6 digits) out of a URL string.
        function idFromUrl(u){
            if(!u) return null;
            let m = u.match(/item\.jd\.(?:com|hk)\/([0-9]{6,})\.html/i);
            if(m) return {id:m[1], type:'item_link'};
            m = u.match(/[?&](?:pid|sku|skuId|wareId|wareid)=([0-9]{6,})/i);
            if(m) return {id:m[1], type: /chat\.jd\.com/i.test(u) ? 'pid_from_chat' : 'pid_from_chat'};
            return null;
        }
        // Find product id + how we found it, for one card.
        function idFromCard(card){
            const links = Array.from(card.querySelectorAll('a[href]'));
            // 1) a real item.jd link
            for(const a of links){ const r = idFromUrl(a.getAttribute('href')||''); if(r && r.type==='item_link') return r; }
            // 2) pid/sku/wareId inside any link (e.g. chat.jd.com?pid=...)
            for(const a of links){ const r = idFromUrl(a.getAttribute('href')||''); if(r) return r; }
            // 3) data-* attributes on the card or a child
            const attrs = ['data-sku','data-pid','data-wareid','data-spu','sku'];
            const holders = [card].concat(Array.from(card.querySelectorAll('[data-sku],[data-pid],[data-wareid],[data-spu]')));
            for(const h of holders){
                for(const a of attrs){
                    const v = h.getAttribute && h.getAttribute(a);
                    if(v && /^[0-9]{6,}$/.test(v)) return {id:v, type:'data_sku'};
                }
            }
            // 4) "sku":"123" / "wareId":"123" inside the card HTML
            const m = (card.innerHTML||'').match(/["'](?:sku|skuId|wareId|wareid)["']?\s*:\s*["']?([0-9]{6,})/i);
            if(m) return {id:m[1], type:'text_fallback'};
            return null;
        }
        function priceEl(node){ return node.querySelector('.p-price, .J_price, [class*="price"]'); }
        function pickPrice(card){
            const sels = ['.p-price i','.p-price','.J_price i','.J_price','[class*="price"] i','[class*="price"]'];
            for(const s of sels){
                const e = card.querySelector(s);
                if(e){ const t=(e.innerText||'').replace(/[,，]/g,''); const m=t.match(/([0-9]+(?:\.[0-9]+)?)/); if(m) return parseFloat(m[1]); }
            }
            const tm = (card.innerText||'').match(priceRe);
            if(tm) return parseFloat(tm[1].replace(/,/g,''));
            return null;
        }
        function pickName(card){
            // Prefer an explicit name element, then title attr, then text lines.
            const sels = ['.p-name em','.p-name a','.p-name','a[title]'];
            for(const s of sels){
                const e = card.querySelector(s);
                if(e){
                    let t = (e.innerText||'').trim();
                    if(t.length < 4) t = (e.getAttribute && (e.getAttribute('title')||'').trim()) || t;
                    if(t.length >= 4 && !pureNum.test(t)) return t;
                }
            }
            const lines = (card.innerText||'').split('\n').map(s=>s.trim()).filter(Boolean);
            for(const ln of lines){
                if(priceRe.test(ln) || pureNum.test(ln) || skipLine.test(ln)) continue;
                if(ln.length>=4) return ln;
            }
            return '';
        }
        function pickMerchant(card){
            const sels = ['.p-shop a','.p-shop','.curr-shop','.shopName'];
            for(const s of sels){ const e=card.querySelector(s); if(e && (e.innerText||'').trim()) return (e.innerText||'').trim(); }
            const lines = (card.innerText||'').split('\n').map(s=>s.trim()).filter(Boolean);
            for(const ln of lines){ if(ln.length<30 && /旗舰店|自营|专营店|专卖店|店$/.test(ln)) return ln; }
            return '';
        }
        function matchScore(name){
            if(!searched || !name) return 0;
            const toks = searched.toLowerCase().split(/[^0-9a-z一-龥]+/).filter(Boolean);
            const n = name.toLowerCase();
            let s = 0; for(const t of toks){ if(n.indexOf(t) >= 0) s++; }
            return s;
        }

        // Collect candidate cards (dedupe by element).
        let cards = Array.from(document.querySelectorAll('li.gl-item, .gl-item, li[data-sku], [data-sku]'));
        const cardSet = []; const cseen = new Set();
        for(const c of cards){ if(!cseen.has(c)){ cseen.add(c); cardSet.push(c); } }

        for(const card of cardSet){
            const idInfo = idFromCard(card);
            const price = pickPrice(card);
            const name = pickName(card);
            const hrefs = Array.from(card.querySelectorAll('a[href]')).map(a=>a.getAttribute('href')).slice(0,5);
            let url = null, srcType = null, reason = '';
            if(idInfo){ url = 'https://item.jd.com/' + idInfo.id + '.html'; srcType = idInfo.type; }

            // Record rejected raw hrefs (chat/cart/etc) for debugging.
            for(const h of hrefs){ if(h && rejectHost.test(h) && rejectedUrls.indexOf(h)<0 && rejectedUrls.length<50) rejectedUrls.push(h); }

            if(!url) reason = 'no product id';
            else if(!name || name.length<4) reason = 'no name';
            else if(price===null) reason = 'no price';

            if(cardsSample.length < 5){
                cardsSample.push({
                    text: (card.innerText||'').trim().slice(0,300),
                    hrefs: hrefs,
                    product_id: idInfo ? idInfo.id : null,
                    product_url: url,
                    price: price,
                    name: name,
                    reason: reason || 'ok'
                });
            }

            if(reason) continue;
            if(seen.has(url)) continue;
            seen.add(url);
            validUrls.push(url);
            results.push({
                product_name: name.slice(0,200),
                price: price,
                merchant: pickMerchant(card),
                url: url,
                match_score: matchScore(name),
                source_url_type: srcType
            });
        }
        results.sort((a,b)=> b.match_score - a.match_score);
        return {results: results, cardsSample: cardsSample, validUrls: validUrls,
                rejectedUrls: rejectedUrls, totalCards: cardSet.length};
    }
    """

    @staticmethod
    def _save_text(path, text):
        """Save a small text debug file (never crashes the scraper)."""
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text if text else '')
        except Exception as e:
            print(f'[debug] Could not save {path}: {e}')

    def find_real_product_container(self, element):
        """Given a candidate element (e.g. a small [data-sku]), climb up to 6
        parent levels and return the first ancestor that looks like a real
        product card (enough text + a price + a JD item link). Falls back to the
        original element if none is found."""
        js = r"""el => {
            const priceRe = /[￥¥]\s*[0-9]/;
            function ok(node){
                if(!node) return false;
                const txt = (node.innerText||'').trim();
                if(txt.length <= 20) return false;
                if(!priceRe.test(txt)) return false;
                if(!node.querySelector('a[href*="item.jd.com"], a[href*="item.jd.hk"]')) return false;
                return true;
            }
            let cur = el;
            for(let i=0;i<6 && cur;i++){
                if(ok(cur)) return cur;
                cur = cur.parentElement;
            }
            return el;
        }"""
        try:
            handle = element.evaluate_handle(js)
            el = handle.as_element()
            return el if el is not None else element
        except Exception:
            return element

    @staticmethod
    def _name_from_text(text):
        """Pick a product-looking line from a block of card text."""
        if not text:
            return None
        skip = re.compile(r'已售|评价|万\+|条评价|加入购物车|对比|关注|优惠券|满[0-9]|'
                          r'旗舰店|自营|专营店|专卖店|排序|综合|销量|价格')
        for ln in [s.strip() for s in text.split('\n') if s.strip()]:
            if re.search(r'[￥¥]\s*[0-9]', ln):
                continue
            if skip.search(ln):
                continue
            if len(ln) >= 4:
                return ln[:200]
        return None

    @staticmethod
    def _id_from_string(s):
        """Pull a JD numeric product id (>=6 digits) out of a URL/text string."""
        if not s:
            return None
        m = re.search(r'item\.jd\.(?:com|hk)/([0-9]{6,})\.html', s, re.I)
        if m:
            return m.group(1)
        m = re.search(r'[?&](?:pid|sku|skuId|wareId|wareid)=([0-9]{6,})', s, re.I)
        if m:
            return m.group(1)
        return None

    def normalize_jd_product_url(self, raw_url, card_element=None):
        """Turn whatever we found into a clean product URL, or None.

        Accepts item.jd.com / item.jd.hk. Rejects chat/cart/search/shop/etc.
        If a chat URL carries pid=/sku=/wareId=, or the card has a
        data-sku/data-pid/data-wareid attribute, or the HTML has "sku":"123",
        it rebuilds https://item.jd.com/<id>.html from that id."""
        pid = self._id_from_string(raw_url) if raw_url else None
        if not pid and card_element is not None:
            for attr in ('data-sku', 'data-pid', 'data-wareid', 'data-spu', 'sku'):
                try:
                    v = card_element.get_attribute(attr)
                except Exception:
                    v = None
                if v and re.fullmatch(r'[0-9]{6,}', v.strip()):
                    pid = v.strip()
                    break
        if not pid and card_element is not None:
            try:
                html = card_element.inner_html()
            except Exception:
                html = ''
            m = re.search(r'["\'](?:sku|skuId|wareId|wareid)["\']?\s*:\s*["\']?([0-9]{6,})',
                          html or '', re.I)
            if m:
                pid = m.group(1)
        if pid:
            return f'https://item.jd.com/{pid}.html'
        return None

    @staticmethod
    def _keyword_score(searched, name):
        """Count how many keywords from the searched product appear in the name."""
        if not searched or not name:
            return 0
        toks = [t for t in re.split(r'[^0-9a-zA-Z一-龥]+', searched.lower()) if t]
        low = name.lower()
        return sum(1 for t in toks if t in low)

    def extract_products_js(self, page, safe, searched='', verbose=False):
        """PRIMARY extractor: run _EXTRACT_JS in the page. It scans product CARDS
        (not just links), derives the product id (pid / data-sku / etc.), and
        rebuilds https://item.jd.com/<id>.html. Saves debug files."""
        try:
            out = page.evaluate(self._EXTRACT_JS, searched)
        except Exception as e:
            print(f'[debug] JS extraction failed: {e}')
            return []
        if not isinstance(out, dict):
            return []
        results = out.get('results', []) or []
        sample = out.get('cardsSample', []) or []
        valid = out.get('validUrls', []) or []
        rejected = out.get('rejectedUrls', []) or []

        # Save the requested debug files.
        self._save_text(os.path.join('debug', f'jd_{safe}_valid_urls.txt'),
                        '\n'.join(valid))
        self._save_text(os.path.join('debug', f'jd_{safe}_rejected_urls.txt'),
                        '\n'.join(rejected))
        sample_lines = []
        for i, c in enumerate(sample):
            sample_lines.append(
                f'--- card {i+1} (reason: {c.get("reason")}) ---\n'
                f'name: {c.get("name")}\nprice: {c.get("price")}\n'
                f'product_id: {c.get("product_id")}\nproduct_url: {c.get("product_url")}\n'
                f'hrefs: {c.get("hrefs")}\ntext: {c.get("text")}\n')
        self._save_text(os.path.join('debug', f'jd_{safe}_cards_sample.txt'),
                        '\n'.join(sample_lines))

        print(f'[debug] Valid product URLs extracted: {len(valid)}')
        # Show the first few failed cards on screen (helps diagnose fast).
        shown = 0
        for c in sample:
            if c.get('reason') != 'ok' and shown < 3:
                shown += 1
                print(f'[debug] Rejected card {shown}: reason={c.get("reason")}, '
                      f'id={c.get("product_id")}, hrefs={c.get("hrefs")}')

        products = []
        for r in results:
            products.append({
                'product_name': r.get('product_name'),
                'price': r.get('price'),
                'merchant': r.get('merchant') or '未知商家',
                'url': r.get('url'),
                'platform': self.store_name,
                'match_score': r.get('match_score', 0),
                'source_url_type': r.get('source_url_type') or 'item_link',
            })
        return products

    def extract_from_cards(self, page, items, safe, searched='', verbose=False):
        """SECONDARY extractor (Python): for each found card, climb to its real
        container, read name/price, and build a clean product URL via
        normalize_jd_product_url (item link -> pid -> data-sku -> HTML)."""
        products = []
        seen = set()
        failed = 0
        for item in items:
            container = self.find_real_product_container(item)
            try:
                ctext = container.inner_text() or ''
            except Exception:
                ctext = ''

            name = self._first_text(container, self.NAME_SELECTORS) or self._name_from_text(ctext)
            price = self._parse_price(self._first_text(container, self.PRICE_SELECTORS))
            if price is None:
                price = self._price_from_text(ctext)
            merchant = self._first_text(container, self.MERCHANT_SELECTORS)

            # Build a clean product URL: try each link, then card attributes/HTML.
            url = None
            src = None
            try:
                for a in container.query_selector_all('a[href]'):
                    raw = a.get_attribute('href')
                    u = self.normalize_jd_product_url(raw, None)
                    if u:
                        url = u
                        src = 'item_link' if raw and 'item.jd' in raw else 'pid_from_chat'
                        break
            except Exception:
                pass
            if not url:
                u = self.normalize_jd_product_url(None, container)
                if u:
                    url = u
                    src = 'data_sku'

            if not (name and price is not None and url):
                if failed < 5:
                    failed += 1
                    print(f'[debug] Failed card {failed}: name={bool(name)} '
                          f'price={price} url={bool(url)}')
                    print(f'  text: {ctext[:300]!r}')
                continue

            if url in seen:
                continue
            seen.add(url)
            products.append({
                'product_name': name[:200],
                'price': price,
                'merchant': merchant if merchant else '未知商家',
                'url': url,
                'platform': self.store_name,
                'match_score': self._keyword_score(searched, name),
                'source_url_type': src or 'item_link',
            })
            if self.limit is not None and len(products) >= self.limit:
                break
        return products

    def extract_from_page_text(self, page, searched='', verbose=False):
        """LAST-RESORT extractor: scan the visible page text for product-looking
        blocks (keyword + a ￥price). Less accurate; URLs are empty."""
        try:
            body = page.inner_text('body')
        except Exception:
            body = ''
        if not body:
            return []
        lines = [l.strip() for l in body.split('\n') if l.strip()]
        price_re = re.compile(r'[￥¥]\s*([0-9][0-9,]*(?:\.\d+)?)')
        keywords = ['大疆', 'dji', 'osmo', 'pocket']
        products = []
        seen = set()
        for i, ln in enumerate(lines):
            low = ln.lower()
            if not any(k in low for k in keywords):
                continue
            window = ' '.join(lines[i:i + 4])
            m = price_re.search(window)
            if not m:
                continue
            name = ln[:200]
            if name in seen:
                continue
            seen.add(name)
            products.append({
                'product_name': name,
                'price': float(m.group(1).replace(',', '')),
                'merchant': '未知商家',
                'url': '',
                'platform': self.store_name,
                'match_score': self._keyword_score(searched, name),
                'source_url_type': 'text_fallback',
            })
        if verbose:
            print(f'[debug] page-text fallback found {len(products)} blocks.')
        return products

    # --------------------------- diagnostics ------------------------------- #
    def _attach_network_logging(self, page, name):
        """Attach listeners that record console errors, page errors, failed
        requests and bad (>=400) responses for JD-related URLs. Returns
        (log_path, logs) — call _write_network_log(...) later to save them."""
        os.makedirs('debug', exist_ok=True)
        log_path = os.path.join('debug', f'jd_{self._safe_filename(name)}_network.log')
        logs = []

        def relevant(url):
            u = (url or '').lower()
            return any(k in u for k in self.NETWORK_KEYWORDS)

        def on_console(msg):
            try:
                if msg.type in ('error', 'warning'):
                    logs.append(f'[console:{msg.type}] {msg.text}')
            except Exception:
                pass

        def on_pageerror(err):
            try:
                logs.append(f'[pageerror] {err}')
            except Exception:
                pass

        def on_requestfailed(req):
            try:
                if relevant(req.url):
                    logs.append(f'[requestfailed] {req.url} :: {req.failure}')
            except Exception:
                pass

        def on_response(resp):
            try:
                if resp.status >= 400 and relevant(resp.url):
                    logs.append(f'[response {resp.status}] {resp.url}')
            except Exception:
                pass

        page.on('console', on_console)
        page.on('pageerror', on_pageerror)
        page.on('requestfailed', on_requestfailed)
        page.on('response', on_response)
        return log_path, logs

    def _collect_js_diagnostics(self, page):
        """Read useful in-page values that explain why the skeleton stays."""
        script = r"""() => {
            const perf = (performance.getEntriesByType('resource') || [])
                .map(e => e.name)
                .filter(u => /(jd|3\.cn|search|api)/i.test(u))
                .slice(0, 50);
            return {
                readyState: document.readyState,
                href: location.href,
                bodyTextLength: (document.body && document.body.innerText) ? document.body.innerText.length : 0,
                scriptTags: document.scripts.length,
                imgTags: document.images.length,
                links: document.links.length,
                dataSkuElements: document.querySelectorAll('[data-sku]').length,
                itemJdLinks: document.querySelectorAll('a[href*="item.jd.com"]').length,
                perfResourceSample: perf
            };
        }"""
        try:
            return page.evaluate(script)
        except Exception as e:
            return {'error': str(e)}

    def _write_network_log(self, log_path, logs, page=None):
        """Save collected network logs plus JS diagnostics to a text file."""
        try:
            lines = list(logs)
            if page is not None:
                diag = self._collect_js_diagnostics(page)
                lines.append('')
                lines.append('==== JS DIAGNOSTICS ====')
                for k, v in diag.items():
                    lines.append(f'{k}: {v}')
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(str(x) for x in lines) if lines else '(no network events captured)')
            print(f'[debug] Network + JS diagnostics saved to: {log_path}')
        except Exception as e:
            print(f'[debug] Could not write network log: {e}')

    # --------------------------- session handling -------------------------- #
    def _launch_context(self, playwright, headless=False):
        """Launch (or reuse) JD's persistent browser profile.

        Tries the user's REAL installed Chrome first (channel="chrome") with
        Chrome's OWN default user-agent — the most normal, least suspicious
        setup. Only if that fails do we fall back to Playwright's bundled
        Chromium (which then needs a desktop user-agent to look right).
        Returns a Playwright BrowserContext (close it with context.close()).

        Login is handled separately by ensure_logged_in(), so this does NOT
        prompt for login.
        """
        os.makedirs(self.PROFILE_DIR, exist_ok=True)
        try:
            context = playwright.chromium.launch_persistent_context(
                self.PROFILE_DIR,
                channel='chrome',
                headless=headless,
                viewport={'width': 1366, 'height': 900},
            )
            print('[debug] Launched your installed Google Chrome (channel="chrome").')
        except Exception as e:
            print(f'[debug] Could not launch installed Chrome ({e}).')
            print('[debug] Falling back to Playwright Chromium with a desktop user-agent.')
            context = playwright.chromium.launch_persistent_context(
                self.PROFILE_DIR,
                headless=headless,
                user_agent=DESKTOP_USER_AGENT,
                viewport={'width': 1366, 'height': 900},
            )
        return context

    def is_logged_in(self, page):
        """Practical (not perfect) check of whether the JD profile is logged in.
        Opens the account/home page and looks at where it lands and what text is
        shown. Returns True if it looks logged in, False otherwise."""
        try:
            page.goto('https://home.jd.com/', wait_until='domcontentloaded')
        except Exception:
            pass
        time.sleep(3)
        try:
            url = (page.url or '').lower()
        except Exception:
            url = ''
        try:
            title = page.title() or ''
        except Exception:
            title = ''
        try:
            content = page.content()
        except Exception:
            content = ''

        # Strong signal: JD sent us to the passport/login page => NOT logged in.
        if 'passport.jd.com' in url or 'login.aspx' in url or '/login' in url:
            return False
        if '欢迎登录' in title:
            return False
        # Account page indicators => logged in.
        if any(m in content for m in self.ACCOUNT_MARKERS):
            return True
        # Login prompts / QR indicators => NOT logged in.
        if any(m in content for m in self.LOGIN_MARKERS):
            return False
        # If we stayed on the home/account page with no login prompts, assume ok.
        if 'home.jd.com' in url:
            return True
        return False

    def ensure_logged_in(self, headless=False, force_login=False):
        """Make sure the JD profile is logged in BEFORE scraping.

        - Opens JD in your real Chrome using the saved profile.
        - If already logged in (and not force_login), returns True immediately.
        - Otherwise opens the JD login page and waits for you to log in by hand
          (scan QR, pass any verification), then verifies and returns True/False.
        Saves debug/jd_login_failed.png/.html if verification fails.
        """
        with sync_playwright() as playwright:
            context = self._launch_context(playwright, headless=headless)
            page = context.pages[0] if context.pages else context.new_page()
            try:
                if not force_login and self.is_logged_in(page):
                    print('JD is already logged in. Good to go.')
                    context.close()
                    return True

                # The user must log in manually.
                print('')
                print('Please login to JD in the opened browser window.')
                print('Scan the QR code, complete any verification, and wait until JD')
                print('shows the login success / account page. Then press Enter here.')
                try:
                    page.goto('https://passport.jd.com/new/login.aspx',
                              wait_until='domcontentloaded')
                except Exception:
                    pass

                if headless:
                    print('Headless mode is ON, so no window is visible. '
                          'Please re-run WITHOUT headless mode to log in.')
                    context.close()
                    return False

                input('After you have logged in and see your JD account page, press Enter here...')

                if self.is_logged_in(page):
                    print('JD login verified. Your browser profile is now trusted.')
                    context.close()
                    return True

                print('Could not verify your JD login. Please try again and make sure the '
                      'JD account/home page is fully visible before pressing Enter.')
                save_debug_artifacts(page, 'jd_login_failed')  # debug/jd_login_failed.png/.html
                context.close()
                return False
            except Exception as e:
                print(f'[debug] Login flow error: {e}')
                try:
                    context.close()
                except Exception:
                    pass
                return False

    def check_login_status(self, headless=True):
        """Non-interactive login check (used by the Streamlit 'Verify' button).
        Returns True/False without prompting the user."""
        try:
            with sync_playwright() as playwright:
                context = self._launch_context(playwright, headless=headless)
                page = context.pages[0] if context.pages else context.new_page()
                ok = self.is_logged_in(page)
                context.close()
                return ok
        except Exception as e:
            print(f'[debug] Login status check error: {e}')
            return False

    # --------------------------- attach-to-Chrome mode --------------------- #
    def connect_to_existing_chrome(self, playwright, chrome_debug_url):
        """Connect to the user's OWN Chrome that was started with
        --remote-debugging-port. Returns (browser, context) or (None, None).
        We do NOT launch a new profile and do NOT modify the user's session."""
        try:
            browser = playwright.chromium.connect_over_cdp(chrome_debug_url)
        except Exception as e:
            print('')
            print(f'Could not connect to your Chrome at {chrome_debug_url}.')
            print(f'[debug] Reason: {e}')
            print('To use attach mode, CLOSE ALL Chrome windows first, then start Chrome')
            print('with remote debugging (PowerShell), for example:')
            print('  & "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
                  '--remote-debugging-port=9222 '
                  '--user-data-dir="$PWD\\browser_profiles\\jd_manual" "https://global.jd.com/"')
            return None, None

        contexts = browser.contexts
        context = contexts[0] if contexts else browser.new_context()
        print('Connected to your existing Chrome session. ✅')
        return browser, context

    def verify_jd_ready(self, page, keyword=None):
        """Check that JD SEARCH actually works in this browser (not just login).
        Opens a test search for `keyword` and waits for real product cards, while
        watching for access-frequency / security messages."""
        keyword = keyword or getattr(self, 'verify_keyword', None) or 'dji'
        test_url = ('https://search.jd.com/Search?keyword='
                    + urllib.parse.quote(keyword) + '&enc=utf-8')
        print(f'Verifying JD search works (test keyword: {keyword})...')
        try:
            page.goto(test_url, wait_until='domcontentloaded')
        except Exception as e:
            print(f'[debug] Could not open JD test search: {e}')
            return False

        failure_markers = ['访问频率', '无法搜索', '抱歉', '安全验证', '验证一下', 'risk_handler']
        waited = 0
        while waited < 30:
            try:
                content = page.content()
            except Exception:
                content = ''
            try:
                url = (page.url or '').lower()
            except Exception:
                url = ''
            if 'risk_handler' in url or any(m in content for m in failure_markers):
                print('JD showed a security / access-frequency message during the test search.')
                save_debug_artifacts(page, 'jd_verify_failed')
                return False
            for sel in ['.gl-item', '[data-sku]', 'a[href*="item.jd.com"]']:
                try:
                    if page.query_selector_all(sel):
                        print('JD search is working — real product cards found. ✅')
                        return True
                except Exception:
                    pass
            print(f'Waiting for JD test results... {waited}s / 30s')
            try:
                page.mouse.wheel(0, 800)
            except Exception:
                pass
            time.sleep(3)
            waited += 3

        print('JD test search only showed loading/skeleton (no product cards).')
        save_debug_artifacts(page, 'jd_verify_failed')
        return False

    def ensure_attached_ready(self, headless=False, keyword=None):
        """For attach mode: connect to the user's Chrome and confirm JD search
        actually works. Returns True/False. Does not modify the user's session."""
        with sync_playwright() as playwright:
            browser, context = self.connect_to_existing_chrome(playwright, self.chrome_debug_url)
            if context is None:
                return False
            page = context.new_page()
            try:
                return self.verify_jd_ready(page, keyword=keyword)
            finally:
                try:
                    page.close()
                except Exception:
                    pass
                try:
                    browser.close()  # disconnect CDP; does NOT close the user's Chrome
                except Exception:
                    pass

    def _get_scrape_page(self, playwright, headless=False):
        """Get a (browser, context, page) to scrape with.
        - attach mode: connect to the user's Chrome; context is theirs (do NOT
          close it), browser is the CDP link (disconnect with browser.close()).
        - normal mode: launch our persistent profile; browser is None and the
          context is ours (close it).
        Returns (browser, context, page); page is None if attach failed."""
        if self.attach_chrome:
            browser, context = self.connect_to_existing_chrome(playwright, self.chrome_debug_url)
            if context is None:
                return None, None, None
            return browser, context, context.new_page()
        context = self._launch_context(playwright, headless=headless)
        return None, context, context.new_page()

    def _release_scrape_page(self, browser, context, page):
        """Close what we opened. In attach mode we only close our page and
        disconnect CDP — we never close the user's context/tabs."""
        try:
            if page is not None:
                page.close()
        except Exception:
            pass
        if self.attach_chrome:
            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass
        else:
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass

    # --------------------------- search behaviour -------------------------- #
    def search_from_jd_homepage(self, page, product_name, verbose=False):
        """Search like a normal user: open the homepage, type into the search
        box, submit, wait, and scroll. Returns True if we ended up on a search
        results page (search.jd.com / list.jd.com)."""
        try:
            page.goto('https://www.jd.com', wait_until='domcontentloaded')
        except Exception as e:
            print(f'[debug] Could not open JD homepage: {e}')
            return False
        time.sleep(3)

        box = None
        for sel in self.SEARCH_INPUT_SELECTORS:
            try:
                box = page.wait_for_selector(sel, timeout=4000)
            except Exception:
                box = None
            if box:
                if verbose:
                    print(f'[debug] Using search box selector: {sel}')
                break
        if box is None:
            print('[debug] Could not find the JD search box on the homepage.')
            return False

        try:
            box.click()
            box.fill('')
            try:
                box.type(product_name, delay=60)
            except Exception:
                box.fill(product_name)
        except Exception as e:
            print(f'[debug] Could not type into the search box: {e}')
            return False

        submitted = False
        try:
            box.press('Enter')
            submitted = True
        except Exception:
            submitted = False
        if not submitted:
            for sel in self.SEARCH_BUTTON_SELECTORS:
                try:
                    btn = page.query_selector(sel)
                except Exception:
                    btn = None
                if btn:
                    try:
                        btn.click()
                        submitted = True
                        break
                    except Exception:
                        continue

        try:
            page.wait_for_load_state('domcontentloaded', timeout=10000)
        except Exception:
            pass
        time.sleep(6)
        self._scroll_page(page)

        url = (page.url or '').lower()
        return ('search.jd.com' in url) or ('list.jd.com' in url)

    def debug_user_can_load_jd_manually(self, page, product_name):
        """Ask the user to manually make real products appear, then re-check the
        DOM for product cards / data-sku / item links. Returns the product cards
        found (empty list if the DOM still has no real product data)."""
        print('')
        print(f'MANUAL CHECK NEEDED for: {product_name}')
        print('1) In the opened Chrome window, please REFRESH the page (F5).')
        print('2) If it is still empty, manually SEARCH the product on JD.')
        print('3) Do NOT press Enter until REAL product cards (names, prices, images) are visible.')
        input('Press Enter ONLY after real JD products are visible on screen...')

        items = self._find_product_cards(page, verbose=True)
        try:
            skus = page.query_selector_all('[data-sku]')
        except Exception:
            skus = []
        try:
            item_links = page.query_selector_all('a[href*="item.jd.com"]')
        except Exception:
            item_links = []
        print(f'[debug] After manual action -> product cards: {len(items)}, '
              f'[data-sku]: {len(skus)}, item.jd.com links: {len(item_links)}')

        if len(items) == 0 and len(skus) == 0 and len(item_links) == 0:
            print('Even after manual action, the DOM still has no JD product data. '
                  'This means JD is not giving this browser real product data. '
                  'The scraper cannot extract products from skeleton-only HTML.')
            return []
        return items

    # --------------------------- direct item URL --------------------------- #
    def scrape_product_by_url(self, url, headless=False, verbose=True):
        """Open a JD product (item) page directly and read its name, price,
        merchant and URL. Used when the catalog provides a product_url."""
        if not url.startswith('http'):
            url = 'https:' + url
        if verbose:
            print(f'Opening product URL directly: {url}')
        safe = self._safe_filename(url)

        with sync_playwright() as playwright:
            browser, context, page = self._get_scrape_page(playwright, headless=headless)
            if page is None:
                return []
            log_path, net_logs = self._attach_network_logging(page, safe)

            try:
                page.goto(url, wait_until='domcontentloaded')
            except Exception as e:
                print(f'[debug] Could not open product URL: {e}')
            time.sleep(5)
            self._scroll_page(page, steps=3, pause=0.8)
            self._handle_captcha(page, headless=headless)

            name = self._first_text_page(page, self.ITEM_NAME_SELECTORS)
            if not name:
                try:
                    name = (page.title() or '').split('【')[0].replace('- 京东', '').strip() or None
                except Exception:
                    name = None

            price = None
            for sel in self.ITEM_PRICE_SELECTORS:
                price = self._parse_price(self._first_text_page(page, [sel]))
                if price is not None:
                    break
            if price is None:
                try:
                    price = self._price_from_text(page.inner_text('body'))
                except Exception:
                    price = None

            merchant = self._first_text_page(page, self.ITEM_MERCHANT_SELECTORS)

            self._write_network_log(log_path, net_logs, page)

            if not name:
                save_debug_artifacts(page, f'jd_url_{safe}_failed')
                print('Could not read product info from the URL page. '
                      'Saved a screenshot and HTML in the debug folder.')
                self._release_scrape_page(browser, context, page)
                return []

            product = {
                'product_name': name,
                'price': price,   # may be None; main.py handles that safely
                'merchant': merchant if merchant else '未知商家',
                'url': url,
                'platform': self.store_name,
            }
            self._release_scrape_page(browser, context, page)

        if verbose:
            print(f'[debug] URL product extracted: {product}')
        return [product]

    # --------------------------- main scrape method ------------------------ #
    def scrape_product_info(self, product_name, headless=False, verbose=True):
        original_name = product_name
        keyword = urllib.parse.quote(product_name)
        base_url = f"https://search.jd.com/Search?keyword={keyword}&enc=utf-8"
        if verbose:
            print(base_url)

        safe = self._safe_filename(original_name)
        pages = max(1, int(getattr(self, 'pages', 1) or 1))
        scroll_rounds = max(1, int(getattr(self, 'scroll_rounds', 5) or 5))

        all_products = []
        seen_urls = set()

        with sync_playwright() as playwright:
            browser, context, page = self._get_scrape_page(playwright, headless=headless)
            if page is None:
                return []
            log_path, net_logs = self._attach_network_logging(page, original_name)

            def load_page1():
                # Page 1: search like a human from the homepage, then fall back.
                reached = self.search_from_jd_homepage(page, original_name, verbose=verbose)
                if (not reached) or self._looks_like_homepage(page):
                    if verbose:
                        print('[debug] Homepage search did not reach results; trying direct URL.')
                    try:
                        page.goto(base_url, wait_until='domcontentloaded')
                    except Exception as e:
                        print(f'[debug] Direct search failed: {e}')
                    time.sleep(5)

            for pnum in range(1, pages + 1):
                if pnum == 1:
                    load_page1()
                    # Security / risk handling (page 1 only).
                    risk_attempts = 2
                    while risk_attempts > 0 and self._is_risk_page(page):
                        print('JD sent this browser to security verification.')
                        save_debug_artifacts(page, f'jd_{safe}_risk')
                        if headless:
                            print('Cannot solve verification in headless mode. '
                                  'Please re-run with headless mode turned OFF.')
                            break
                        input('Please solve the verification (and log in if asked) in the '
                              'browser window, then press Enter here to try again...')
                        load_page1()
                        risk_attempts -= 1
                    if self._looks_like_homepage(page):
                        print('JD redirected the search back to homepage. This usually means '
                              'JD blocked automated search or the search did not submit correctly.')
                else:
                    # JD pages advance as 1, 3, 5, ... via the &page= parameter.
                    jd_page = 2 * pnum - 1
                    page_url = f'{base_url}&page={jd_page}'
                    if verbose:
                        print(f'[debug] Opening page {pnum}: {page_url}')
                    try:
                        page.goto(page_url, wait_until='domcontentloaded')
                    except Exception as e:
                        print(f'[debug] Could not open page {pnum}: {e}')
                    time.sleep(5)

                # Wait for cards, then scroll slowly to load lazy ones.
                items = self._wait_for_products(page, timeout=90, interval=3, verbose=verbose)
                self._scroll_page(page, steps=scroll_rounds, pause=1.0)
                cards = self._find_product_cards(page)
                print(f'[debug] Page {pnum} cards found: {len(cards)}')

                # Page-1 empty handling (skeleton / manual / diagnostics).
                if len(cards) == 0:
                    if pnum == 1:
                        self._write_network_log(log_path, net_logs, page)
                        if self._looks_like_skeleton(page):
                            print('JD page is still showing loading placeholders. Products not ready.')
                        if not headless:
                            cards = self.debug_user_can_load_jd_manually(page, original_name)
                            if len(cards) == 0:
                                save_debug_artifacts(page, f'jd_{safe}_failed')
                    if len(cards) == 0:
                        continue  # try the next page (or finish)

                # ---- Extraction (product-ID based -> real item.jd.com URLs) ----
                page_products = self.extract_products_js(page, safe, searched=original_name, verbose=verbose)
                if not page_products:
                    if verbose:
                        print('[debug] JS extraction found none; trying Python card extraction.')
                    page_products = self.extract_from_cards(page, cards, safe,
                                                            searched=original_name, verbose=verbose)
                if not page_products and pnum == 1:
                    if verbose:
                        print('[debug] Card extraction found none; trying page-text fallback.')
                    page_products = self.extract_from_page_text(page, searched=original_name, verbose=verbose)

                print(f'[debug] Page {pnum} valid URLs: {len(page_products)}')

                # Merge + dedupe by URL as we go.
                for pr in page_products:
                    u = pr.get('url') or ''
                    if u and u in seen_urls:
                        continue
                    if u:
                        seen_urls.add(u)
                    all_products.append(pr)

                if self.limit is not None and len(all_products) >= self.limit:
                    if verbose:
                        print(f'[debug] Reached products_limit ({self.limit}); stopping pages.')
                    break

            self._release_scrape_page(browser, context, page)

        if not all_products:
            print('')
            print('No products were extracted. Possible reasons: JD showed only grey '
                  'loading boxes, a security check appeared, or your profile got logged out.')
            print("Check the 'debug' folder (cards_sample / rejected_urls / network log).")
            return []

        # Best keyword matches first, then keep up to products_limit.
        total_before = len(all_products)
        print(f'[debug] Total extracted before limit: {total_before}')
        all_products.sort(key=lambda p: p.get('match_score', 0), reverse=True)
        if self.limit is not None:
            all_products = all_products[:self.limit]
        print(f'[debug] Kept after products_limit={self.limit}: {len(all_products)}')

        print(f'[debug] Extracted usable products: {len(all_products)}')
        first = all_products[0]
        print('[debug] First result:')
        print(f'  product_name: {first.get("product_name")}')
        print(f'  price: {first.get("price")}')
        print(f'  url: {first.get("url")}')
        return all_products

    def scrape_product_info_by_weight(self, product_name, use_gpt=False, verbose=False, headless=False):
        product_name_original = product_name.lower().replace(' ', '%20')
        weight_original, product_name_no_w = self.get_weight_from_product_name(product_name_original)
        if weight_original is None:
            print('Error: weight is not specified in product name')
            return []
        products_info = self.scrape_product_info(product_name_original, headless=headless)
        if len(products_info) == 0:
            print(f'No merchants data retrieved for "{product_name}". '
                  'Skipping this product and continuing to the next one.')
            return []
        ordered_products, scores = self.get_best_matching_product(product_name_original, products_info)
        ordered_products = [product for product, score in zip(ordered_products, scores) if score > 0]
        if verbose: print(f'Retrieved {len(ordered_products)} merchants:', ordered_products)
        if verbose: print(f'Merchants scores:', scores)

        with sync_playwright() as playwright:
            browser, context, page = self._get_scrape_page(playwright, headless=headless)
            if page is None:
                return []
            page.goto(self.url, wait_until='domcontentloaded')
            self._handle_captcha(page, headless=headless)

            product_dict = []
            for j, product_info in enumerate(ordered_products):
                self.sleep()
                page.goto(product_info['url'])
                self._handle_captcha(page, headless=headless)

                #page.wait_for_selector('.item[data-sku]')
                products_list = page.query_selector_all('.item[data-sku]')
                if verbose: print(f'Scraping products merchant ({j+1}): {product_info["product_name"]}')
                if verbose: print(f'Scraped {len(products_list)} items in details page')

                # case no products in details page
                if len(products_list) < 2:
                    if weight_original not in product_info['product_name']:
                        continue
                    score = self.check_name_matching_score(product_name, product_info['product_name'],
                                                           remove_punctuation=True)
                    if score < 1:
                        continue
                    product_dict.append({'product_name': product_info['product_name'], 'price': product_info['price'],
                                         'merchant': product_info['merchant'], 'url': product_info['url'],
                                         'platform': self.store_name,
                                         'score': score})
                    if verbose: print(f'Added: {product_dict[-1]}')
                    continue

                for i, product in enumerate(products_list):
                    self.sleep()
                    page.wait_for_selector('.item[data-sku]')
                    try:
                        product_name_detail_original = products_list[i].text_content().strip()
                    except:
                        print(f'Could not scrape ({i+1}) {product}')
                        continue
                    if verbose: print(f'Scraping item ({i+1}): {product_name_detail_original}')
                    if weight_original not in product_name_detail_original and weight_original not in product_info['product_name']:
                        if verbose: print('Weight unknown')
                        continue
                    weight, product_name_detail = self.get_weight_from_product_name(product_name_detail_original)
                    if weight and weight != weight_original:
                        if verbose: print('Weight not matching')
                        continue
                    elif not weight and weight_original not in product_info['product_name']:
                        if verbose: print('Weight unknown')
                        continue
                    score = self.check_name_matching_score(product_name_no_w, product_name_detail, remove_punctuation=True)
                    if score < 1:
                        if verbose: print(f'Low matching score: {score}')
                        continue

                    # now click on it to get the price
                    sku_icons = page.query_selector_all('.item[data-sku]')
                    try:
                        sku_icons[i].click()
                        page.wait_for_load_state("load")
                    except:
                        if verbose: print('Failed to click on page')
                        continue
                    j = 10
                    while j > 0:  # 10 attempts to retrieve the price
                        try:
                            price_element = page.query_selector('.price')
                            if price_element is not None and len(price_element.text_content()) > 0:
                                break
                            self._handle_captcha(page, headless=headless)
                        except:
                            pass
                        page.reload()
                        page.wait_for_load_state("load")
                        self.sleep()
                        j -= 1
                    if j == 0:
                        if verbose: print(f'Price not found')
                        continue

                    # check for discounts
                    price_element = page.query_selector('.price')
                    if price_element is None or len(price_element.text_content()) < 1:
                        if verbose: print('Price not found')
                        continue
                    price = float(price_element.text_content())
                    product_dict.append({'product_name': f"{product_info['product_name']}-{product_name_detail_original}",
                                         'price': price,
                                         'merchant': product_info['merchant'], 'url': product_info['url'],
                                         'platform': self.store_name,
                                         'score': score})
                    if verbose: print(f'Added: {product_dict[-1]}')

            if len(product_dict) < 2:
                self._release_scrape_page(browser, context, page)
                if verbose: print('Final result:', product_dict)
                if len(product_dict) == 0:
                    if verbose: print('No results found')
                return product_dict

            product_dict = sorted(product_dict, key=lambda x: x['score'], reverse=True)

            # filter with chatgpt
            if use_gpt:
                gpt_scores = [self.check_name_matching_gpt(product['product_name'].split('-')[-1], product_name_original) for product in product_dict]
                gpt_product_dict = [product for i, product in enumerate(product_dict) if gpt_scores[i]]
                if verbose: print('GPT scores:', gpt_scores)
                if verbose: print(f'Before GPT filter ({len(product_dict)}):', product_dict)
                if verbose: print(f'After GPT filter ({len(gpt_product_dict)}):', gpt_product_dict)
                if len(gpt_product_dict) > 0:
                    product_dict = gpt_product_dict
            else:
                highest_score = product_dict[0]['score']
                product_dict = [entry for entry in product_dict if entry['score'] == highest_score]

            if verbose: print('Final result:', product_dict)

            self._release_scrape_page(browser, context, page)

        return product_dict


def test_scraper():
    scraper = JDScraper(products_limit=10, sleep_time=1)
    products = [
        '丹麦皇冠慕尼黑风味白肠500g',
        '丹麦皇冠慕尼黑风味白肠800g',
    ]
    prices = [
        71.5, 142
    ]
    for i, p in enumerate(products):
        print(f'Scraping product: {products[i]}')
        product_info = scraper.scrape_product_info_by_weight(p, use_gpt=False, verbose=True, headless=False)
        print(f'Target price: {prices[i]}')
        print('--------------------')
        time.sleep(5)


if __name__ == "__main__":
    test_scraper()
