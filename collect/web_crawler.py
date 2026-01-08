"""
Web Crawler for UIHash
Crawls web pages and extracts screenshots and DOM structure in Rico dataset format.
Supports scrolling and recursive link following.
"""

import os
import json
import time
import random
import argparse
from urllib.parse import urlparse, urljoin
from collections import deque
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

class WebCrawler:
    def __init__(self, headless=False, max_pages=10, max_scrolls=3, random_mode=False):
        options = Options()
        if headless:
            options.add_argument('--headless')
            # CUI環境（特にLinux/Docker）での安定生向上のためのオプション
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--start-maximized')
        options.add_argument('--log-level=3')
        options.add_argument('--ignore-certificate-errors')
        options.add_argument('--allow-running-insecure-content')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        self.driver.set_page_load_timeout(30)
        self.driver.set_script_timeout(30)
        self.max_pages = max_pages
        self.max_scrolls = max_scrolls
        self.visited_urls = set()
        self.queue = deque()
        self.random_mode = random_mode

    def crawl(self, start_url: str, output_dir: str):
        """
        Crawl a site starting from start_url.
        """
        self.start_domain = urlparse(start_url).netloc
        # Create domain-specific output directory
        timestamp = int(time.time())
        site_dirname = f"{self.start_domain.replace('.', '_')}_{timestamp}"
        self.site_output_dir = os.path.join(output_dir, site_dirname)
        
        # Reset state for new domain
        self.queue.clear()
        self.visited_urls.clear()
        
        self.queue.append(start_url)
        self.visited_urls.add(start_url)
        
        if not os.path.exists(self.site_output_dir):
            os.makedirs(self.site_output_dir)

        pages_crawled = 0
        while self.queue and pages_crawled < self.max_pages:
            url = self.queue.popleft()
            print(f"({pages_crawled + 1}/{self.max_pages}) Crawling: {url}")
            
            try:
                self.driver.get(url)
                time.sleep(3) # Wait for load
                
                # Process the page (scroll and capture)
                self._process_page(url)
                
                # Find new links
                self._extract_links(url)
                
                pages_crawled += 1
            except Exception as e:
                print(f"Error crawling {url}: {e}")

    def _process_page(self, url):
        """
        Capture screenshots and DOM while scrolling.
        """
        scroll_height = self.driver.execute_script("return document.body.scrollHeight")
        viewport_height = self.driver.execute_script("return window.innerHeight")
        
        current_scroll = 0
        scroll_count = 0
        
        while scroll_count < self.max_scrolls:
            # Capture current view
            timestamp = int(time.time())
            filename_base = f"web_{timestamp}_{scroll_count}"
            
            # Screenshot
            screenshot_path = os.path.join(self.site_output_dir, f"{filename_base}.png")
            self.driver.save_screenshot(screenshot_path)
            
            # DOM (Using JS for viewport-aware extraction)
            dom_data = self._extract_dom_js()
            if dom_data:
                json_path = os.path.join(self.site_output_dir, f"{filename_base}.json")
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(dom_data, f, indent=2)
                
            print(f"  Saved capture {scroll_count}: {filename_base} in {self.site_output_dir}")

            # Scroll down
            if current_scroll + viewport_height >= scroll_height:
                break # Reached bottom
            
            current_scroll += viewport_height
            self.driver.execute_script(f"window.scrollTo(0, {current_scroll});")
            time.sleep(1) # Wait for scroll/render
            scroll_count += 1

    def _extract_links(self, current_url):
        """
        Find links on the page and add to queue.
        """
        try:
            new_links = []
            elements = self.driver.find_elements(By.TAG_NAME, "a")
            for elem in elements:
                href = elem.get_attribute("href")
                if not href:
                    continue
                
                # Normalize URL
                href = href.split('#')[0]
                parsed = urlparse(href)
                
                # Check domain and visited
                if parsed.netloc == self.start_domain and href not in self.visited_urls:
                    self.visited_urls.add(href)
                    new_links.append(href)
            
            # Randomize order if enabled
            if self.random_mode:
                random.shuffle(new_links)
                
            self.queue.extend(new_links)
        except Exception as e:
            print(f"Error in extract_links: {e}")
            import traceback
            traceback.print_exc()

    def _extract_dom_js(self):
        """
        Extract visible DOM structure using JavaScript.
        This captures elements relative to the viewport.
        """
        js_script = """
        function getVisibleDom(node) {
            if (node.nodeType !== Node.ELEMENT_NODE) return [];
            
            const rect = node.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) return [];
            
            // Check if in viewport
            const viewportWidth = window.innerWidth;
            const viewportHeight = window.innerHeight;
            
            // Intersection check: checks if the element overlaps with the viewport
            if (rect.bottom < 0 || rect.top > viewportHeight || 
                rect.right < 0 || rect.left > viewportWidth) {
                return [];
            }
            
            // Check computed visibility
            const style = window.getComputedStyle(node);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
                return [];
            }

            const children = [];
            for (const child of node.children) {
                const childNodes = getVisibleDom(child);
                children.push(...childNodes);
            }
            
            const tagName = node.tagName.toLowerCase();
            
            // If it's a div, unwrap it (return children only)
            if (tagName === 'div') {
                return children;
            }

            // If it's an SVG, treat as a single image (ignore children like path, polygon)
            const childrenToUse = tagName === 'svg' ? [] : children;

            const interact = ['a', 'button', 'input', 'select', 'textarea'].includes(tagName);

            return [{
                "componentLabel": tagName,
                "bounds": [Math.round(rect.left), Math.round(rect.top), Math.round(rect.right), Math.round(rect.bottom)],
                "children": childrenToUse,
                "visible": true,
                "interact": interact
            }];
        }
        const roots = getVisibleDom(document.body);
        return roots.length > 0 ? roots[0] : null;
        """
        return self.driver.execute_script(js_script)

    def close(self):
        self.driver.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Web Crawler for UIHash")
    parser.add_argument("urls", nargs='+', help="Target URLs to crawl")
    parser.add_argument("--output", "-o", default="output_web", help="Output directory")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    parser.add_argument("--pages", type=int, default=10, help="Max pages to crawl per URL")
    parser.add_argument("--scrolls", type=int, default=3, help="Max scrolls per page")
    parser.add_argument("--random", action="store_true", help="Randomize link traversal order")
    
    args = parser.parse_args()
    
    crawler = WebCrawler(headless=args.headless, max_pages=args.pages, max_scrolls=args.scrolls, random_mode=args.random)
    try:
        for url in args.urls:
            # Check if it's a local file
            if os.path.exists(url):
                abs_path = os.path.abspath(url)
                # Convert to file:// URI
                url = "file:///" + abs_path.replace("\\", "/")
                print(f"Detected local file, converting to: {url}")
                
            crawler.crawl(url, args.output)
    finally:
        crawler.close()
