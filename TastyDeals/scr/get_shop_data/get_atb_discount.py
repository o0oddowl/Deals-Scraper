import time
import random
import json
import sqlite3
import base64
import re
from pathlib import Path

import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from bs4 import BeautifulSoup


def driver_options():
    options = uc.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    driver = uc.Chrome(options=options, enable_logging=True)
    return driver


def init_db(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            url TEXT PRIMARY KEY
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS availability (
            url TEXT,
            city TEXT,
            street TEXT,
            UNIQUE(url, city, street)
        )
    ''')
    conn.commit()
    return conn


def find_project_root(marker: str = "TastyDeals") -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if parent.name == marker:
            return parent
    raise FileNotFoundError(f"{marker} Not Found")

def add_cookies(driver, city_id, street_id, max_retries=5, delay=2):
    for attempt in range(1, max_retries + 1):
        try:
            driver.add_cookie({
                "name": "ncityid",
                "value": str(city_id),
                "domain": ".www.atbmarket.com",
                "path": "/"
            })
            driver.add_cookie({
                "name": "nstore_id",
                "value": str(street_id),
                "domain": ".www.atbmarket.com",
                "path": "/"
            })
            driver.refresh()
            return True 
        except Exception as e:
            print(f"[{attempt}/{max_retries}] Не вдалося додати cookie: {e}")
            time.sleep(delay)
    return False

def selenium(driver, link,  path_name="discount", is_cookie=False, city_id=None, street_id=None):
    project_root = find_project_root()
    html_dir = project_root / "html" / f"html_file_{path_name}"
    html_dir.mkdir(parents=True, exist_ok=True)
    soup = None 
    try:
        driver.get(link)
        if is_cookie:
            success = add_cookies(driver, city_id, street_id)
        scr = driver.page_source
        soup = BeautifulSoup(scr, "lxml")
    except Exception as e:
        print("SELENIUM ERROR: ", e)
    return soup


def get_city(driver):
    soup = selenium(driver, "https://www.atbmarket.com/catalog/287-ovochi-ta-frukti/f/discount")
    city = soup.find("select", id="city").find_all("option")[1:]
    city_list = []
    for city_info in city:
        city_list.append({
            "city_name": city_info.text.strip(),
            "city_id": city_info["value"]
        })
    return city_list


def get_street(driver, link):
    city_list = get_city(driver)
    street_info = []
    street_id_progress = 0
    try:
        project_root = find_project_root()
        json_dir = project_root / "data" / "json"
        json_dir.mkdir(parents=True, exist_ok=True)
        with open(f"{json_dir}/atb_street_info.json", "r") as file:
            data = json.load(file)
        return data    
    except FileNotFoundError:
        driver.get(link)
        driver.fullscreen_window()
        time.sleep(2)
        driver.find_elements(By.CLASS_NAME, "delivery-info__button")[1].click()
        time.sleep(1)
        driver.find_elements(By.CLASS_NAME, "square-input__container")[1].click()
        time.sleep(1)
        for progress, city_info in enumerate(city_list):
            print(f" Progress: {progress+1}/{len(city_list)}", end="\r")
            try:           
                driver.find_element(By.CLASS_NAME, "select2-selection--single").click()
                time.sleep(0.5)
                if not city_info["city_name"] == "Київ":
                    logs = driver.get_log("performance")
                    logs.clear()
                driver.find_element(By.CLASS_NAME, "select2-search__field").send_keys(city_info["city_name"] + Keys.ENTER)
                time.sleep(0.5)
                logs = driver.get_log("performance")
                requests_data = {}
                for entry in logs:
                        try:
                            log = json.loads(entry["message"])["message"]
                            if log["method"] == "Network.responseReceived":
                                url = log["params"]["response"]["url"]
                                mime_type = log["params"]["response"].get("mimeType", "")
                                request_id = log["params"]["requestId"]

                                if "getstore" in url and "json" in mime_type:
                                    body = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id})
                                    raw_body = body["body"]

                                    if body.get("base64Encoded"):
                                        raw_body = base64.b64decode(raw_body).decode("utf-8")
                                    json_data = json.loads(raw_body)
                                    matches = re.findall(r'<option [^>]*>(.*?)</option>', json_data["optselect"])
                                    for match in matches:
                                        if "Оберіть магазин" not in match:
                                            street_name = match.strip()
                                            street_info.append({
                                            "city_name": city_info["city_name"],
                                            "city_id": city_info["city_id"],
                                            "street_name": street_name,
                                        })
                                    for street_id in json_data["coordinates"]:
                                        street_info[street_id_progress]["street_id"] = street_id["id"]
                                        street_id_progress += 1
                                    break
                        except Exception as e:
                            print("")
                            print("ERROR:", e)
            except Exception as e:
                print("")
                print("SELENIUM ERROR:", e)
        driver.quit()
        project_root = find_project_root()
        json_dir = project_root / "data" / "json"
        json_dir.mkdir(parents=True, exist_ok=True)
        with open(f"{json_dir}/atb_street_info.json", "w") as file:
           json.dump(street_info, file, indent=5, ensure_ascii=False)    
        with open(f"{json_dir}/atb_street_info.json", "r") as file:
            data = json.load(file)
        return data    

def get_category_urls(driver):
    soup = selenium(driver, "https://www.atbmarket.com/catalog/287-ovochi-ta-frukti/f/discount")
    category_list = soup.find_all("a", class_=["category-menu__link-wrap", "js-dropdown-show"], href=True)[3:-9]
    
    category_urls = []
    for category_url in category_list:
        url = "https://www.atbmarket.com" + category_url["href"] + "/f/discount"
        category_urls.append(url)   
    return category_urls

def get_product_urls(driver):
    category_urls = get_category_urls(driver)
    street_info = get_street(driver, "https://www.atbmarket.com/catalog/287-ovochi-ta-frukti/f/discount")

    project_root = find_project_root()
    db_dir = project_root / "data" / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "product_urls.db"

    conn = init_db(db_path)
    cursor = conn.cursor()

    print("")
    for progress, street_param in enumerate(street_info):
        print(f" Progress: {progress+1}/{len(street_info)}", end="\r")
        if progress % 50 == 0:
            try:
                driver.quit()
                driver = driver_options()
            except:
                driver = driver_options()
        for category_url in category_urls:
            soup = selenium(driver, category_url, "products", True, street_param["city_id"], street_param["street_id"])     
            try:
                catalog_list = soup.find_all("article", class_=["catalog-item", "js-product-container"])
            except:
                time.sleep(3)
                catalog_list = soup.find_all("article", class_=["catalog-item", "js-product-container"])
            for product_url in catalog_list:
                try:
                    url = "https://www.atbmarket.com" + product_url.find("a", class_="catalog-item__photo-link", href=True)["href"]
                    cursor.execute("INSERT OR IGNORE INTO products (url) VALUES (?)", (url,))
                    cursor.execute("""
                        INSERT OR IGNORE INTO availability (url, city, street)
                        VALUES (?, ?, ?)
                    """, (url, street_param["city_name"], street_param["street_name"]))

                except Exception as e:
                    pass
                #    print("")
                #    print(f"Error processing product: {e}")

        conn.commit()

def get_product_inform():
    driver = driver_options()
    get_product_urls(driver)
    project_root = find_project_root()
    db_path = project_root / "data" / "db" / "product_urls.db"
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT url FROM products")
    product_urls = [row[0] for row in cursor.fetchall()]

    product_info = [] 
    print("")
    for progress, product_url in enumerate(product_urls):
        print(f" Progress: {progress+1}/{len(product_urls)}", end="\r")
        if progress % 100 == 0:
            try:
                driver.quit()
                driver = driver_options()
            except:
                driver = driver_options()
             
        try:
            soup = selenium(driver, product_url, "product_info")

            product_title = soup.find("h1", class_=["page-title", "product-page__title", "show"]).text.strip()
            product_price_top = float(soup.find("data", class_="product-price__top").text.split(" ")[0])
            product_price_bottom = float(soup.find("data", class_="product-price__bottom").text.split(" ")[0])
            discount_percent = int(((product_price_bottom - product_price_top) / product_price_bottom) * 100)

            try:
                discount_date = soup.find("span", class_="custom-product-label__date").text.strip().split(" ")[1]
            except:
                discount_date = None

            product_type_name = soup.find_all("div", class_="product-characteristics__name")
            product_type_value = soup.find_all("div", class_="product-characteristics__value")
            product_type = None
            for name, value in zip(product_type_name, product_type_value):
                if name.text.strip().lower() == "тип продукту":
                    product_type = value.text.strip()
                    break

            cursor.execute("""
                SELECT DISTINCT city, street 
                FROM availability 
                WHERE url = ?
            """, (product_url,))
            locations = cursor.fetchall()
            location_data = [{"city": city, "street": street} for city, street in locations]

            product_info.append({
                "shop_name": "АТБ",
                "location": location_data,
                "product_title": product_title,
                "product_type": product_type,
                "product_price_top": product_price_top,
                "product_price_bottom": product_price_bottom,
                "discount_percent": discount_percent,
                "discount_date": discount_date,
                "url": product_url,
            })

        except Exception as e:
            pass

    json_dir = project_root / "data" / "json"
    json_dir.mkdir(parents=True, exist_ok=True)

    with open(json_dir / "atb.json", "w", encoding="utf-8") as file:
        json.dump(product_info, file, indent=5, ensure_ascii=False)
    driver.quit()
        
def main():
    get_product_inform()

if __name__ == "__main__":
    main()
