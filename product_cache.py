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
        self.cache_duration = timedelta(hours=1)
        # One SKU can map to multiple products (e.g. same model, different colorways
        # that share/duplicate a SKU). Store a list to avoid silently overwriting.
        self.products_by_sku: Dict[str, List[dict]] = {}
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

    def _collect_skus(self, product: dict) -> List[str]:
        """Collect all SKUs for a product, normalized to uppercase.

        Primary source is the real Shopify variant SKU (variant['sku']); this is
        authoritative and matches what users see in the Shopify admin. The SKU
        scraped from body_html is unreliable (hand-entered, often stale/wrong) and
        is only used as a fallback when no variant carries a SKU.
        """
        skus = set()
        for var in product.get('variants', []):
            vsku = (var.get('sku') or '').strip()
            if vsku:
                skus.add(vsku.upper())

        # Product-level sku (cache "new format") also counts as authoritative.
        psku = (product.get('sku') or '').strip()
        if psku:
            skus.add(psku.upper())

        # Fallback only when no real SKU exists anywhere on the product.
        if not skus:
            html_sku = self._extract_sku_from_html(product.get('body_html', ''))
            if html_sku:
                skus.add(html_sku.strip().upper())

        return list(skus)

    def _build_sku_index(self, products: List[dict]):
        """Build SKU-based index from products (one SKU -> list of products)"""
        self.products_by_sku = {}
        for product in products:
            for sku in self._collect_skus(product):
                self.products_by_sku.setdefault(sku, [])
                # Avoid indexing the exact same product object twice under one SKU.
                if product not in self.products_by_sku[sku]:
                    self.products_by_sku[sku].append(product)
                logger.debug(f"Indexed product: {product.get('title')} with SKU: {sku}")

        # Mark that we have cache available
        if self.products_by_sku:
            self.has_cache = True
            collisions = sum(1 for v in self.products_by_sku.values() if len(v) > 1)
            logger.info(f"Indexed {len(self.products_by_sku)} SKUs ({collisions} shared by multiple products)")

    def _save_cache(self, products: List[dict]):
        """Save products to cache file in SKU-indexed format"""
        try:
            # Build SKU-indexed structure for easier reading.
            # Value is a list because one SKU may map to multiple products.
            products_by_sku = {}
            products_without_sku = []

            for product in products:
                skus = self._collect_skus(product)
                if skus:
                    entry = {
                        'sku': skus[0],
                        'all_skus': skus,
                        'title': product.get('title'),
                        'handle': product.get('handle'),
                        'vendor': product.get('vendor'),
                        'tags': product.get('tags', []),
                        'variants': product.get('variants', []),
                        'images': product.get('images', []),
                        'product_url': f"https://www.dennis-snkrs.com/products/{product.get('handle')}"
                    }
                    for sku in skus:
                        products_by_sku.setdefault(sku, []).append(entry)
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

                    # Check format and flatten to a unique list of product dicts
                    # for _build_sku_index (which re-derives SKUs itself).
                    if isinstance(products_data, dict):
                        # New format: SKU-indexed. Values may be a single product
                        # (legacy) or a list of products (current).
                        products = []
                        seen = set()
                        for value in products_data.values():
                            entries = value if isinstance(value, list) else [value]
                            for entry in entries:
                                handle = entry.get('handle')
                                key = handle or id(entry)
                                if key not in seen:
                                    seen.add(key)
                                    products.append(entry)
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

    def _lookup_sku(self, sku: str):
        """Resolve an input SKU to (products, matched_sku, ambiguous_candidates).

        Matching strategy:
          1. Exact match (preferred — avoids the false positives that bidirectional
             substring matching used to cause).
          2. Partial match only as a fallback, and only where the cached SKU
             *contains* the input (input is a prefix/substring of a real SKU);
             we no longer match when the cached SKU is a substring of the input.

        Returns:
          (products, matched_sku, candidates)
          - products: list of product dicts under the matched SKU (may be >1)
          - matched_sku: the cache key that matched, or None
          - candidates: list of {title, handle, sku} when the SKU maps to multiple
                        distinct products (ambiguous); empty otherwise.
        """
        sku_upper = sku.upper().strip()
        matched_sku = None
        products = None

        if sku_upper in self.products_by_sku:
            matched_sku = sku_upper
            products = self.products_by_sku[sku_upper]
        else:
            for cached_sku, cached_products in self.products_by_sku.items():
                if sku_upper and sku_upper in cached_sku:
                    matched_sku = cached_sku
                    products = cached_products
                    logger.info(f"Partial SKU match: input '{sku_upper}' matched with '{cached_sku}'")
                    break

        if not products:
            return None, None, []

        candidates = []
        if len(products) > 1:
            candidates = [
                {
                    'title': p.get('title'),
                    'handle': p.get('handle'),
                    'sku': matched_sku,
                }
                for p in products
            ]

        return products, matched_sku, candidates

    def find_product(self, sku: str, variant: str) -> Optional[Dict]:
        """Find product by SKU and variant (case-insensitive, exact-first SKU match)"""
        products, matched_sku, candidates = self._lookup_sku(sku)

        if not products:
            return None

        if candidates:
            return {'ambiguous': True, 'sku': matched_sku, 'candidates': candidates}

        product = products[0]

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
                    'sku': matched_sku,  # Return the matched SKU from cache
                    'variant': variant_title,  # Return original case from database
                    'image_url': image_url,
                    'price': var.get('price'),
                    'available': var.get('available', False),
                    'product_url': f"https://www.dennis-snkrs.com/products/{product.get('handle')}"
                }

        return None

    def find_product_all_sizes(self, sku: str) -> Optional[Dict]:
        """Find product by SKU only, without checking variant existence

        Used for "all sizes" requests where we don't validate specific variants.
        Returns product info with image using same logic as variant search.
        """
        products, matched_sku, candidates = self._lookup_sku(sku)

        if not products:
            return None

        if candidates:
            return {'ambiguous': True, 'sku': matched_sku, 'candidates': candidates}

        product = products[0]

        # Get product image (first image)
        images = product.get('images', [])
        image_url = images[0]['src'] if images else None

        return {
            'product_name': product.get('title'),
            'sku': matched_sku,
            'image_url': image_url,
            'product_url': f"https://www.dennis-snkrs.com/products/{product.get('handle')}"
        }

    def find_product_with_variants(self, sku: str, variants: List[str]) -> Optional[Dict]:
        """Find product by SKU and multiple variants (case-insensitive)

        Returns product info with all requested variants, or None if any variant is invalid.
        """
        products, matched_sku, candidates = self._lookup_sku(sku)

        if not products:
            return None

        if candidates:
            return {'ambiguous': True, 'sku': matched_sku, 'candidates': candidates}

        product = products[0]

        # Validate all variants exist (case-insensitive)
        product_variants = product.get('variants', [])
        variant_titles_lower = {var.get('title', '').strip().lower(): var.get('title', '').strip()
                                for var in product_variants}

        matched_variants = []
        invalid_variants = []

        for variant_input in variants:
            variant_lower = variant_input.lower().strip()
            if variant_lower in variant_titles_lower:
                # Store the original case from database
                matched_variants.append(variant_titles_lower[variant_lower])
            else:
                invalid_variants.append(variant_input)

        # If any variant is invalid, return error info
        if invalid_variants:
            return {
                'error': True,
                'invalid_variants': invalid_variants,
                'sku': matched_sku
            }

        # Get image from first variant
        first_variant_lower = variants[0].lower().strip()
        image_url = None

        images = product.get('images', [])
        if images:
            image_url = images[0]['src']

        # Check if first variant has featured image
        for var in product_variants:
            if var.get('title', '').strip().lower() == first_variant_lower:
                variant_image_id = var.get('featured_image')
                if variant_image_id:
                    for img in images:
                        if img.get('id') == variant_image_id:
                            image_url = img['src']
                            break
                break

        return {
            'product_name': product.get('title'),
            'sku': matched_sku,
            'variants': matched_variants,  # List of matched variants with original case
            'image_url': image_url,
            'product_url': f"https://www.dennis-snkrs.com/products/{product.get('handle')}"
        }

    async def start_background_refresh(self):
        """Start background task to refresh cache every 1 hour"""
        while True:
            # Wait 1 hour before refreshing
            await asyncio.sleep(1 * 60 * 60)
            logger.info("1h cache refresh triggered")
            # Force refresh after 1h
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
