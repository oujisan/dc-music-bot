# cogs/music.py
import discord
from discord.ext import commands
import yt_dlp
import asyncio
import time
import random
from config import YTDL_SEARCH_OPTIONS, YTDL_STREAM_OPTIONS, FFMPEG_OPTIONS

ytdl_search = yt_dlp.YoutubeDL(YTDL_SEARCH_OPTIONS)
ytdl_stream = yt_dlp.YoutubeDL(YTDL_STREAM_OPTIONS)

class MusicPlayerView(discord.ui.View):
    def __init__(self, cog, guild_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        state = self.cog.get_state(self.guild_id)
        if state['session_owner'] and state['session_owner'] != interaction.user.id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Only the person who requested the first track (or an Admin) can control this.", ephemeral=True)
            return False
        return True

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary, custom_id="music_resume")
    async def resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        state = self.cog.get_state(self.guild_id)
        if vc and vc.is_paused():
            vc.resume()
            if state['paused_time'] > 0:
                state['total_paused_duration'] += time.time() - state['paused_time']
                state['paused_time'] = 0
            await interaction.response.send_message("Resumed", ephemeral=True, delete_after=2)
        elif vc and vc.is_playing():
            await interaction.response.send_message("Already playing.", ephemeral=True, delete_after=2)
        else:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True, delete_after=2)

    @discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.secondary, custom_id="music_pause")
    async def pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        state = self.cog.get_state(self.guild_id)
        if vc and vc.is_playing():
            vc.pause()
            state['paused_time'] = time.time()
            await interaction.response.send_message("Paused", ephemeral=True, delete_after=2)
        else:
            await interaction.response.send_message("Not playing.", ephemeral=True, delete_after=2)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.primary, custom_id="music_skip")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await interaction.response.send_message("Skipped", ephemeral=True, delete_after=2)
        else:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True, delete_after=2)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.success, custom_id="music_shuffle")
    async def shuffle_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.cog.get_state(self.guild_id)
        if len(state['queue']) > 1:
            random.shuffle(state['queue'])
            await interaction.response.send_message("Queue shuffled", ephemeral=True, delete_after=2)
        else:
            await interaction.response.send_message("Not enough tracks to shuffle.", ephemeral=True, delete_after=2)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="music_stop")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        state = self.cog.get_state(self.guild_id)
        state['queue'].clear()
        if vc and vc.is_playing():
            vc.stop()
        await interaction.response.send_message("Stopped playback and cleared the queue.", ephemeral=True, delete_after=3)


