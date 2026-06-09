"""
Shopify Product Option Migration Script

Migrates products from metafield-linked Option 1 to a plain text Option named "Talla".

For products where Option 1 has linkedMetafield != null:
1. Creates new Option "Talla" (plain text, not linked to metafield)
2. Copies variant values from Option 1 to "Talla"
3. Deletes original Option 1

All variant data (price, sku, inventory, barcode, etc.) is preserved.

Usage:
    python scripts/variants-migrates/migrate.py           # Dry run (default)
    python scripts/variants-migrates/migrate.py --execute  # Actually perform migration
"""

import asyncio
import argparse
import json
import logging
import sys
import os
import time
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Add project root to path for logger_config import
sys.path.insert(0, str(PROJECT_ROOT))
from logger_config import setup_logger

SHOPIFY_ADMIN_TOKEN = os.getenv("SHOPIFY_ADMIN_TOKEN")
SHOPIFY_STORE_URL = os.getenv("SHOPIFY_STORE_URL")
GRAPHQL_ENDPOINT = f"https://{SHOPIFY_STORE_URL}/admin/api/2024-10/graphql.json"

logger = setup_logger("migrate")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class InventoryLevelSnapshot:
    """Snapshot of inventory at a specific location."""
    location_id: str
    location_name: str
    available: int


@dataclass
class VariantSnapshot:
    """Snapshot of a variant before migration."""
    id: str
    title: str
    price: str
    compare_at_price: Optional[str]
    sku: Optional[str]
    barcode: Optional[str]
    inventory_quantity: int
    inventory_policy: str  # DENY or CONTINUE
    taxable: bool
    inventory_tracked: bool
    option1_value: str
    inventory_levels: list[InventoryLevelSnapshot] = field(default_factory=list)


@dataclass
class ProductMigrationPlan:
    """Migration plan for a single product."""
    product_id: str
    product_title: str
    option1_id: str
    option1_name: str
    needs_rename: bool  # True when option1 is already named "Talla"
    unique_option_values: list[str]
    variants: list[VariantSnapshot]
    status: str = "pending"
    error: Optional[str] = None


@dataclass
class MigrationReport:
    """Overall migration report."""
    total_products_scanned: int = 0
    products_needing_migration: int = 0
    products_already_migrated: int = 0
    products_skipped: int = 0
    products_migrated_successfully: int = 0
    products_failed: int = 0
    errors: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Shopify GraphQL client
# ---------------------------------------------------------------------------

