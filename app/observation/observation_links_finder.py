import requests
from selenium import webdriver
import re

class ObservationLinksFinder:
    def __init__(self, base_url="https://www.spaceweatherlive.com"):
        self.base_url = base_url
        self.session = requests.Session()
        
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def get_observation_count(self, date_str):
        driver = webdriver.Chrome()
        driver.get(f"{self.base_url}/en/archive/{date_str}/observations.html")

        html = driver.page_source
        driver.quit()

        match = re.search(r'(\d+)\s+observations were shared by aurora chasers for this day', html, re.IGNORECASE)

        if match:
            number = int(match.group(1))
            return number
        return None

    def get_observation_links(self, date_str):
        obs_count = self.get_observation_count(date_str)
        links = []
        if obs_count is None:
            print("No observations")
            return links
        
        id=-1
        while len(links) < obs_count:
            id+=1
            url = f"{self.base_url}/en/archive/{date_str}/observations/{id}.html"
            
            try:
                resp = self.session.get(url, timeout=10)
                
                if resp.status_code == 200:
                    links.append(url)
                    print(f"Found: {url}")
                else:
                    continue
                    
            except Exception as e:
                print(f"Ошибка: {url} - {e}")
                continue
                
        return links