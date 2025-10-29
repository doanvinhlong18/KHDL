import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup
import time
import os

# Cấu hình
BASE_URL = "https://alonhadat.com.vn/nha-dat/can-ban/trang--{}.html"
SHORT_TIMEOUT = 3000        # ms: timeout ngắn khi không nghi ngờ captcha
CAPTCHA_WAIT_TIMEOUT = 30000  # ms: timeout dài khi phát hiện captcha (3 phút)
PAGE_RENDER_WAIT = 1000     # ms: nhỏ, đợi sau goto để page có thể bắt đầu load

async def page_has_list_items(page):
    """Trả về True nếu page đã có các div.content-item.item"""
    return await page.evaluate("() => document.querySelectorAll('div.content-item.item').length > 0")

async def detect_captcha(page):
    """Những kiểm tra đơn giản để phát hiện captcha trên trang"""
    # tìm iframe chứa recaptcha
    iframe = await page.query_selector("iframe[src*='recaptcha'], iframe[src*='hcaptcha']")
    if iframe:
        return True

    # tìm các phần tử thường dùng đặt tên captcha
    possible = await page.query_selector_all("[id*=captcha], [class*=captcha], [class*=recaptcha], [id*=recaptcha], input[name='captcha']")
    if possible and len(possible) > 0:
        return True

    # kiểm tra text hiển thị lỗi/verify (tiếng Việt/Anh)
    text_content = await page.inner_text("body")
    lowered = text_content.lower()
    if "xác minh" in lowered or "verify" in lowered or "please verify" in lowered or "vui lòng xác minh" in lowered:
        return True

    return False

async def crawl_alonhadat(max_page=100):
    all_links = []
    os.makedirs("debug_screenshots", exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        for i in range(1, max_page + 1):
            url = BASE_URL.format(i)
            print(f"\n=== Đang cào: {url} ===")
            try:
                await page.goto(url, timeout=60000)
                await page.wait_for_timeout(PAGE_RENDER_WAIT)

                # 1) Thử lấy items với timeout ngắn (fast path)
                try:
                    await page.wait_for_selector("div.content-item.item", timeout=SHORT_TIMEOUT)
                    print(" -> Item xuất hiện (fast path).")
                except PlaywrightTimeoutError:
                    # chưa thấy item trong timeout ngắn: kiểm tra captcha
                    print(" -> Không tìm thấy item nhanh, kiểm tra captcha...")
                    is_captcha = await detect_captcha(page)
                    if is_captcha:
                        print(" --> CAPTCHA nghi ngờ. Chụp màn hình và tăng timeout...")
                        # chụp màn hình để debug / gửi cho bạn xem
                        shot_path = f"debug_screenshots/page_{i}_captcha.png"
                        await page.screenshot(path=shot_path, full_page=True)
                        print(f" --> Screenshot lưu: {shot_path}")

                        # chờ lâu hơn để người dùng tự solve hoặc để site trả về nội dung
                        try:
                            await page.wait_for_selector("div.content-item.item", timeout=CAPTCHA_WAIT_TIMEOUT)
                            print(" --> Items xuất hiện sau khi chờ xử lý captcha.")
                        except PlaywrightTimeoutError:
                            print(" --> Hết thời gian chờ CAPTCHA mà vẫn không thấy items. Bỏ qua trang.")
                            continue
                    else:
                        # Không có captcha nhưng vẫn không thấy item -> bỏ qua trang
                        print(" --> Không có dấu hiệu CAPTCHA nhưng cũng không có item. Bỏ qua trang.")
                        continue

                # nếu đến đây thì đã có item => lấy html và parse
                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")
                items = soup.select("div.content-item.item")
                print(f" -> Số item thu được: {len(items)}")

                for item in items:
                    a = item.select_one(".ct_title a")
                    if a:
                        href = a.get("href")
                        if href and href.endswith(".html") and not href.startswith("/du-an-"):
                            full_link = "https://alonhadat.com.vn" + href
                            all_links.append(full_link)

                # small polite pause between pages
                await page.wait_for_timeout(800)  # 0.8s

            except Exception as e:
                print("Lỗi bất ngờ khi cào trang:", e)
                # lưu screenshot debug
                try:
                    await page.screenshot(path=f"debug_screenshots/error_page_{i}.png", full_page=True)
                    print(f" --> Screenshot lỗi lưu: debug_screenshots/error_page_{i}.png")
                except Exception:
                    pass
                continue

        await browser.close()

    # loại trùng
    all_links = list(dict.fromkeys(all_links))
    print(f"\nTổng link thu được: {len(all_links)}")
    # lưu file
    with open("alonhadat_links.txt", "w", encoding="utf-8") as f:
        for link in all_links:
            f.write(link + "\n")

    return all_links

if __name__ == "__main__":
    asyncio.run(crawl_alonhadat(max_page=200))
