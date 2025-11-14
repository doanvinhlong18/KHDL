import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import csv
import os
import time

# cấu hình
SHORT_TIMEOUT = 3000           # ms: thời gian chờ nhanh (3s)
CAPTCHA_WAIT_TIMEOUT = 30000  # ms: thời gian chờ khi phát hiện captcha (3 phút)
PAGE_RENDER_WAIT = 500         # ms: đợi ngay sau goto để bắt đầu render
HEADLESS = False               # False khi muốn mở browser nhìn trực tiếp để solve captcha thủ công
INPUT_LINK_FILE = "alonhadat_links.txt"
OUTPUT_CSV = "alonhadat_data.csv"
SCREENSHOT_DIR = "debug_screenshots"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)


async def detect_captcha(page):
    # iframe recaptcha/hcaptcha
    iframe = await page.query_selector("iframe[src*='recaptcha'], iframe[src*='hcaptcha']")
    if iframe:
        return True

    # các id/class chứa từ captcha/recaptcha
    possible = await page.query_selector_all("[id*=captcha], [class*=captcha], [class*=recaptcha], [id*=recaptcha], input[name='captcha']")
    if possible and len(possible) > 0:
        return True

    # text kiểm tra (vi + en)
    try:
        body_text = (await page.inner_text("body")).lower()
        if "xác minh" in body_text or "vui lòng xác minh" in body_text or "please verify" in body_text or "verify" in body_text:
            return True
    except Exception:
        pass

    return False


async def ensure_detail_loaded(page):
    # selector đại diện cho nội dung chi tiết (chọn nhiều selector phòng trường hợp khác nhau)
    main_selectors = "div.moreinfor, .detail.text-content, div.ct_title_box"
    try:
        # fast path
        await page.wait_for_selector(main_selectors, timeout=SHORT_TIMEOUT)
        return True
    except PlaywrightTimeoutError:
        # fast path failed -> kiểm tra captcha
        is_captcha = await detect_captcha(page)
        if is_captcha:
            # chụp màn hình debug
            ts = int(time.time())
            shot_path = os.path.join(SCREENSHOT_DIR, f"captcha_{ts}.png")
            try:
                await page.screenshot(path=shot_path, full_page=True)
                print(f"  -> CAPTCHA nghi ngờ: screenshot lưu ở {shot_path}")
            except Exception as e:
                print("  -> Lỗi chụp màn hình captcha:", e)

            # bạn có 2 lựa chọn: chờ lâu để solve tự động/ thủ công, hoặc pause để can thiệp
            # Mình dùng wait_for_selector với CAPTCHA_WAIT_TIMEOUT (chờ lâu)
            try:
                print(f"  -> Đang chờ up to {CAPTCHA_WAIT_TIMEOUT/1000:.0f}s để nội dung xuất hiện sau CAPTCHA...")
                await page.wait_for_selector(main_selectors, timeout=CAPTCHA_WAIT_TIMEOUT)
                return True
            except PlaywrightTimeoutError:
                print("  -> Hết thời gian chờ sau captcha. Bỏ qua trang này.")
                return False
        else:
            # không thấy CAPTCHA nhưng nội dung vẫn không hiện -> bỏ qua
            print("  -> Không thấy nội dung và không phát hiện CAPTCHA. Bỏ qua trang.")
            return False
    except Exception as e:
        print("  -> Lỗi khi chờ selector:", e)
        return False


async def scrape_detail(page, url):
    """Đi vào trang chi tiết và lấy thông tin, có xử lý captcha/timeouts."""
    await page.goto(url, timeout=60000)
    await page.wait_for_timeout(PAGE_RENDER_WAIT)

    ok = await ensure_detail_loaded(page)
    if not ok:
        return {"url": url, "error": "no_content_or_captcha_timeout"}

    data = {"url": url}

    # Giá và Diện tích
    try:
        gia = await page.locator(".moreinfor .price .value").text_content()
        dientich = await page.locator(".moreinfor .square .value").text_content()
        data["Giá"] = gia.strip() if gia else ""
        data["Diện tích"] = dientich.strip() if dientich else ""
    except Exception:
        # fallback: try other selectors
        try:
            gia2 = await page.locator(".ct_price").text_content()
            data["Giá"] = gia2.strip() if gia2 else ""
        except:
            data["Giá"] = ""
        try:
            dt2 = await page.locator(".ct_dt").text_content()
            data["Diện tích"] = dt2.strip() if dt2 else ""
        except:
            data["Diện tích"] = ""

    # Địa chỉ
    try:
        diachi = await page.locator(".address .value").text_content()
        data["Địa chỉ tài sản"] = diachi.strip() if diachi else ""
    except:
        # fallback
        try:
            addr = await page.locator(".ct_dis").text_content()
            data["Địa chỉ tài sản"] = addr.strip() if addr else ""
        except:
            data["Địa chỉ tài sản"] = ""
    try:
        rows = page.locator(".moreinfor1 table tr")
        count = await rows.count()
        for i in range(count):
            cells = rows.nth(i).locator("td")
            n_cells = await cells.count()
            for j in range(0, n_cells, 2):
                key = (await cells.nth(j).text_content() or "").strip()
                val = ""
                if j + 1 < n_cells:
                    val = (await cells.nth(j + 1).text_content() or "").strip()
                if key:
                    data[key] = val
    except Exception:
        pass

    return data


async def main():
    # load urls
    with open(INPUT_LINK_FILE, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip()]

    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context()
        page = await context.new_page()

        for idx, url in enumerate(urls):
            print(f"[{idx+1}/{len(urls)}] Scraping: {url}")
            try:
                data = await scrape_detail(page, url)
                results.append(data)
            except Exception as e:
                print(f"  -> Lỗi khi cào {url}: {e}")
                # chụp screenshot debug
                try:
                    ts = int(time.time())
                    path = os.path.join(SCREENSHOT_DIR, f"error_{idx+1}_{ts}.png")
                    await page.screenshot(path=path, full_page=True)
                    print("  -> Screenshot lỗi lưu ở", path)
                except Exception:
                    pass
                # tiếp tục trang sau
                continue

        await browser.close()

    # ghi CSV (tự động unite headers)
    keys = set()
    for r in results:
        keys.update(r.keys())
    keys = list(keys)

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(results)

    print("✅ Done! Lưu file:", OUTPUT_CSV)


if __name__ == "__main__":
    asyncio.run(main())
