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
        self.is_refreshing: bool = False
        self.has_cache: bool = False

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
        """Fetch all products from dennis-snkrs.com with pagination"""
        all_products = []
        page = 1
        page_size = 250

        try:
            async with aiohttp.ClientSession() as session:
                while True:
                    url = f"https://www.dennis-snkrs.com/products.json?page={page}&size={page_size}"
                    logger.info(f"Fetching page {page} (size={page_size})...")

                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            products = data.get('products', [])

                            if not products:
                                # Empty page means we've reached the end
                                logger.info(f"Reached end of products at page {page}")
                                break

                            all_products.extend(products)
                            logger.info(f"Fetched {len(products)} products from page {page} (total: {len(all_products)})")

                            # Move to next page
                            page += 1
                        else:
                            logger.error(f"Failed to fetch products page {page}: HTTP {response.status}")
                            break

                logger.info(f"Successfully fetched {len(all_products)} total products")
                return all_products

        except Exception as e:
            logger.error(f"Error fetching products: {e}")
            return all_products if all_products else []

    def _build_sku_index(self, products: List[dict]):
        """Build SKU-based index from products"""
        self.products_by_sku = {}
        for product in products:
            # Check if product already has SKU (new format)
            sku = product.get('sku')
            if not sku:
                # Extract from body_html (old format or raw API data)
                sku = self._extract_sku_from_html(product.get('body_html', ''))

            if sku:
                # Store product with all its variants
                self.products_by_sku[sku] = product
                logger.debug(f"Indexed product: {product.get('title')} with SKU: {sku}")

        # Mark that we have cache available
        if self.products_by_sku:
            self.has_cache = True
            logger.info(f"Indexed {len(self.products_by_sku)} products by SKU")

    def _save_cache(self, products: List[dict]):
        """Save products to cache file in SKU-indexed format"""
        try:
            # Build SKU-indexed structure for easier reading
            products_by_sku = {}
            products_without_sku = []

            for product in products:
                sku = self._extract_sku_from_html(product.get('body_html', ''))
                if sku:
                    products_by_sku[sku] = {
                        'sku': sku,
                        'title': product.get('title'),
                        'handle': product.get('handle'),
                        'vendor': product.get('vendor'),
                        'tags': product.get('tags', []),
                        'variants': product.get('variants', []),
                        'images': product.get('images', []),
                        'product_url': f"https://www.dennis-snkrs.com/products/{product.get('handle')}"
                    }
                else:
                    products_without_sku.append({
                        'title': product.get('title'),
                        'handle': product.get('handle')
                    })

            cache_data = {
                'last_update': datetime.now().isoformat(),
                'total_products': len(products),
                'products_with_sku': len(products_by_sku),
                'products': products_by_sku,
                'products_without_sku': products_without_sku
            }

            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)

            logger.info(f"Saved {len(products_by_sku)} products (with SKU) + {len(products_without_sku)} (without SKU) to cache")
        except Exception as e:
            logger.error(f"Error saving cache: {e}")

    def _load_cache(self) -> Optional[List[dict]]:
        """Load products from cache file (supports old and new format)"""
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
                    products_data = cache_data.get('products', [])

                    # Check if new format (dict) or old format (list)
                    if isinstance(products_data, dict):
                        # New format: already SKU-indexed, convert to list for _build_sku_index
                        products = list(products_data.values())
                        logger.info(f"Loaded {len(products)} products from cache (new format)")
                    else:
                        # Old format: list of products
                        products = products_data
                        logger.info(f"Loaded {len(products)} products from cache (old format)")

                    return products
                else:
                    logger.info("Cache expired, will fetch new data")
            return None
        except Exception as e:
            logger.error(f"Error loading cache: {e}")
            return None

    async def refresh(self, force: bool = False):
        """Refresh product cache"""
        # Set refreshing flag
        self.is_refreshing = True

        try:
            # Try to load from cache first
            if not force:
                cached_products = self._load_cache()
                if cached_products:
                    self._build_sku_index(cached_products)
                    logger.info("Using existing cache")
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
        finally:
            # Clear refreshing flag
            self.is_refreshing = False

    def find_product(self, sku: str, variant: str) -> Optional[Dict]:
        """Find product by SKU and variant (case-insensitive)"""
        # Case-insensitive SKU lookup
        product = self.products_by_sku.get(sku.upper())
        if not product:
            return None

        # Find matching variant (case-insensitive)
        variant_lower = str(variant).lower().strip()
        for var in product.get('variants', []):
            variant_title = var.get('title', '').strip()
            # Match variant case-insensitively
            if variant_title.lower() == variant_lower:
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
                    'variant': variant_title,  # Return original case from database
                    'image_url': image_url,
                    'price': var.get('price'),
                    'available': var.get('available', False),
                    'product_url': f"https://www.dennis-snkrs.com/products/{product.get('handle')}"
                }

        return None

    async def start_background_refresh(self):
        """Start background task to refresh cache every 24 hours"""
        while True:
            # Wait 24 hours before refreshing
            await asyncio.sleep(24 * 60 * 60)
            logger.info("24h cache refresh triggered")
            # Force refresh after 24h
            await self.refresh(force=True)

    def get_status(self) -> Dict[str, any]:
        """Get current cache status"""
        return {
            'is_refreshing': self.is_refreshing,
            'has_cache': self.has_cache,
            'products_count': len(self.products_by_sku),
            'last_update': self.last_update.isoformat() if self.last_update else None
        }

# Global instance
product_cache = ProductCache()
