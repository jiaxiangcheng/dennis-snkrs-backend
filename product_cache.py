import json
import aiohttp
import asyncio
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

class ProductCache:
    def __init__(self, cache_file: str = "products_cache.json"):
        self.cache_file = Path(cache_file)
        self.products_url = "https://www.dennis-snkrs.com/products.json"
        self.cache_duration = timedelta(hours=24)
        self.products_by_sku: Dict[str, dict] = {}
        self.last_update: Optional[datetime] = None

    def _extract_sku_from_html(self, body_html: str) -> Optional[str]:
        """Extract SKU from body_html field"""
        if not body_html:
            return None
        # Remove HTML tags and get the text content
        sku_match = re.search(r'>([A-Z0-9\-]+)<', body_html)
        if sku_match:
            return sku_match.group(1).strip()
        # Try without tags
        text = re.sub(r'<[^>]+>', '', body_html).strip()
        if text:
            return text
        return None

    async def _fetch_products(self) -> List[dict]:
        """Fetch products from dennis-snkrs.com"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.products_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('products', [])
                    else:
                        logger.error(f"Failed to fetch products: HTTP {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Error fetching products: {e}")
            return []

    def _build_sku_index(self, products: List[dict]):
        """Build SKU-based index from products"""
        self.products_by_sku = {}
        for product in products:
            sku = self._extract_sku_from_html(product.get('body_html', ''))
            if sku:
                # Store product with all its variants
                self.products_by_sku[sku] = product
                logger.debug(f"Indexed product: {product.get('title')} with SKU: {sku}")

    def _save_cache(self, products: List[dict]):
        """Save products to cache file"""
        try:
            cache_data = {
                'last_update': datetime.now().isoformat(),
                'products': products
            }
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved {len(products)} products to cache")
        except Exception as e:
            logger.error(f"Error saving cache: {e}")

    def _load_cache(self) -> Optional[List[dict]]:
        """Load products from cache file"""
        try:
            if not self.cache_file.exists():
                return None

            with open(self.cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            last_update_str = cache_data.get('last_update')
            if last_update_str:
                self.last_update = datetime.fromisoformat(last_update_str)
                # Check if cache is still valid
                if datetime.now() - self.last_update < self.cache_duration:
                    products = cache_data.get('products', [])
                    logger.info(f"Loaded {len(products)} products from cache")
                    return products
                else:
                    logger.info("Cache expired, will fetch new data")
            return None
        except Exception as e:
            logger.error(f"Error loading cache: {e}")
            return None

    async def refresh(self, force: bool = False):
        """Refresh product cache"""
        # Try to load from cache first
        if not force:
            cached_products = self._load_cache()
            if cached_products:
                self._build_sku_index(cached_products)
                return

        # Fetch new data
        logger.info("Fetching fresh product data...")
        products = await self._fetch_products()
        if products:
            self._build_sku_index(products)
            self._save_cache(products)
            self.last_update = datetime.now()
            logger.info(f"Successfully refreshed {len(products)} products")
        else:
            logger.warning("No products fetched, keeping existing cache")

    def find_product(self, sku: str, variant: str) -> Optional[Dict]:
        """Find product by SKU and variant"""
        product = self.products_by_sku.get(sku.upper())
        if not product:
            return None

        # Find matching variant
        for var in product.get('variants', []):
            variant_title = var.get('title', '').strip()
            # Match variant exactly
            if variant_title == variant or variant_title == str(variant):
                # Get product image (first image or variant featured image)
                images = product.get('images', [])
                image_url = images[0]['src'] if images else None

                # Check if variant has featured image
                variant_image_id = var.get('featured_image')
                if variant_image_id:
                    for img in images:
                        if img.get('id') == variant_image_id:
                            image_url = img['src']
                            break

                return {
                    'product_name': product.get('title'),
                    'sku': sku.upper(),
                    'variant': variant_title,
                    'image_url': image_url,
                    'price': var.get('price'),
                    'available': var.get('available', False),
                    'product_url': f"https://www.dennis-snkrs.com/products/{product.get('handle')}"
                }

        return None

    async def start_background_refresh(self):
        """Start background task to refresh cache every 24 hours"""
        while True:
            await self.refresh()
            # Wait 24 hours
            await asyncio.sleep(24 * 60 * 60)

# Global instance
product_cache = ProductCache()
