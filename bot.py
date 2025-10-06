import discord
from discord import app_commands
import logging
import aiohttp
from config import DISCORD_BOT_TOKEN
from product_cache import product_cache

# Logger will be configured by main.py
logger = logging.getLogger(__name__)

class DiscordBot:
    def __init__(self):
        # Set up Discord bot with necessary intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.guild_reactions = True  # Enable reaction events

        self.client = discord.Client(intents=intents)
        self.tree = app_commands.CommandTree(self.client)
        self.token = DISCORD_BOT_TOKEN
        self.setup_slash_commands()
        self.setup_events()
        
    def setup_events(self):
        """Set up Discord client events"""
        @self.client.event
        async def on_ready():
            logger.info(f'Discord bot logged in as {self.client.user}')
            try:
                # Initialize product cache
                await product_cache.refresh()
                logger.info('Product cache initialized')

                synced = await self.tree.sync()
                logger.info(f'Synced {len(synced)} slash commands')

            except Exception as e:
                logger.error(f'Failed to sync slash commands: {e}')

        @self.client.event
        async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
            """Handle reaction events"""
            try:
                logger.info(f'Reaction detected: {payload.emoji} on message {payload.message_id} by user {payload.user_id}')

                # Check if reaction is white_check_mark (✅)
                if str(payload.emoji) != '✅':
                    logger.debug(f'Ignoring non-checkmark reaction: {payload.emoji}')
                    return

                # Get the message
                channel = self.client.get_channel(payload.channel_id)
                if not channel:
                    logger.warning(f'Channel {payload.channel_id} not found')
                    return

                message = await channel.fetch_message(payload.message_id)
                logger.info(f'Message author: {message.author.id}, Bot ID: {self.client.user.id}')
                logger.info(f'Message content: "{message.content[:100] if message.content else "No content"}"')

                # Check if message is from our bot and contains "Want to Buy" (case-insensitive)
                if message.author.id != self.client.user.id:
                    logger.debug(f'Message not from bot (author: {message.author.id})')
                    return

                if not message.content or "want to buy" not in message.content.lower():
                    logger.debug(f'Message does not contain "Want to Buy" (case-insensitive)')
                    return

                # Delete the message
                await message.delete()
                logger.info(f'✅ Deleted WTB message {payload.message_id} after ✅ reaction by user {payload.user_id}')

            except discord.NotFound:
                logger.warning(f'Message {payload.message_id} not found for deletion')
            except discord.Forbidden:
                logger.error(f'No permission to delete message {payload.message_id}')
            except Exception as e:
                logger.error(f'Error handling reaction: {e}', exc_info=True)
    
    def setup_slash_commands(self):
        """Set up slash commands"""
        @self.tree.command(name='wtb', description='Want to buy - Search for a product by SKU and size')
        @app_commands.describe(
            sku='Product SKU code (e.g., FZ8117-100)',
            variant='Size/variant (e.g., 43)'
        )
        async def wtb_command(interaction: discord.Interaction, sku: str, variant: str):
            await interaction.response.defer(ephemeral=True)

            try:
                # Check if user has Admin role or allowed role
                allowed_role_ids = [
                    1424509842491707392,  # Admin role
                    1338230016147980308   # Moderator
                ]
                user_role_ids = [role.id for role in interaction.user.roles]

                # Check if user has any of the allowed roles
                if not any(role_id in user_role_ids for role_id in allowed_role_ids):
                    await interaction.followup.send(
                        "❌ You don't have permission to use this command. Required role not found.",
                        ephemeral=True
                    )
                    logger.info(f'WTB command denied: User {interaction.user} does not have required role')
                    return

                # Check if cache is available
                if product_cache.is_refreshing and not product_cache.has_cache:
                    await interaction.followup.send(
                        "⏳ Product data is being refreshed, please try again in a moment...",
                        ephemeral=True
                    )
                    logger.info(f'WTB command blocked: Cache is refreshing and no data available yet')
                    return

                # Search for product
                product_info = product_cache.find_product(sku, variant)

                if not product_info:
                    await interaction.followup.send(
                        f"❌ Product not found for SKU: {sku} with variant: {variant}",
                        ephemeral=True
                    )
                    logger.info(f'WTB command: Product not found - SKU: {sku}, Variant: {variant}')
                    return

                # Send message to the current channel
                # Build content message with role mention, channel mention, and link
                content_message = (
                    "**WANT TO BUY**\n"
                    "<@&1344067083465654282> <#1344381116613660682>\n"
                    "https://www.wtbmarketlist.eu/list/355476796801679378"
                )

                # Create embed
                embed = discord.Embed(
                    description=f"**{product_info['product_name']}**\n**SKU:** {product_info['sku']}\n**Size:** {product_info['variant']}",
                    color=0x5865F2,  # Discord blurple color
                    timestamp=discord.utils.utcnow()
                )
                embed.set_footer(text="Dennis Snkrs Bot")

                if product_info['image_url']:
                    embed.set_image(url=product_info['image_url'])

                # Send message to the channel where command was used
                channel = interaction.channel
                await channel.send(content=content_message, embed=embed)

                # Confirm to user
                await interaction.followup.send(
                    f"✅ WTB request sent for {product_info['product_name']} - Size {product_info['variant']}",
                    ephemeral=True
                )
                logger.info(f'WTB command: Sent message in channel {interaction.channel_id} for {sku} - {variant} by {interaction.user}')

            except Exception as e:
                logger.error(f'Error in WTB command: {e}', exc_info=True)
                await interaction.followup.send(
                    f"❌ An error occurred: {str(e)}",
                    ephemeral=True
                )
        
    async def start(self):
        """Start the Discord bot"""
        try:
            logger.info("Starting Discord bot...")
            await self.client.start(self.token)
        except Exception as e:
            logger.error(f"Error starting bot: {e}")
            raise
    
    async def stop(self):
        """Stop the Discord bot"""
        try:
            await self.client.close()
            logger.info("Discord bot stopped")
        except Exception as e:
            logger.error(f"Error stopping bot: {e}")

# Global instance
discord_bot = DiscordBot()