class ShopifyGraphQLClient:
    """Async client for Shopify GraphQL Admin API with rate limiting."""

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": SHOPIFY_ADMIN_TOKEN,
        }
        self._last_request_time = 0.0
        self._min_request_interval = 0.5

    async def _execute(self, query: str, variables: dict = None) -> dict:
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self._min_request_interval:
            await asyncio.sleep(self._min_request_interval - elapsed)

        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        async with self.session.post(
            GRAPHQL_ENDPOINT, headers=self.headers, json=payload
        ) as response:
            self._last_request_time = time.monotonic()

            if response.status == 429:
                retry_after = float(response.headers.get("Retry-After", "2.0"))
                logger.warning(f"Rate limited. Retrying after {retry_after}s...")
                await asyncio.sleep(retry_after)
                return await self._execute(query, variables)

            if response.status != 200:
                body = await response.text()
                raise Exception(f"HTTP {response.status}: {body}")

            data = await response.json()

            if "errors" in data:
                raise Exception(f"GraphQL errors: {json.dumps(data['errors'], indent=2)}")

            return data

    async def fetch_all_products(self) -> list[dict]:
        query = """
        query($cursor: String) {
          products(first: 250, after: $cursor) {
            edges {
              node {
                id
                title
                options {
                  id
                  name
                  position
                  linkedMetafield {
                    namespace
                    key
                  }
                  optionValues {
                    id
                    name
                  }
                }
                variants(first: 100) {
                  edges {
                    node {
                      id
                      title
                      price
                      compareAtPrice
                      sku
                      barcode
                      inventoryQuantity
                      inventoryPolicy
                      taxable
                      inventoryItem {
                        tracked
                      }
                      selectedOptions {
                        name
                        value
                      }
                    }
                  }
                }
              }
            }
            pageInfo {
              hasNextPage
              endCursor
            }
          }
        }
        """
        all_products = []
        cursor = None
        page = 0

        while True:
            page += 1
            variables = {"cursor": cursor} if cursor else {}
            data = await self._execute(query, variables)

            products_data = data["data"]["products"]
            edges = products_data["edges"]
            all_products.extend([edge["node"] for edge in edges])

            logger.info(f"Fetched page {page}: {len(edges)} products (total: {len(all_products)})")

            page_info = products_data["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            cursor = page_info["endCursor"]

        return all_products

    async def fetch_product_inventory(self, product_id: str) -> dict[str, list[dict]]:
        """Fetch per-location inventory for all variants of a product.
        Returns {variant_id: [{location_id, location_name, available}]}"""
        query = """
        query($id: ID!) {
          product(id: $id) {
            variants(first: 100) {
              edges {
                node {
                  id
                  inventoryItem {
                    inventoryLevels(first: 20) {
                      edges {
                        node {
                          location {
                            id
                            name
                          }
                          quantities(names: ["available"]) {
                            name
                            quantity
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """
        data = await self._execute(query, {"id": product_id})
        result = {}
        for edge in data["data"]["product"]["variants"]["edges"]:
            node = edge["node"]
            levels = []
            inv_item = node.get("inventoryItem") or {}
            for inv_edge in (inv_item.get("inventoryLevels") or {}).get("edges", []):
                inv_node = inv_edge["node"]
                loc = inv_node["location"]
                available = 0
                for qty in inv_node.get("quantities", []):
                    if qty["name"] == "available":
                        available = qty["quantity"]
                levels.append({
                    "location_id": loc["id"],
                    "location_name": loc["name"],
                    "available": available,
                })
            result[node["id"]] = levels
        return result

    async def create_option(self, product_id: str, option_name: str, values: list[str]) -> dict:
        mutation = """
        mutation productOptionsCreate($productId: ID!, $options: [OptionCreateInput!]!) {
          productOptionsCreate(productId: $productId, options: $options, variantStrategy: LEAVE_AS_IS) {
            product {
              id
              options {
                id
                name
                position
                linkedMetafield {
                  namespace
                  key
                }
                optionValues {
                  id
                  name
                }
              }
              variants(first: 100) {
                edges {
                  node {
                    id
                    title
                    selectedOptions {
                      name
                      value
                    }
                  }
                }
              }
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        variables = {
            "productId": product_id,
            "options": [{
                "name": option_name,
                "values": [{"name": v} for v in values],
            }],
        }
        data = await self._execute(mutation, variables)
        result = data["data"]["productOptionsCreate"]
        if result["userErrors"]:
            raise Exception(f"productOptionsCreate errors: {json.dumps(result['userErrors'])}")
        return result

    async def update_variant_options(self, product_id: str, variant_updates: list[dict]) -> dict:
        mutation = """
        mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
          productVariantsBulkUpdate(productId: $productId, variants: $variants) {
            productVariants {
              id
              title
              selectedOptions {
                name
                value
              }
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        variables = {
            "productId": product_id,
            "variants": variant_updates,
        }
        data = await self._execute(mutation, variables)
        result = data["data"]["productVariantsBulkUpdate"]
        if result["userErrors"]:
            raise Exception(f"productVariantsBulkUpdate errors: {json.dumps(result['userErrors'])}")
        return result

    async def rename_option(self, product_id: str, option_id: str, new_name: str) -> dict:
        mutation = """
        mutation productOptionUpdate($productId: ID!, $option: OptionUpdateInput!) {
          productOptionUpdate(productId: $productId, option: $option) {
            product {
              id
              options {
                id
                name
                position
              }
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        variables = {
            "productId": product_id,
            "option": {"id": option_id, "name": new_name},
        }
        data = await self._execute(mutation, variables)
        result = data["data"]["productOptionUpdate"]
        if result["userErrors"]:
            raise Exception(f"productOptionUpdate errors: {json.dumps(result['userErrors'])}")
        return result

    async def delete_option(self, product_id: str, option_id: str) -> dict:
        mutation = """
        mutation productOptionsDelete($productId: ID!, $options: [ID!]!) {
          productOptionsDelete(productId: $productId, options: $options, strategy: POSITION) {
            deletedOptionsIds
            product {
              id
              options {
                id
                name
                position
                linkedMetafield {
                  namespace
                  key
                }
              }
              variants(first: 100) {
                edges {
                  node {
                    id
                    title
                    price
                    compareAtPrice
                    sku
                    barcode
                    inventoryQuantity
                    selectedOptions {
                      name
                      value
                    }
                  }
                }
              }
            }
            userErrors {
              field
              message
              code
            }
          }
        }
        """
        variables = {
            "productId": product_id,
            "options": [option_id],
        }
        data = await self._execute(mutation, variables)
        result = data["data"]["productOptionsDelete"]
        if result["userErrors"]:
            raise Exception(f"productOptionsDelete errors: {json.dumps(result['userErrors'])}")
        return result

    async def fetch_product(self, product_id: str) -> dict:
        query = """
        query($id: ID!) {
          product(id: $id) {
            id
            title
            options {
              id
              name
              position
              linkedMetafield {
                namespace
                key
              }
              optionValues {
                id
                name
              }
            }
            variants(first: 100) {
              edges {
                node {
                  id
                  title
                  price
                  compareAtPrice
                  sku
                  barcode
                  inventoryQuantity
                  inventoryPolicy
                  taxable
                  inventoryItem {
                    tracked
                    inventoryLevels(first: 20) {
                      edges {
                        node {
                          location {
                            id
                            name
                          }
                          quantities(names: ["available"]) {
                            name
                            quantity
                          }
                        }
                      }
                    }
                  }
                  selectedOptions {
                    name
                    value
                  }
                }
              }
            }
          }
        }
        """
        data = await self._execute(query, {"id": product_id})
        return data["data"]["product"]


# ---------------------------------------------------------------------------
# Migration orchestrator
# ---------------------------------------------------------------------------

class ProductMigrator:
    """Orchestrates the migration of product options."""

    def __init__(self, client: ShopifyGraphQLClient, dry_run: bool = True):
        self.client = client
        self.dry_run = dry_run
        self.report = MigrationReport()

    def _analyze_product(self, product: dict) -> Optional[ProductMigrationPlan]:
        options = product.get("options", [])
        if not options:
            return None

        # Find Option at position 1
        option1 = None
        for opt in options:
            if opt["position"] == 1:
                option1 = opt
                break

        if not option1:
            return None

        # Check if Option 1 has linkedMetafield
        linked = option1.get("linkedMetafield")
        if not linked:
            return None

        # Check if a plain-text "Talla" option already exists (fully migrated product)
        for opt in options:
            if opt["name"].lower() == "talla" and not opt.get("linkedMetafield") and opt["id"] != option1["id"]:
                logger.warning(
                    f"Product '{product['title']}' ({product['id']}) already has plain 'Talla' option. Skipping."
                )
                self.report.products_already_migrated += 1
                return None

        # If option1 is already named "Talla" (linked), we need to rename it first
        needs_rename = option1["name"].lower() == "talla"

        # Build variant snapshots
        variants_data = product.get("variants", {}).get("edges", [])
        variants = []
        unique_values = []
        seen_values = set()

        for edge in variants_data:
            node = edge["node"]
            option1_value = None
            for sel_opt in node.get("selectedOptions", []):
                if sel_opt["name"] == option1["name"]:
                    option1_value = sel_opt["value"]
                    break

            if option1_value is None:
                logger.error(
                    f"Variant {node['id']} has no value for option '{option1['name']}'. Skipping variant."
                )
                continue

            inv_item = node.get("inventoryItem") or {}
            variants.append(VariantSnapshot(
                id=node["id"],
                title=node["title"],
                price=node["price"],
                compare_at_price=node.get("compareAtPrice"),
                sku=node.get("sku"),
                barcode=node.get("barcode"),
                inventory_quantity=node.get("inventoryQuantity", 0),
                inventory_policy=node.get("inventoryPolicy", "DENY"),
                taxable=node.get("taxable", True),
                inventory_tracked=inv_item.get("tracked", True),
                option1_value=option1_value,
            ))

            if option1_value not in seen_values:
                unique_values.append(option1_value)
                seen_values.add(option1_value)

        return ProductMigrationPlan(
            product_id=product["id"],
            product_title=product["title"],
            option1_id=option1["id"],
            option1_name=option1["name"],
            needs_rename=needs_rename,
            unique_option_values=unique_values,
            variants=variants,
        )

    async def _enrich_inventory(self, plan: ProductMigrationPlan):
        """Fetch and attach per-location inventory data to each variant in the plan."""
        inv_data = await self.client.fetch_product_inventory(plan.product_id)
        for variant in plan.variants:
            levels = inv_data.get(variant.id, [])
            variant.inventory_levels = [
                InventoryLevelSnapshot(
                    location_id=l["location_id"],
                    location_name=l["location_name"],
                    available=l["available"],
                ) for l in levels
            ]

    async def _migrate_product(self, plan: ProductMigrationPlan) -> bool:
        logger.info(f"--- Migrating: '{plan.product_title}' ({plan.product_id}) ---")
        logger.info(f"  Option 1: '{plan.option1_name}' (to be replaced)"
                   f"{' [NAME CONFLICT - will rename first]' if plan.needs_rename else ''}")
        logger.info(f"  Unique values: {plan.unique_option_values}")
        logger.info(f"  Variants: {len(plan.variants)}")

        # Fetch per-location inventory before any changes
        await self._enrich_inventory(plan)

        if self.dry_run:
            if plan.needs_rename:
                logger.info(f"    [DRY RUN] Will rename '{plan.option1_name}' -> 'Talla_legacy' first")
            for v in plan.variants:
                inv_info = ", ".join(
                    f"{il.location_name}={il.available}" for il in v.inventory_levels
                ) if v.inventory_levels else "no inventory data"
                logger.info(
                    f"    [DRY RUN] Variant {v.id}: '{v.title}' -> Talla='{v.option1_value}' "
                    f"(price={v.price}, compareAt={v.compare_at_price}, sku={v.sku}, "
                    f"barcode={v.barcode}, policy={v.inventory_policy}, "
                    f"taxable={v.taxable}, tracked={v.inventory_tracked}, "
                    f"inventory=[{inv_info}])"
                )
            return True

        # Track the working name for the old option (may change if renamed)
        old_option_working_name = plan.option1_name

        try:
            # Step 0 (conditional): Rename old option if it's already named "Talla"
            if plan.needs_rename:
                logger.info(f"  Step 0: Renaming '{plan.option1_name}' -> 'Talla_legacy'...")
                await self.client.rename_option(plan.product_id, plan.option1_id, "Talla_legacy")
                old_option_working_name = "Talla_legacy"
                logger.info(f"  Step 0: Done")

            # Step 1: Create Option "Talla"
            logger.info(f"  Step 1/4: Creating option 'Talla' with {len(plan.unique_option_values)} values...")
            await self.client.create_option(
                plan.product_id, "Talla", plan.unique_option_values
            )
            plan.status = "option_created"
            logger.info(f"  Step 1/4: Done")

            # Step 2: Update each variant's "Talla" value
            logger.info(f"  Step 2/4: Updating {len(plan.variants)} variants...")
            variant_updates = []
            for variant in plan.variants:
                variant_updates.append({
                    "id": variant.id,
                    "optionValues": [
                        {"optionName": old_option_working_name, "name": variant.option1_value},
                        {"optionName": "Talla", "name": variant.option1_value},
                    ],
                })

            batch_size = 100
            for i in range(0, len(variant_updates), batch_size):
                batch = variant_updates[i:i + batch_size]
                logger.info(f"    Updating batch {i // batch_size + 1} ({len(batch)} variants)...")
                await self.client.update_variant_options(plan.product_id, batch)

            plan.status = "variants_updated"
            logger.info(f"  Step 2/4: Done")

            # Step 3: Delete old option
            logger.info(f"  Step 3/4: Deleting option '{old_option_working_name}' ({plan.option1_id})...")
            delete_result = await self.client.delete_option(plan.product_id, plan.option1_id)
            plan.status = "option_deleted"
            deleted_ids = delete_result.get("deletedOptionsIds", [])
            logger.info(f"  Step 3/4: Done (deleted: {deleted_ids})")

            # Step 4: Verify
            logger.info(f"  Step 4/4: Verifying migration...")
            verified_product = await self.client.fetch_product(plan.product_id)
            if self._verify_migration(plan, verified_product):
                plan.status = "verified"
                logger.info(f"  Migration VERIFIED for '{plan.product_title}'")
                return True
            else:
                plan.status = "failed"
                plan.error = "Post-migration verification failed"
                logger.error(f"  Migration VERIFICATION FAILED for '{plan.product_title}'")
                return False

        except Exception as e:
            plan.status = "failed"
            plan.error = str(e)
            logger.error(f"  Migration FAILED for '{plan.product_title}': {e}")
            return False

    def _verify_migration(self, plan: ProductMigrationPlan, product: dict) -> bool:
        options = product.get("options", [])

        if len(options) != 1:
            logger.error(f"    Expected 1 option, got {len(options)}: {[o['name'] for o in options]}")
            return False

        if options[0]["name"] != "Talla":
            logger.error(f"    Option name is '{options[0]['name']}', expected 'Talla'")
            return False

        if options[0].get("linkedMetafield"):
            logger.error(f"    'Talla' option still has linkedMetafield")
            return False

        actual_variants = product.get("variants", {}).get("edges", [])
        if len(actual_variants) != len(plan.variants):
            logger.error(f"    Expected {len(plan.variants)} variants, got {len(actual_variants)}")
            return False

        actual_by_id = {e["node"]["id"]: e["node"] for e in actual_variants}
        for expected in plan.variants:
            actual = actual_by_id.get(expected.id)
            if not actual:
                logger.error(f"    Variant {expected.id} not found after migration")
                return False

            # Verify price
            if actual["price"] != expected.price:
                logger.error(f"    Variant {expected.id} price changed: '{expected.price}' -> '{actual['price']}'")
                return False

            # Verify compareAtPrice
            if actual.get("compareAtPrice") != expected.compare_at_price:
                logger.error(f"    Variant {expected.id} compareAtPrice changed: "
                           f"'{expected.compare_at_price}' -> '{actual.get('compareAtPrice')}'")
                return False

            # Verify SKU
            if actual.get("sku") != expected.sku:
                logger.error(f"    Variant {expected.id} SKU changed: '{expected.sku}' -> '{actual.get('sku')}'")
                return False

            # Verify barcode
            if actual.get("barcode") != expected.barcode:
                logger.error(f"    Variant {expected.id} barcode changed: "
                           f"'{expected.barcode}' -> '{actual.get('barcode')}'")
                return False

            # Verify inventoryPolicy (sell policy: DENY or CONTINUE)
            if actual.get("inventoryPolicy") != expected.inventory_policy:
                logger.error(f"    Variant {expected.id} inventoryPolicy changed: "
                           f"'{expected.inventory_policy}' -> '{actual.get('inventoryPolicy')}'")
                return False

            # Verify taxable
            if actual.get("taxable") != expected.taxable:
                logger.error(f"    Variant {expected.id} taxable changed: "
                           f"{expected.taxable} -> {actual.get('taxable')}")
                return False

            # Verify inventory tracked
            actual_inv_item = actual.get("inventoryItem") or {}
            if actual_inv_item.get("tracked") != expected.inventory_tracked:
                logger.error(f"    Variant {expected.id} inventory tracked changed: "
                           f"{expected.inventory_tracked} -> {actual_inv_item.get('tracked')}")
                return False

            talla_value = None
            for sel_opt in actual.get("selectedOptions", []):
                if sel_opt["name"] == "Talla":
                    talla_value = sel_opt["value"]
            if talla_value != expected.option1_value:
                logger.error(
                    f"    Variant {expected.id} Talla='{talla_value}', expected '{expected.option1_value}'"
                )
                return False

            # Verify per-location inventory
            if expected.inventory_levels:
                actual_inv_item = actual.get("inventoryItem") or {}
                actual_inv_edges = (actual_inv_item.get("inventoryLevels") or {}).get("edges", [])
                actual_inv_by_loc = {}
                for inv_edge in actual_inv_edges:
                    inv_node = inv_edge["node"]
                    loc_id = inv_node["location"]["id"]
                    for qty in inv_node.get("quantities", []):
                        if qty["name"] == "available":
                            actual_inv_by_loc[loc_id] = qty["quantity"]

                for exp_inv in expected.inventory_levels:
                    actual_qty = actual_inv_by_loc.get(exp_inv.location_id)
                    if actual_qty is None:
                        logger.warning(
                            f"    Variant {expected.id} location '{exp_inv.location_name}' "
                            f"not found after migration (was {exp_inv.available})"
                        )
                    elif actual_qty != exp_inv.available:
                        logger.error(
                            f"    Variant {expected.id} inventory at '{exp_inv.location_name}' "
                            f"changed: {exp_inv.available} -> {actual_qty}"
                        )
                        return False

        logger.info(f"    All {len(plan.variants)} variants verified (options + inventory)")
        return True

    async def run(self):
        mode = "DRY RUN" if self.dry_run else "EXECUTE"
        logger.info(f"{'=' * 60}")
        logger.info(f"  Shopify Option Migration - Mode: {mode}")
        logger.info(f"  Store: {SHOPIFY_STORE_URL}")
        logger.info(f"{'=' * 60}")

        if not self.dry_run:
            logger.warning("EXECUTE MODE: Changes will be made to your Shopify store!")
            logger.warning("Press Ctrl+C within 5 seconds to abort...")
            await asyncio.sleep(5)

        # Phase 1: Fetch all products
        logger.info("Phase 1: Fetching all products...")
        products = await self.client.fetch_all_products()
        self.report.total_products_scanned = len(products)
        logger.info(f"Fetched {len(products)} products total")

        # Phase 2: Analyze
        logger.info("Phase 2: Analyzing products...")
        migration_plans: list[ProductMigrationPlan] = []
        for product in products:
            plan = self._analyze_product(product)
            if plan:
                migration_plans.append(plan)
            else:
                self.report.products_skipped += 1

        self.report.products_needing_migration = len(migration_plans)
        logger.info(
            f"Analysis: {len(migration_plans)} need migration, "
            f"{self.report.products_skipped} skipped, "
            f"{self.report.products_already_migrated} already migrated"
        )

        if not migration_plans:
            logger.info("No products need migration. Done.")
            self._print_report()
            return self.report

        # Phase 3: Migrate
        logger.info(f"Phase 3: {'Simulating' if self.dry_run else 'Executing'} migrations...")
        for i, plan in enumerate(migration_plans, 1):
            logger.info(f"[{i}/{len(migration_plans)}] Processing '{plan.product_title}'...")
            success = await self._migrate_product(plan)
            if success:
                self.report.products_migrated_successfully += 1
            else:
                self.report.products_failed += 1
                self.report.errors.append({
                    "product_id": plan.product_id,
                    "product_title": plan.product_title,
                    "status": plan.status,
                    "error": plan.error,
                })

        self._print_report()
        return self.report

    def _print_report(self):
        r = self.report
        logger.info(f"\n{'=' * 60}")
        logger.info(f"  MIGRATION REPORT ({'DRY RUN' if self.dry_run else 'EXECUTED'})")
        logger.info(f"{'=' * 60}")
        logger.info(f"  Total products scanned:      {r.total_products_scanned}")
        logger.info(f"  Products needing migration:  {r.products_needing_migration}")
        logger.info(f"  Products skipped (no link):   {r.products_skipped}")
        logger.info(f"  Products already migrated:    {r.products_already_migrated}")
        logger.info(f"  Successfully migrated:        {r.products_migrated_successfully}")
        logger.info(f"  Failed:                       {r.products_failed}")
        if r.errors:
            logger.info("  ERRORS:")
            for err in r.errors:
                logger.error(f"    - {err['product_title']} ({err['product_id']}): "
                           f"status={err['status']}, error={err['error']}")
        logger.info(f"{'=' * 60}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(
        description="Migrate Shopify product options from metafield-linked to plain text 'Talla'"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Actually execute the migration (default is dry-run mode)",
    )
    args = parser.parse_args()

    if not SHOPIFY_ADMIN_TOKEN:
        logger.error("SHOPIFY_ADMIN_TOKEN not found in .env")
        sys.exit(1)
    if not SHOPIFY_STORE_URL:
        logger.error("SHOPIFY_STORE_URL not found in .env")
        sys.exit(1)

    dry_run = not args.execute

    async with aiohttp.ClientSession() as session:
        client = ShopifyGraphQLClient(session)
        migrator = ProductMigrator(client, dry_run=dry_run)
        await migrator.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nMigration interrupted by user")
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        sys.exit(1)
