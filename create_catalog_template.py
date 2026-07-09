# -*- coding: utf-8 -*-
"""Create inputs/catalog_template.xlsx with the simple 3-column format.

Run it once with:   python create_catalog_template.py
It produces a ready-to-edit Excel file that normal users can copy and fill in.

Columns
-------
product_name : your own label / reference for the product (also used to SEARCH
               JD when no URL is given).
promo_price  : your benchmark price. It is ONLY used AFTER scraping to compare
               scraped_price < promo_price. It is NEVER searched for.
product_url  : OPTIONAL. If you paste a JD product page link here, the scraper
               opens that exact page directly (more stable). If left empty, the
               scraper searches JD using product_name.
"""
import os
import pandas as pd

os.makedirs('inputs', exist_ok=True)

template = pd.DataFrame({
    'product_name': [
        '大疆DJI Osmo Pocket 3',      # no URL -> Search mode
        '大疆 OSMO Pocket 4 Pro',      # has URL -> Direct URL mode (example link)
        '西班牙风味香肠500g',           # no URL -> Search mode
    ],
    'promo_price': [1319, 3138, 53.52],
    'product_url': [
        '',                                        # empty = search by name
        'https://item.jd.com/100012345678.html',   # example: replace with a real JD link
        '',                                        # empty = search by name
    ],
})

out_path = os.path.join('inputs', 'catalog_template.xlsx')
template.to_excel(out_path, index=False)
print(f'Template created at {out_path}')
