import os
import re
import time
import base64
import logging
from selenium import webdriver
from selenium.common.exceptions import (
    WebDriverException, TimeoutException, InvalidSessionIdException
)
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# === Nastavení logování ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("scraper.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)


# === Inicializace driveru ===
def init_driver(headless=True):
    logging.info("🚀 Spouštím nový Chrome driver...")
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    if headless:
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")  # Volitelně pro správné načítání
        #options.add_argument("--log-level=3")  # Ticho: pouze fatální chyby

    driver = webdriver.Chrome(options=options)
    return driver


# === Přihlášení ===
def login(driver, username, password):
    logging.info("🔐 Přihlašuji se na web...")
    driver.get("https://nasems.cz")
    time.sleep(2)
    driver.find_element(By.NAME, "login").send_keys(username)
    driver.find_element(By.NAME, "password").send_keys(password)
    driver.find_element(By.CSS_SELECTOR, "form input[type='submit']").click()
    time.sleep(3)


def sanitize_folder_name(name):
    # Odeber znaky, které nejsou povoleny ve jménu složky
    # (např. :, ", <, >, |, ?, *, /, \)
    name = name.strip()
    name = re.sub(r'[\\/*?:"<>|]', '_', name)
    return name


# === Zpracuj galerii ===
def process_gallery(driver):
    wait = WebDriverWait(driver, 10)

    # Otevři stránku s galeriemi
    driver.get("https://nasems.cz/prihlaseno/fotogalerie")
    time.sleep(3)

    # Najdi všechny galerie
    gallery_elements = driver.find_elements(By.CSS_SELECTOR, ".fotogalerie_containers .container")

    # Uložíme si kontejnery, protože po kliknutí se stránka přenačte
    galleries = gallery_elements.copy()

    logging.info(f"📁 Nalezeno {len(galleries)} galerií")

    for g_index in range(0, len(galleries)):
        logging.info(f"📂 Zpracovávám galerii {g_index + 1}/{len(galleries)}")
        try:
            # ZNOVU načti seznam galerií při každém kroku
            galleries = driver.find_elements(By.CSS_SELECTOR, ".fotogalerie_containers .container")
            gallery = galleries[g_index]

            driver.execute_script("arguments[0].scrollIntoView(true);", gallery)
            time.sleep(0.5)
            gallery.click()
            time.sleep(10)

            # Složka podle nadpisu galerie
            folder = driver.find_elements(By.CSS_SELECTOR, ".content .podnadpis label")

            raw_name = folder[0].text.strip()
            folder_name = sanitize_folder_name(raw_name)
            path = os.path.join("fotky", folder_name)
            os.makedirs(path, exist_ok=True)

            # Najdi všechny náhledy
            thumbnails = driver.find_elements(By.CSS_SELECTOR, ".fotografie_container .picture")

            for i, thumb in enumerate(thumbnails):
                try:
                    driver.execute_script("arguments[0].scrollIntoView(true);", thumb)
                    time.sleep(0.5)

                    try:
                        close_btn = driver.find_element(By.ID, "cboxClose")
                        if close_btn.is_displayed():
                            close_btn.click()
                            wait.until_not(EC.visibility_of_element_located((By.ID, "cboxOverlay")))
                    except:
                        pass

                    # Zapamatuj si starý src
                    try:
                        old_img = driver.find_element(By.CSS_SELECTOR, ".cboxPhoto")
                        old_src = old_img.get_attribute("src")
                    except:
                        old_src = None

                    thumb.click()

                    time.sleep(3)

                    # Počkej na nový obrázek
                    wait.until(lambda d: d.find_element(By.CSS_SELECTOR, ".cboxPhoto").get_attribute("src") != old_src)
                    full_img = driver.find_element(By.CSS_SELECTOR, ".cboxPhoto")
                    img_url = full_img.get_attribute("src")

                    if not img_url or not img_url.startswith("http"):
                        logging.warning("⚠️ Obrázek nemá platnou URL – přeskočeno.")
                        continue

                    # Selenium-only stahování
                    img_data = driver.execute_script("""
                        const [url, done] = arguments;
                        return new Promise(resolve => {
                            fetch(url).then(resp => resp.blob()).then(blob => {
                                const reader = new FileReader();
                                reader.onloadend = () => resolve(reader.result);
                                reader.readAsDataURL(blob);
                            }).catch(() => resolve(null));
                        });
                    """, img_url)

                    if img_data and img_data.startswith("data:image"):
                        header, encoded = img_data.split(",", 1)

                        pic_timestamp = int(time.time() * 1000)
                        pic_filename = f"{folder_name}_{pic_timestamp}.jpg"
                        full_path = os.path.join(path, pic_filename)

                        with open(full_path, "wb") as f:
                            f.write(base64.b64decode(encoded))

                        logging.info(f"✅ Uloženo: {full_path}")
                    else:
                        logging.error("❌ Chyba při získávání obrázku")

                    # Zavři modal
                    try:
                        driver.find_element(By.ID, "cboxClose").click()
                        wait.until_not(EC.visibility_of_element_located((By.ID, "cboxOverlay")))
                    except:
                        pass

                    time.sleep(1)

                except Exception as e:
                    logging.error(f"❌ Chyba u obrázku {i + 1}: {e}")

            # Zpět na seznam galerií
            driver.get("https://nasems.cz/prihlaseno/fotogalerie")
            time.sleep(10)

        except Exception as e:
            logging.error(f"❌ Chyba u galerie {g_index + 1}: {e}")


# 🔐 Získání údajů od uživatele
def prompt_credentials():
    username = input("Zadej uživatelské jméno: ").strip()
    try:
        import getpass
        password = getpass.getpass("Zadej heslo: ").strip()
    except Exception:
        print("⚠️ Nelze použít bezpečné zadání hesla – bude viditelné.")
        password = input("Zadej heslo: ").strip()
    return username, password


# === Robustní main s restartem ===
def main():
    max_retries = 5
    attempt = 0
    headless_mode = True

    username, password = prompt_credentials()

    while attempt < max_retries:
        driver = None
        try:
            driver = init_driver(headless_mode)
            login(driver, username, password)
            process_gallery(driver)
            break  # Úspěšně dokončeno

        except (InvalidSessionIdException, WebDriverException) as e:
            logging.error(f"🚨 Selenium chyba – restartuji session: {e}")
            attempt += 1
            time.sleep(2)

        except Exception as e:
            logging.exception(f"❌ Neočekávaná chyba: {e}")
            attempt += 1
            time.sleep(2)

        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass

    if attempt == max_retries:
        logging.critical("❌ Nepodařilo se dokončit skript ani po opakování.")


if __name__ == "__main__":
    main()