class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild_states = {}
        self.disconnect_tasks = {}

    def get_state(self, guild_id):
        if guild_id not in self.guild_states:
            self.guild_states[guild_id] = {
                'queue': [],
                'current_track': None,
                'stream_url': None,
                'start_time': 0,
                'paused_time': 0,
                'total_paused_duration': 0,
                'current_seek': 0,
                'is_seeking': False,
                'volume': 1.0,
                'now_playing_message': None,
                'bound_channel': None,
                'session_owner': None
            }
        return self.guild_states[guild_id]

    def is_dj(self, member: discord.Member, state: dict) -> bool:
        if state['session_owner'] and state['session_owner'] != member.id and not member.guild_permissions.administrator:
            return False
        return True

    def get_elapsed(self, state):
        if state['start_time'] == 0:
            return 0
        if state['paused_time'] > 0:
            return state['paused_time'] - state['start_time'] - state['total_paused_duration'] + state['current_seek']
        return time.time() - state['start_time'] - state['total_paused_duration'] + state['current_seek']

    def parse_time(self, time_str: str) -> int:
        if ':' in time_str:
            parts = time_str.split(':')
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        return int(time_str)

    def format_time(self, seconds: int) -> str:
        mins, secs = divmod(int(seconds), 60)
        hrs, mins = divmod(mins, 60)
        if hrs > 0:
            return f"{hrs:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    def create_progress_bar(self, elapsed, duration, length=15):
        if not duration or duration == 0:
            return "▶︎ 🔘" + "▬" * (length - 1)
        
        progress = elapsed / duration
        if progress > 1.0:
            progress = 1.0
            
        pos = int(progress * length)
        if pos >= length:
            pos = length - 1
            
        bar = ""
        for i in range(length):
            if i == pos:
                bar += "🔘"
            else:
                bar += "▬"
                
        return f"▶︎ {bar}"

    async def inactivity_timeout(self, guild_id, vc):
        await asyncio.get_event_loop().create_task(asyncio.sleep(60))
        if vc and not vc.is_playing():
            await vc.disconnect()
            state = self.guild_states.get(guild_id)
            if state and state['bound_channel']:
                await state['bound_channel'].send("Disconnected from the voice channel due to 1 minute of inactivity.")
            self.guild_states.pop(guild_id, None)
        self.disconnect_tasks.pop(guild_id, None)

    def cancel_timeout(self, guild_id):
        if guild_id in self.disconnect_tasks:
            self.disconnect_tasks[guild_id].cancel()
            self.disconnect_tasks.pop(guild_id, None)

    async def prefetch_next(self, guild_id):
        state = self.get_state(guild_id)
        if len(state['queue']) > 0:
            next_item = state['queue'][0]
            if 'prefetched_data' not in next_item:
                next_item['prefetched_data'] = "loading"
                try:
                    data = await self.bot.loop.run_in_executor(
                        None, lambda: ytdl_stream.extract_info(next_item['webpage_url'], download=False)
                    )
                    if len(state['queue']) > 0 and state['queue'][0] == next_item:
                        next_item['prefetched_data'] = data
                except Exception:
                    next_item.pop('prefetched_data', None)

    async def play_next_callback(self, guild_id, channel):
        state = self.get_state(guild_id)
        if state['is_seeking']:
            state['is_seeking'] = False
            await self.play_current_seek(guild_id, channel)
        else:
            await self.play_next(guild_id, channel)

    async def play_next(self, guild_id, channel):
        state = self.get_state(guild_id)
        queue = state['queue']
        vc = self.bot.get_guild(guild_id).voice_client
        
        if len(queue) > 0:
            self.cancel_timeout(guild_id)
            item = queue.pop(0)
            state['current_track'] = item
            
            try:
                if 'prefetched_data' in item and item['prefetched_data'] != "loading":
                    data = item['prefetched_data']
                else:
                    data = await self.bot.loop.run_in_executor(
                        None, lambda: ytdl_stream.extract_info(item['webpage_url'], download=False)
                    )
                state['stream_url'] = data['url']
                
                source = discord.FFmpegPCMAudio(state['stream_url'], **FFMPEG_OPTIONS)
                source = discord.PCMVolumeTransformer(source, volume=state['volume'])
                
                def after_playing(e):
                    asyncio.run_coroutine_threadsafe(self.play_next_callback(guild_id, channel), self.bot.loop)

                state['start_time'] = time.time()
                state['paused_time'] = 0
                state['total_paused_duration'] = 0
                state['current_seek'] = 0
                state['is_seeking'] = False

                vc.play(source, after=after_playing)
                
                # Pre-fetch the next item so there is no delay when this track finishes
                asyncio.create_task(self.prefetch_next(guild_id))
                
                title = data.get('title', item['title'])
                url = data.get('webpage_url', item['webpage_url'])
                thumbnail = data.get('thumbnail')
                uploader = data.get('uploader', 'Unknown Artist')
                duration = data.get('duration')
                view_count = data.get('view_count')
                like_count = data.get('like_count')
                
                # Update current_track with full details for later use
                state['current_track'] = {
                    'webpage_url': url,
                    'title': title,
                    'thumbnail': thumbnail,
                    'uploader': uploader,
                    'duration': duration,
                    'view_count': view_count,
                    'like_count': like_count
                }
                
                duration_str = self.format_time(duration) if duration else "Live/Unknown"
                progress_bar = self.create_progress_bar(0, duration)
                
                embed = discord.Embed(title="🎵 Now Playing", description=f"[{title}]({url})\n\n`{progress_bar}`", color=discord.Color.from_rgb(255, 105, 180))
                if thumbnail:
                    embed.set_thumbnail(url=thumbnail)
                embed.add_field(name="Channel", value=uploader, inline=True)
                embed.add_field(name="Duration", value=duration_str, inline=True)
                
                if view_count:
                    embed.add_field(name="👁️ Views", value=f"{view_count:,}", inline=True)
                if like_count:
                    embed.add_field(name="👍 Likes", value=f"{like_count:,}", inline=True)
                
                embed.set_footer(text="Youtube Music Bot", icon_url=self.bot.user.display_avatar.url if self.bot.user.display_avatar else None)
                
                view = MusicPlayerView(self, guild_id)
                
                if state['now_playing_message']:
                    try:
                        await state['now_playing_message'].edit(embed=embed, view=view)
                    except discord.NotFound:
                        state['now_playing_message'] = await channel.send(embed=embed, view=view)
                else:
                    state['now_playing_message'] = await channel.send(embed=embed, view=view)
                
            except Exception as e:
                await channel.send(f"Failed to play **{item['title']}**: Skipping...")
                await self.play_next(guild_id, channel)
        else:
            state['current_track'] = None
            state['stream_url'] = None
            if state['now_playing_message']:
                try:
                    embed = discord.Embed(title="Queue Finished", description="Waiting for more tracks...", color=discord.Color.orange())
                    await state['now_playing_message'].edit(embed=embed, view=None)
                except discord.NotFound:
                    pass
            if guild_id not in self.disconnect_tasks:
                self.disconnect_tasks[guild_id] = self.bot.loop.create_task(self.inactivity_timeout(guild_id, vc))

    async def play_current_seek(self, guild_id, channel):
        state = self.get_state(guild_id)
        target_seconds = state['current_seek']
        vc = self.bot.get_guild(guild_id).voice_client
        
        custom_before = f"{FFMPEG_OPTIONS['before_options']} -ss {target_seconds}"
        source = discord.FFmpegPCMAudio(state['stream_url'], before_options=custom_before, options=FFMPEG_OPTIONS['options'])
        source = discord.PCMVolumeTransformer(source, volume=state['volume'])
        
        def after_playing(e):
            asyncio.run_coroutine_threadsafe(self.play_next_callback(guild_id, channel), self.bot.loop)
            
        state['start_time'] = time.time()
        state['paused_time'] = 0
        state['total_paused_duration'] = 0
        
        vc.play(source, after=after_playing)
        await channel.send(f"Seeked to **{self.format_time(target_seconds)}**", delete_after=5)

    async def execute_seek_signal(self, guild_id, channel, target_seconds):
        state = self.get_state(guild_id)
        vc = self.bot.get_guild(guild_id).voice_client
        if not vc or not state['current_track']:
            return await channel.send("No track is currently playing.", delete_after=5)
        
        if target_seconds < 0:
            target_seconds = 0
            
        state['is_seeking'] = True
        state['current_seek'] = target_seconds
        
        vc.stop()

    @commands.command(name="play", help="Plays a track or playlist from YouTube")
    async def play(self, ctx: commands.Context, *, search: str):
        if not ctx.author.voice:
            return await ctx.send("Connection rejected: You must be in a Voice Channel.")
        
        state = self.get_state(ctx.guild.id)
        vc = ctx.guild.voice_client
        if not vc:
            await ctx.author.voice.channel.connect()
            vc = ctx.guild.voice_client
            state['session_owner'] = ctx.author.id

        state['bound_channel'] = ctx.channel

        try:
            if "http" in search:
                query = search
            else:
                query = f"ytsearch:{search}"

            data = await self.bot.loop.run_in_executor(
                None, lambda: ytdl_search.extract_info(query, download=False)
            )
            
            if 'entries' in data:
                entries = [entry for entry in list(data['entries']) if entry]
                if not entries:
                    return await ctx.send("No results found.")
                if "ytsearch:" in query:
                    entries = [entries[0]]
                
                for entry in entries:
                    webpage_url = entry.get('url') or entry.get('webpage_url')
                    state['queue'].append({'webpage_url': webpage_url, 'title': entry.get('title')})
                if len(entries) > 1:
                    await ctx.send(f"Indexed {len(entries)} tracks into the queue.")
                else:
                    await ctx.send(f"Indexed **{entries[0].get('title')}** into the queue.")
            else:
                webpage_url = data.get('webpage_url') or data.get('original_url')
                state['queue'].append({'webpage_url': webpage_url, 'title': data.get('title')})
                await ctx.send(f"Indexed **{data.get('title')}** into the queue.")

            self.cancel_timeout(ctx.guild.id)

            if not vc.is_playing() and not vc.is_paused():
                await self.play_next(ctx.guild.id, ctx.channel)
            else:
                asyncio.create_task(self.prefetch_next(ctx.guild.id))

        except Exception as e:
            await ctx.send(f"Indexing failure: {str(e)}")

    @commands.command(name="pause", help="Pauses current playback")
    async def pause(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
        vc = ctx.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            state['paused_time'] = time.time()
            await ctx.send("Audio playback paused.")
        else:
            await ctx.send("Not playing.")

    @commands.command(name="resume", help="Resumes paused playback")
    async def resume(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
        vc = ctx.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            if state['paused_time'] > 0:
                state['total_paused_duration'] += time.time() - state['paused_time']
                state['paused_time'] = 0
            await ctx.send("Audio playback resumed.")
        else:
            await ctx.send("Not paused.")

    @commands.command(name="skip", help="Skips the current track")
    async def skip(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
        vc = ctx.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await ctx.send("Track skipped.")
        else:
            await ctx.send("Not playing.")

    @commands.command(name="forward", help="Skips audio forward")
    async def forward(self, ctx: commands.Context, seconds: int = 5):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
        current_elapsed = self.get_elapsed(state)
        await ctx.send(f"Forwarding {seconds} seconds...")
        await self.execute_seek_signal(ctx.guild.id, ctx.channel, current_elapsed + seconds)

    @commands.command(name="back", help="Skips audio backward")
    async def back(self, ctx: commands.Context, seconds: int = 5):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
        current_elapsed = self.get_elapsed(state)
        await ctx.send(f"Going back {seconds} seconds...")
        await self.execute_seek_signal(ctx.guild.id, ctx.channel, current_elapsed - seconds)

    @commands.command(name="seek", help="Jumps to a specific timestamp (e.g., 90 or 01:30)")
    async def seek(self, ctx: commands.Context, time_input: str):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
        try:
            target_seconds = self.parse_time(time_input)
            await ctx.send(f"Seeking to {time_input}...")
            await self.execute_seek_signal(ctx.guild.id, ctx.channel, target_seconds)
        except ValueError:
            await ctx.send("Wrong time format. Use second number (e.g. `90`) or format `MM:SS` (e.g. `02:30`).")

    @commands.command(name="drop", help="Removes a track from the queue")
    async def drop(self, ctx: commands.Context, index: int):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
        queue = state['queue']
        target_index = index - 1
        
        if 0 <= target_index < len(queue):
            removed = queue.pop(target_index)
            await ctx.send(f"Dropped **{removed['title']}** from the queue.")
            vc = ctx.guild.voice_client
            if len(queue) == 0 and vc and not vc.is_playing():
                if ctx.guild.id not in self.disconnect_tasks:
                    self.disconnect_tasks[ctx.guild.id] = self.bot.loop.create_task(self.inactivity_timeout(ctx.guild.id, vc))
        else:
            await ctx.send("Invalid index. Use `!queue` to verify track positions.")

    @commands.command(name="volume", help="Sets the playback volume (1-100)")
    async def volume(self, ctx: commands.Context, level: int):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
        if level < 1 or level > 100:
            return await ctx.send("Volume must be between 1 and 100.")
        
        state = self.get_state(ctx.guild.id)
        state['volume'] = level / 100.0
        
        vc = ctx.guild.voice_client
        if vc and vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = state['volume']
            
        await ctx.send(f"Volume set to {level}%")

    @commands.command(name="shuffle", help="Shuffles the current queue")
    async def shuffle(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
        if len(state['queue']) > 1:
            random.shuffle(state['queue'])
            await ctx.send("Queue shuffled.")
        else:
            await ctx.send("Not enough tracks to shuffle.")

    @commands.command(name="move", help="Moves a track to a different position in the queue")
    async def move(self, ctx: commands.Context, from_index: int, to_index: int):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
        queue = state['queue']
        if not (1 <= from_index <= len(queue)) or not (1 <= to_index <= len(queue)):
            return await ctx.send("Invalid index.")
            
        item = queue.pop(from_index - 1)
        queue.insert(to_index - 1, item)
        await ctx.send(f"Moved **{item['title']}** to position {to_index}.")

    @commands.command(name="player", aliases=["np", "nowplaying"], help="Displays the currently playing track")
    async def player(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if not state['current_track']:
            return await ctx.send("Nothing is currently playing.")
        
        track = state['current_track']
        title = track.get('title', 'Unknown')
        url = track.get('webpage_url', '')
        thumbnail = track.get('thumbnail')
        uploader = track.get('uploader', 'Unknown Artist')
        duration = track.get('duration')
        view_count = track.get('view_count')
        like_count = track.get('like_count')
        
        duration_str = self.format_time(duration) if duration else "Live/Unknown"
        elapsed_secs = self.get_elapsed(state)
        elapsed_str = self.format_time(elapsed_secs)
        
        progress_bar = self.create_progress_bar(elapsed_secs, duration)
        
        embed = discord.Embed(title="🎵 Now Playing", description=f"[{title}]({url})\n\n`{progress_bar}`", color=discord.Color.from_rgb(255, 105, 180))
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        
        embed.add_field(name="Channel", value=uploader, inline=True)
        embed.add_field(name="Progress", value=f"{elapsed_str} / {duration_str}", inline=True)
        
        if view_count:
            embed.add_field(name="👁️ Views", value=f"{view_count:,}", inline=True)
        if like_count:
            embed.add_field(name="👍 Likes", value=f"{like_count:,}", inline=True)
            
        embed.set_footer(text="Youtube Music Bot", icon_url=self.bot.user.display_avatar.url if self.bot.user.display_avatar else None)
        
        view = MusicPlayerView(self, ctx.guild.id)
        await ctx.send(embed=embed, view=view)

    @commands.command(name="queue", help="Displays the current queue")
    async def queue(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        queue = state['queue']
        if not queue and not state['current_track']:
            return await ctx.send("The queue is currently empty.")
        
        embed = discord.Embed(title="📜 Music Queue", color=discord.Color.blurple())
        
        if state['current_track']:
            embed.add_field(name="Now Playing", value=f"▶️ **{state['current_track']['title']}** ({self.format_time(self.get_elapsed(state))})", inline=False)
            
        if queue:
            queue_str = ""
            for i, item in enumerate(queue[:10]):
                queue_str += f"`{i+1}.` {item['title']}\n"
            if len(queue) > 10:
                queue_str += f"\n*... and {len(queue) - 10} more tracks*"
            embed.add_field(name="Up Next", value=queue_str, inline=False)
        else:
            embed.add_field(name="Up Next", value="No upcoming tracks.", inline=False)
            
        await ctx.send(embed=embed)

    @commands.command(name="quit", aliases=["leave", "disconnect"], help="Disconnects the bot from the voice channel")
    async def quit(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
        vc = ctx.guild.voice_client
        if vc and vc.is_connected():
            await vc.disconnect()
            await ctx.send("Disconnected from the voice channel.")
        else:
            await ctx.send("Not connected to a voice channel.")

    @commands.command(name="clear", help="Clears the current queue")
    async def clear(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
        state['queue'].clear()
        await ctx.send("Queue has been cleared.")

    @commands.command(name="stop", help="Stops playback and clears the queue")
    async def stop(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
        state['queue'].clear()
        vc = ctx.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
        await ctx.send("Playback stopped and queue cleared.")

    @commands.command(name="help", help="Displays a list of available commands")
    async def help_command(self, ctx: commands.Context):
        embed = discord.Embed(
            title="🎧 Outa Music Bot",
            description="List of available commands:",
            color=discord.Color.blurple()
        )
        
        embed.add_field(name="▶️ `!play <query/url>`", value="Plays a track or playlist.", inline=False)
        embed.add_field(name="🎵 `!player` (or `!np`)", value="Displays the currently playing track.", inline=False)
        embed.add_field(name="⏸️ `!pause` & ▶️ `!resume`", value="Pauses and resumes playback.", inline=False)
        embed.add_field(name="⏹️ `!stop`", value="Stops playback and clears the queue.", inline=False)
        embed.add_field(name="⏭️ `!skip`", value="Skips the currently playing track.", inline=False)
        embed.add_field(name="⏩ `!forward <seconds>` & ⏪ `!back <seconds>`", value="Skips audio forward/backward (Default: 5 sec).", inline=False)
        embed.add_field(name="⏱️ `!seek <time>`", value="Jumps to a specific time (Example: `!seek 01:30`).", inline=False)
        embed.add_field(name="📜 `!queue`", value="Displays the music queue.", inline=False)
        embed.add_field(name="🗑️ `!drop <index>` &  🧹 `!clear`", value="Removes a specific track / Clears the entire queue.", inline=False)
        embed.add_field(name="🔀 `!shuffle` &  🔄 `!move <from> <to>`", value="Shuffles the queue or moves a track's position.", inline=False)
        embed.add_field(name="🔊 `!volume <1-100>`", value="Adjusts the playback volume.", inline=False)
        embed.add_field(name="🚪 `!quit`", value="Disconnects the bot from the voice channel.", inline=False)
        
        embed.set_footer(text="Note: The bot will automatically disconnect if you leave it alone in the channel.")
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.id == self.bot.user.id:
            if before.channel is not None and after.channel is None:
                guild_id = member.guild.id
                if guild_id in self.guild_states:
                    self.guild_states.pop(guild_id, None)
                self.cancel_timeout(guild_id)
        else:
            if before.channel is not None:
                bot_member = before.channel.guild.me
                if bot_member in before.channel.members:
                    non_bots = [m for m in before.channel.members if not m.bot]
                    if len(non_bots) == 0:
                        vc = before.channel.guild.voice_client
                        if vc and vc.is_connected():
                            await vc.disconnect()

async def setup(bot):
    await bot.add_cog(MusicCog(bot))