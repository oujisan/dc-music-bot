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

class PaginatorView(discord.ui.View):
    def __init__(self, embeds):
        super().__init__(timeout=180)
        self.embeds = embeds
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == len(self.embeds) - 1

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, custom_id="paginator_prev")
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, custom_id="paginator_next")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

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
                'previous_track': None,
                'loop': False,
                'loopqueue': False,
                'is_skipping': False,
                'is_replaying': False,
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

    async def inactivity_timeout(self, guild_id, vc):
        await asyncio.get_event_loop().create_task(asyncio.sleep(120))
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
        if state.get('is_seeking'):
            state['is_seeking'] = False
            await self.play_current_seek(guild_id, channel)
        else:
            current_track = state.get('current_track')
            if current_track:
                old_prev = state.get('previous_track')
                state['previous_track'] = current_track
                
                if state.get('is_skipping'):
                    state['is_skipping'] = False
                    if state.get('loopqueue'):
                        state['queue'].append(current_track)
                elif state.get('is_replaying'):
                    state['is_replaying'] = False
                    state['queue'].insert(0, current_track)
                    if old_prev:
                        state['queue'].insert(0, old_prev)
                else:
                    if state.get('loop'):
                        state['queue'].insert(0, current_track)
                    elif state.get('loopqueue'):
                        state['queue'].append(current_track)
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
                
                asyncio.create_task(self.prefetch_next(guild_id))
                
                is_live = data.get('is_live', False)
                track_name = data.get('track')
                artist_name = data.get('artist')
                raw_title = data.get('title', item['title'])
                
                if track_name:
                    title = f"{artist_name} - {track_name}" if artist_name else track_name
                else:
                    title = raw_title
                    
                if is_live:
                    title = f"🔴 [LIVE] {title}"

                url = data.get('webpage_url', item['webpage_url'])
                uploader = data.get('uploader', 'Unknown Artist')
                duration = data.get('duration')
                view_count = data.get('view_count')
                categories = data.get('categories')
                genre = categories[0] if categories else "Unknown"

                upload_date = data.get('upload_date')
                formatted_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}" if upload_date and len(upload_date) == 8 else None
                
                all_subs = set(data.get('subtitles', {}).keys()).union(set(data.get('automatic_captions', {}).keys()))
                target_langs = {'en': 'EN', 'id': 'ID', 'ja': 'JP', 'ko': 'KR'}
                found_subs = [target_langs[k] for k in target_langs if k in all_subs]
                subs_str = ", ".join(found_subs) if found_subs else None
                
                state['current_track'] = {
                    'webpage_url': url,
                    'title': title,
                    'uploader': uploader,
                    'duration': duration,
                    'view_count': view_count,
                    'genre': genre,
                    'upload_date': formatted_date,
                    'subtitles': subs_str,
                    'is_live': is_live
                }
                
                duration_str = self.format_time(duration) if duration and not is_live else "Live/Unknown"
                
                embed = discord.Embed(title="🎵  Now Playing", description=f"**[{title}]({url})**", color=discord.Color.from_rgb(255, 105, 180))
                embed.add_field(name="Channel", value=uploader, inline=True)
                embed.add_field(name="Duration", value=duration_str, inline=True)
                
                if view_count:
                    embed.add_field(name="Views", value=f"{view_count:,}", inline=True)
                
                if genre and genre != "Unknown":
                    embed.add_field(name="Genre", value=genre, inline=True)
                
                if subs_str:
                    embed.add_field(name="Subtitles", value=subs_str, inline=True)
                
                footer_text = "Outa • Youtube Music Bot"
                if formatted_date:
                    footer_text += f" • Uploaded: {formatted_date}"
                embed.set_footer(text=footer_text, icon_url=self.bot.user.display_avatar.url if self.bot.user.display_avatar else None)
                
                if state['now_playing_message']:
                    try:
                        await state['now_playing_message'].edit(embed=embed, view=None)
                    except discord.NotFound:
                        state['now_playing_message'] = await channel.send(embed=embed)
                else:
                    state['now_playing_message'] = await channel.send(embed=embed)
                
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

    @commands.command(name="play", aliases=["p"], help="Plays audio from a YouTube query or URLs separated by space")
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

        parts = search.split()
        if len(parts) > 1 and all(p.startswith("http://") or p.startswith("https://") for p in parts):
            if len(parts) > 5:
                await ctx.send("Limit exceeded: You can only batch add up to 5 URLs at a time. Only the first 5 will be processed.")
                queries = parts[:5]
            else:
                queries = parts
        else:
            queries = [search]

        added_count = 0
        added_titles = []
        for q in queries:
            try:
                if "http" in q:
                    query = q
                else:
                    query = f"ytsearch:{q}"

                data = await self.bot.loop.run_in_executor(
                    None, lambda: ytdl_search.extract_info(query, download=False)
                )
                
                if 'entries' in data:
                    entries = [entry for entry in list(data['entries']) if entry]
                    if not entries:
                        continue
                    if "ytsearch:" in query:
                        entries = [entries[0]]
                    
                    for entry in entries:
                        webpage_url = entry.get('url') or entry.get('webpage_url')
                        state['queue'].append({'webpage_url': webpage_url, 'title': entry.get('title')})
                        added_titles.append(entry.get('title'))
                    added_count += len(entries)
                else:
                    webpage_url = data.get('webpage_url') or data.get('original_url')
                    state['queue'].append({'webpage_url': webpage_url, 'title': data.get('title')})
                    added_titles.append(data.get('title'))
                    added_count += 1
            except Exception as e:
                await ctx.send(f"Failed to index '{q}': {str(e)}")

        if added_count > 1:
            await ctx.send(f"Indexed {added_count} tracks into the queue.")
        elif added_count == 1:
            await ctx.send(f"Indexed **{added_titles[0]}** into the queue.")
        elif added_count == 0:
            await ctx.send("No results found.")

        self.cancel_timeout(ctx.guild.id)

        if not vc.is_playing() and not vc.is_paused() and added_count > 0:
            await self.play_next(ctx.guild.id, ctx.channel)
        elif added_count > 0:
            asyncio.create_task(self.prefetch_next(ctx.guild.id))

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
    async def skip(self, ctx: commands.Context, index: int = None):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
        vc = ctx.guild.voice_client
        if vc and vc.is_playing():
            if index is not None:
                if index > 1 and index <= len(state['queue']) + 1:
                    skipped_tracks = state['queue'][:index - 1]
                    state['queue'] = state['queue'][index - 1:]
                    if state.get('loopqueue'):
                        state['queue'].extend(skipped_tracks)
                    await ctx.send(f"Skipping to track at index {index}.")
                elif index <= 1:
                    await ctx.send("Track skipped.")
                else:
                    return await ctx.send("Index out of range.")
            else:
                await ctx.send("Track skipped.")
            state['is_skipping'] = True
            vc.stop()
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

    @commands.command(name="drop", help="Removes a track or multiple tracks from the queue (e.g., 1,3,5-7)")
    async def drop(self, ctx: commands.Context, *, drop_input: str):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
        queue = state['queue']
        
        indices_to_drop = set()
        parts = drop_input.split(',')
        for part in parts:
            part = part.strip()
            if not part: continue
            if '-' in part:
                try:
                    start, end = map(int, part.split('-'))
                    if start <= end:
                        for i in range(start, end + 1):
                            indices_to_drop.add(i - 1)
                except ValueError:
                    pass
            else:
                try:
                    indices_to_drop.add(int(part) - 1)
                except ValueError:
                    pass
                    
        valid_indices = sorted([i for i in indices_to_drop if 0 <= i < len(queue)], reverse=True)
        
        if not valid_indices:
            return await ctx.send("No valid indices provided. Use `!queue` to verify track positions.")
            
        dropped_titles = []
        for i in valid_indices:
            item = queue.pop(i)
            dropped_titles.append(item['title'])
            
        if len(dropped_titles) == 1:
            await ctx.send(f"Dropped **{dropped_titles[0]}** from the queue.")
        else:
            await ctx.send(f"Dropped {len(dropped_titles)} tracks from the queue.")

        vc = ctx.guild.voice_client
        if len(queue) == 0 and vc and not vc.is_playing():
            if ctx.guild.id not in self.disconnect_tasks:
                self.disconnect_tasks[ctx.guild.id] = self.bot.loop.create_task(self.inactivity_timeout(ctx.guild.id, vc))

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
        uploader = track.get('uploader', 'Unknown Artist')
        duration = track.get('duration')
        view_count = track.get('view_count')
        genre = track.get('genre', 'Unknown')
        formatted_date = track.get('upload_date')
        subs_str = track.get('subtitles')
        is_live = track.get('is_live', False)
        
        duration_str = self.format_time(duration) if duration and not is_live else "Live/Unknown"
        elapsed_secs = self.get_elapsed(state)
        elapsed_str = self.format_time(elapsed_secs)
        
        embed = discord.Embed(title="🎵  Now Playing", description=f"**[{title}]({url})**", color=discord.Color.from_rgb(255, 105, 180))
        
        embed.add_field(name="Channel", value=uploader, inline=True)
        embed.add_field(name="Progress", value=f"{elapsed_str} / {duration_str}", inline=True)
        
        if view_count:
            embed.add_field(name="Views", value=f"{view_count:,}", inline=True)
            
        if genre and genre != "Unknown":
            embed.add_field(name="Genre", value=genre, inline=True)
        
        if subs_str:
            embed.add_field(name="Subtitles", value=subs_str, inline=True)
            
        footer_text = "Outa • Youtube Music Bot"
        if formatted_date:
            footer_text += f" • Uploaded: {formatted_date}"
        embed.set_footer(text=footer_text, icon_url=self.bot.user.display_avatar.url if self.bot.user.display_avatar else None)
        
        await ctx.send(embed=embed)

    @commands.command(name="queue", help="Displays the current queue")
    async def queue(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        queue = state['queue']
        if not queue and not state['current_track']:
            return await ctx.send("The queue is currently empty.")
        
        embeds = []
        items_per_page = 10
        total_pages = max(1, (len(queue) + items_per_page - 1) // items_per_page) if queue else 1
        
        for page in range(total_pages):
            embed = discord.Embed(title="📜 Music Queue", color=discord.Color.blurple())
            
            if page == 0 and state['current_track']:
                embed.add_field(name="Now Playing", value=f"▶️ **{state['current_track']['title']}** ({self.format_time(self.get_elapsed(state))})", inline=False)
                
            start_idx = page * items_per_page
            end_idx = start_idx + items_per_page
            page_items = queue[start_idx:end_idx]
            
            if page_items:
                queue_str = ""
                for i, item in enumerate(page_items):
                    queue_str += f"`{start_idx + i + 1}.` {item['title']}\n"
                embed.add_field(name="Up Next", value=queue_str, inline=False)
            elif not queue:
                embed.add_field(name="Up Next", value="No upcoming tracks.", inline=False)
                
            embed.set_footer(text=f"Page {page+1}/{total_pages} | Outa • Youtube Music Bot")
            embeds.append(embed)
            
        if len(embeds) == 1:
            await ctx.send(embed=embeds[0])
        else:
            view = PaginatorView(embeds)
            await ctx.send(embed=embeds[0], view=view)

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
        state['loopqueue'] = False
        await ctx.send("Queue has been cleared and queue loop disabled.")

    @commands.command(name="stop", help="Stops playback and clears the queue")
    async def stop(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
        state['queue'].clear()
        state['loop'] = False
        state['loopqueue'] = False
        state['is_skipping'] = True
        vc = ctx.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
        await ctx.send("Playback stopped, queue cleared, and loops disabled.")

    @commands.command(name="transfer", help="Transfers the DJ role to another user")
    async def transfer(self, ctx: commands.Context, target: discord.Member):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
            
        vc = ctx.guild.voice_client
        if not vc or not vc.is_connected():
            return await ctx.send("The bot is not connected to a voice channel.")
            
        if target not in vc.channel.members:
            return await ctx.send(f"{target.display_name} is not in the voice channel.")
            
        if target.bot:
            return await ctx.send("You cannot transfer the DJ role to a bot.")
            
        state['session_owner'] = target.id
        await ctx.send(f"The DJ role has been transferred to {target.mention}!")

    @commands.command(name="dj", help="Shows the current DJ")
    async def show_dj(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        owner_id = state.get('session_owner')
        if owner_id:
            await ctx.send(f"👑 The current DJ is <@{owner_id}>.")
        else:
            await ctx.send("There is no DJ currently.")

    @commands.command(name="loop", help="Toggles looping for the current track")
    async def loop(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
        state['loop'] = not state.get('loop', False)
        if state['loop']:
            state['loopqueue'] = False
            await ctx.send("🔁 **Loop is now ON** for the current track.")
        else:
            await ctx.send("🔁 **Loop is now OFF**.")

    @commands.command(name="loopqueue", aliases=["lq"], help="Toggles looping for the entire queue")
    async def loopqueue(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
        state['loopqueue'] = not state.get('loopqueue', False)
        if state['loopqueue']:
            state['loop'] = False
            await ctx.send("🔁 **Queue Loop is now ON**.")
        else:
            await ctx.send("🔁 **Queue Loop is now OFF**.")

    @commands.command(name="replay", aliases=["previous"], help="Replays the previously played track")
    async def replay(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
        
        if not state.get('previous_track'):
            return await ctx.send("There is no previously played track.")
            
        vc = ctx.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            state['is_replaying'] = True
            vc.stop()
            await ctx.send(f"Replaying **{state['previous_track']['title']}**...")
        else:
            state['queue'].insert(0, state['previous_track'])
            await ctx.send(f"Replaying **{state['previous_track']['title']}**...")
            await self.play_next(ctx.guild.id, ctx.channel)

    @commands.command(name="ping", help="Checks the bot's latency to the server")
    async def ping(self, ctx: commands.Context):
        latency = round(self.bot.latency * 1000)
        
        if latency < 100:
            status = f"🟢 Excellent ({latency} ms)"
        elif latency < 200:
            status = f"🟡 Good ({latency} ms)"
        elif latency < 500:
            status = f"🟠 Fair ({latency} ms)"
        else:
            status = f"🔴 Poor ({latency} ms)"
            
        embed = discord.Embed(
            title="🏓 Pong!",
            description=f"**Status:** {status}",
            color=discord.Color.green() if latency < 200 else discord.Color.orange() if latency < 500 else discord.Color.red()
        )
        embed.set_footer(text="Outa • Youtube Music Bot", icon_url=self.bot.user.display_avatar.url if self.bot.user.display_avatar else None)
        await ctx.send(embed=embed)

    @commands.command(name="credit", help="Displays the creator of the bot")
    async def credit(self, ctx: commands.Context):
        embed = discord.Embed(
            title="✨ Credits",
            description="Created with ❤️ by **Vou Aka. Oujisan**\nPowered by the intelligence of **Gemini AI**\n\n🐙 **[GitHub Repository](https://github.com/oujisan/dc-music-bot)**",
            color=discord.Color.gold()
        )
        embed.set_footer(text="Outa • Youtube Music Bot", icon_url=self.bot.user.display_avatar.url if self.bot.user.display_avatar else None)
        await ctx.send(embed=embed)

    @commands.command(name="help", help="Displays a list of available commands")
    async def help_command(self, ctx: commands.Context):
        commands_list = [
            ("▶️ `!play <query/url>`", "Plays a track or playlist."),
            ("🎵 `!player` (or `!np`)", "Displays the currently playing track."),
            ("⏸️ `!pause` & ▶️ `!resume`", "Pauses and resumes playback."),
            ("⏹️ `!stop`", "Stops playback and clears the queue."),
            ("⏭️ `!skip [index]`", "Skips current track or skips to index."),
            ("⏩ `!forward <seconds>` & ⏪ `!back <seconds>`", "Skips audio forward/backward."),
            ("🔁 `!loop` & `!loopqueue`", "Toggles loop for current track / entire queue."),
            ("⏪ `!replay`", "Replays the previously played track."),
            ("⏱️ `!seek <time>`", "Jumps to a specific time (Example: `!seek 01:30`)."),
            ("📜 `!queue`", "Displays the music queue."),
            ("🗑️ `!drop <indices>`", "Removes tracks (e.g., `1,3,5-7`) / `!clear` empties it."),
            ("🔀 `!shuffle` &  🔄 `!move <from> <to>`", "Shuffles or moves a track's position."),
            ("🔊 `!volume <1-100>`", "Adjusts the playback volume."),
            ("👑 `!dj` & `!transfer <@user>`", "Shows the current DJ or transfers the role."),
            ("🏓 `!ping`", "Checks the bot's latency to the server."),
            ("✨ `!credit`", "Displays the creator of the bot."),
            ("🚪 `!quit`", "Disconnects the bot from the voice channel.")
        ]
        
        embeds = []
        items_per_page = 6
        total_pages = max(1, (len(commands_list) + items_per_page - 1) // items_per_page)
        
        for page in range(total_pages):
            embed = discord.Embed(
                title="🎧 Outa Music Bot",
                description="List of available commands:",
                color=discord.Color.blurple()
            )
            
            start_idx = page * items_per_page
            end_idx = start_idx + items_per_page
            page_items = commands_list[start_idx:end_idx]
            
            for name, value in page_items:
                embed.add_field(name=name, value=value, inline=False)
                
            embed.set_footer(text=f"Page {page+1}/{total_pages} | The bot will automatically disconnect if you leave it alone in the channel.")
            embeds.append(embed)
            
        if len(embeds) == 1:
            await ctx.send(embed=embeds[0])
        else:
            view = PaginatorView(embeds)
            await ctx.send(embed=embeds[0], view=view)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.id == self.bot.user.id:
            if before.channel is not None and after.channel is None:
                guild_id = member.guild.id
                if guild_id in self.guild_states:
                    self.guild_states.pop(guild_id, None)
                self.cancel_timeout(guild_id)
        else:
            if before.channel is not None and (after.channel is None or after.channel != before.channel):
                bot_member = before.channel.guild.me
                if bot_member in before.channel.members:
                    non_bots = [m for m in before.channel.members if not m.bot]
                    if len(non_bots) == 0:
                        vc = before.channel.guild.voice_client
                        if vc and vc.is_connected():
                            await vc.disconnect()
                    else:
                        state = self.guild_states.get(before.channel.guild.id)
                        if state and state.get('session_owner') == member.id:
                            new_owner = non_bots[0]
                            state['session_owner'] = new_owner.id
                            if state.get('bound_channel'):
                                asyncio.create_task(state['bound_channel'].send(f"The previous DJ left. **{new_owner.display_name}** is now the DJ!"))

async def setup(bot):
    await bot.add_cog(MusicCog(bot))