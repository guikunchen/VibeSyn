import time
from urllib.parse import unquote
from pathlib import PurePosixPath
from playwright.sync_api import sync_playwright

URL = "https://www.chemtools.cn/iupac/smilesToIupac.html"

def get_iupac_from_image(page):
    img = page.locator('img[src*="/opsin/"]').first
    src = img.get_attribute("src")
    return unquote(PurePosixPath(src.split("?")[0]).stem)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    page.goto(URL)

    smiles = "[N+](=O)([O-])C1=C(C)C(=CC(=C1)[N+](=O)[O-])[N+](=O)[O-]"

    page.locator('input[type="text"]').first.fill(smiles)

    # 记录提交前的图片地址
    old_src = page.locator('img[src*="/opsin/"]').first.get_attribute("src") \
        if page.locator('img[src*="/opsin/"]').count() else None

    page.get_by_role("button", name="提交", exact=True).click()

    # 等待新结果出现，而不是读取旧图片
    page.wait_for_function(
        """oldSrc => {
            const img = document.querySelector('img[src*="/opsin/"]');
            return img && img.getAttribute("src") !== oldSrc;
        }""",
        arg=old_src,
        timeout=30000
    )

    iupac = get_iupac_from_image(page)

    print("SMILES:", smiles)
    print("IUPAC:", iupac)

    browser.close()
