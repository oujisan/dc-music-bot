# cogs/music.py
import discord
from discord.ext import commands
import yt_dlp
import asyncio
import time
import random
import aiohttp
import json
import io
import re
from config import YTDL_SEARCH_OPTIONS, YTDL_STREAM_OPTIONS, FFMPEG_OPTIONS

BOT_VERSION = "1.7.1"

ytdl_search = yt_dlp.YoutubeDL(YTDL_SEARCH_OPTIONS)
ytdl_stream = yt_dlp.YoutubeDL(YTDL_STREAM_OPTIONS)

def clean_title(title):
    if not title:
        return " "
    invisible_chars = re.compile(r'[\s\u200b-\u200d\u200e\u200f\ufeff\u202a-\u202e\u2060]+')
    cleaned = invisible_chars.sub('', title)
    if not cleaned:
        return " "
    return title.strip()

def deduplicate_lines(lines):
    if not lines:
        return []
    cleaned = []
    for line in lines:
        if cleaned and line == cleaned[-1]:
            continue
        if not cleaned:
            cleaned.append(line)
            continue
        prev = cleaned[-1]
        prev_words = prev.split()
        curr_words = line.split()
        max_overlap = min(len(prev_words), len(curr_words))
        overlap_found = False
        for k in range(max_overlap, 0, -1):
            p_slice = [re.sub(r'[^\w]', '', w.lower()) for w in prev_words[-k:]]
            c_slice = [re.sub(r'[^\w]', '', w.lower()) for w in curr_words[:k]]
            if p_slice == c_slice and any(w for w in p_slice):
                merged = prev + " " + " ".join(curr_words[k:])
                cleaned[-1] = merged.strip()
                overlap_found = True
                break
        if not overlap_found:
            cleaned.append(line)
    return cleaned

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

AUDIO_FILTERS = {
    "bassboost": "bass=g=20",
    "nightcore": "asetrate=48000*1.25,aresample=48000,atempo=1.0",
    "vaporwave": "asetrate=48000*0.8,aresample=48000,atempo=1.0",
    "karaoke": "asplit=2[mid_source][side_source];[mid_source]pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1,equalizer=f=1000:width_type=h:width=3000:g=-25[mid_attenuated];[side_source]pan=stereo|c0=0.5*c0-0.5*c1|c1=-0.5*c0+0.5*c1[side];[mid_attenuated][side]amix=inputs=2:normalize=0",
    "8d": "apulsator=hz=0.08",
    "clear": ""
}

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
                'session_owner': None,
                'autoplay': False,
                'autoplay_query': None,
                'played_history': [],
                'current_filter': "clear",
                'autoplay_failures': 0,
                'speed': 1.0,
                'http_headers': {}
            }
        return self.guild_states[guild_id]

    def is_dj(self, member: discord.Member, state: dict) -> bool:
        if state['session_owner'] and state['session_owner'] != member.id and not member.guild_permissions.administrator:
            return False
        return True

    def get_speed_filter(self, speed: float) -> str:
        if speed == 1.0:
            return ""
        filters = []
        while speed < 0.5:
            filters.append("atempo=0.5")
            speed /= 0.5
        if speed != 1.0:
            filters.append(f"atempo={speed:.2f}")
        return ",".join(filters)

    def get_elapsed(self, state):
        if state['start_time'] == 0:
            return 0
        speed = state.get('speed', 1.0)
        if state['paused_time'] > 0:
            real_elapsed = state['paused_time'] - state['start_time'] - state['total_paused_duration']
        else:
            real_elapsed = time.time() - state['start_time'] - state['total_paused_duration']
        return int(real_elapsed * speed + state['current_seek'])

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
            
            elapsed = time.time() - state.get('start_time', 0)
            if elapsed < 3 and not state.get('is_skipping') and not state.get('is_replaying') and not state.get('is_seeking'):
                state['autoplay_failures'] = state.get('autoplay_failures', 0) + 1
                if state.get('autoplay') and state['autoplay_failures'] >= 3:
                    state['autoplay'] = False
                    asyncio.run_coroutine_threadsafe(
                        channel.send("⚠️ Autoplay automatically disabled due to 3 consecutive track failures."),
                        self.bot.loop
                    )
                    state['autoplay_failures'] = 0
                    return
            elif elapsed >= 3:
                state['autoplay_failures'] = 0

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
        
        if len(queue) == 0 and state.get('autoplay') and not state.get('is_skipping') and not state.get('is_replaying'):
            try:
                search_query = "top music mix"
                if state.get('autoplay_query'):
                    search_query = f"{state['autoplay_query']} music"
                elif state.get('previous_track'):
                    prev = state['previous_track']
                    if prev.get('tags'):
                        first_tag = prev['tags'].split(',')[0].strip()
                        search_query = f"{first_tag} music"
                    elif prev.get('uploader') and prev['uploader'] != 'Unknown Artist':
                        search_query = f"{prev['uploader']} mix"
                    else:
                        search_query = f"{prev['title']} mix"

                import urllib.parse
                query = f"https://music.youtube.com/search?q={urllib.parse.quote(search_query)}"
                data = await self.bot.loop.run_in_executor(
                    None, lambda: ytdl_search.extract_info(query, download=False)
                )
                if 'entries' in data and data['entries']:
                    entries = [e for e in data['entries'] if e]
                    # Filter to only actual track/video results from YouTube Music search
                    entries = [
                        e for e in entries 
                        if (e.get('title') is not None) and ('watch?v=' in (e.get('url') or e.get('webpage_url') or ''))
                    ]
                    if entries:
                        history = state.get('played_history', [])
                        unplayed = [e for e in entries if e.get('url', e.get('webpage_url')) not in history]
                        track = random.choice(unplayed) if unplayed else random.choice(entries)
                        
                        webpage_url = track.get('url') or track.get('webpage_url')
                        queue.append({'webpage_url': webpage_url, 'title': clean_title(track.get('title'))})
            except Exception:
                pass
        
        if len(queue) > 0:
            self.cancel_timeout(guild_id)
            item = queue.pop(0)
            state['current_track'] = item
            
            history = state['played_history']
            url = item.get('webpage_url')
            if url and url not in history:
                history.append(url)
            if len(history) > 50:
                history.pop(0)
            
            try:
                if 'prefetched_data' in item and item['prefetched_data'] != "loading":
                    data = item['prefetched_data']
                else:
                    data = await self.bot.loop.run_in_executor(
                        None, lambda: ytdl_stream.extract_info(item['webpage_url'], download=False)
                    )
                state['stream_url'] = data['url']
                state['http_headers'] = data.get('http_headers', {})
                
                options = dict(FFMPEG_OPTIONS)
                
                headers = state.get('http_headers', {})
                if headers:
                    headers_list = [f"{k}: {v}" for k, v in headers.items()]
                    headers_str = "\r\n".join(headers_list) + "\r\n"
                    headers_str_escaped = headers_str.replace('"', '\\"')
                    options['before_options'] = f"{options.get('before_options', '')} -headers \"{headers_str_escaped}\""
                
                filter_list = []
                if state.get('current_filter') and state['current_filter'] != "clear":
                    filter_list.append(AUDIO_FILTERS[state['current_filter']])
                
                speed = state.get('speed', 1.0)
                if speed != 1.0:
                    speed_filter = self.get_speed_filter(speed)
                    if speed_filter:
                        filter_list.append(speed_filter)
                
                if filter_list:
                    vf_str = ",".join(filter_list)
                    options['options'] = f"{options.get('options', '')} -filter:a \"{vf_str}\""
                
                source = discord.FFmpegPCMAudio(state['stream_url'], **options)
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
                
                title = clean_title(title)
                    
                if is_live:
                    title = f"🔴 [LIVE] {title}"

                url = data.get('webpage_url', item['webpage_url'])
                uploader = data.get('uploader', 'Unknown Artist')
                duration = data.get('duration')
                view_count = data.get('view_count')
                tags_list = data.get('tags', [])
                tags = ", ".join(tags_list[:3]) if tags_list else None
                thumbnail = data.get('thumbnail', item.get('thumbnail'))

                upload_date = data.get('upload_date')
                formatted_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}" if upload_date and len(upload_date) == 8 else None
                
                subs_data = data.get('subtitles', {})
                auto_data = data.get('automatic_captions', {})
                target_langs = {'en': 'EN', 'id': 'ID', 'ja': 'JP', 'ko': 'KR'}
                
                found_subs = []
                for lang_code, display_name in target_langs.items():
                    sub_list = subs_data.get(lang_code) or auto_data.get(lang_code)
                    if sub_list:
                        # Only count it as found if it has at least one json3 or vtt format
                        if any(s.get('ext') in ['json3', 'vtt'] for s in sub_list):
                            found_subs.append(display_name)
                
                subs_str = ", ".join(found_subs) if found_subs else None
                
                state['current_track'] = {
                    'webpage_url': url,
                    'title': title,
                    'uploader': uploader,
                    'duration': duration,
                    'view_count': view_count,
                    'tags': tags,
                    'upload_date': formatted_date,
                    'subtitles': subs_str,
                    'is_live': is_live,
                    'subtitles_data': data.get('subtitles', {}),
                    'auto_captions_data': data.get('automatic_captions', {}),
                    'thumbnail': thumbnail
                }
                
                duration_str = self.format_time(duration) if duration and not is_live else "Live/Unknown"
                
                embed = discord.Embed(title="🎵  Now Playing", description=f"**[{title}]({url})**", color=discord.Color.from_rgb(255, 105, 180))
                if thumbnail:
                    embed.set_thumbnail(url=thumbnail)
                embed.add_field(name="Channel", value=uploader, inline=True)
                embed.add_field(name="Duration", value=duration_str, inline=True)
                
                if view_count:
                    embed.add_field(name="Views", value=f"{view_count:,}", inline=True)
                
                if tags:
                    embed.add_field(name="Tags", value=tags, inline=True)
                if subs_str:
                    embed.add_field(name="Subtitles", value=subs_str, inline=True)
                if formatted_date:
                    embed.add_field(name="Uploaded", value=formatted_date, inline=True)
                
                footer_text = "Outa • Youtube Music Bot"
                embed.set_footer(text=footer_text, icon_url=self.bot.user.display_avatar.url if self.bot.user.display_avatar else None)
                
                if state['now_playing_message']:
                    try:
                        await state['now_playing_message'].delete()
                    except discord.NotFound:
                        pass
                state['now_playing_message'] = await channel.send(embed=embed)
                
            except Exception as e:
                state['autoplay_failures'] = state.get('autoplay_failures', 0) + 1
                if state.get('autoplay') and state['autoplay_failures'] >= 3:
                    state['autoplay'] = False
                    await channel.send("⚠️ Autoplay automatically disabled due to 3 consecutive track failures.")
                    state['autoplay_failures'] = 0
                    return
                await channel.send(f"Failed to play **{item['title']}**: Skipping...")
                await asyncio.sleep(1)
                await self.play_next(guild_id, channel)
        else:
            state['current_track'] = None
            state['stream_url'] = None
            if state['now_playing_message']:
                try:
                    await state['now_playing_message'].delete()
                    state['now_playing_message'] = None
                except discord.NotFound:
                    pass
            if guild_id not in self.disconnect_tasks:
                self.disconnect_tasks[guild_id] = self.bot.loop.create_task(self.inactivity_timeout(guild_id, vc))

    async def play_current_seek(self, guild_id, channel):
        state = self.get_state(guild_id)
        target_seconds = state['current_seek']
        vc = self.bot.get_guild(guild_id).voice_client
        
        custom_before = f"{FFMPEG_OPTIONS['before_options']} -ss {target_seconds}"
        
        headers = state.get('http_headers', {})
        if headers:
            headers_list = [f"{k}: {v}" for k, v in headers.items()]
            headers_str = "\r\n".join(headers_list) + "\r\n"
            headers_str_escaped = headers_str.replace('"', '\\"')
            custom_before = f"{custom_before} -headers \"{headers_str_escaped}\""
        
        options_str = FFMPEG_OPTIONS['options']
        filter_list = []
        if state.get('current_filter') and state['current_filter'] != "clear":
            filter_list.append(AUDIO_FILTERS[state['current_filter']])
            
        speed = state.get('speed', 1.0)
        if speed != 1.0:
            speed_filter = self.get_speed_filter(speed)
            if speed_filter:
                filter_list.append(speed_filter)
                
        if filter_list:
            vf_str = ",".join(filter_list)
            options_str = f"{options_str} -filter:a \"{vf_str}\""
            
        source = discord.FFmpegPCMAudio(state['stream_url'], before_options=custom_before, options=options_str)
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
                    import urllib.parse
                    query = f"https://music.youtube.com/search?q={urllib.parse.quote(q)}"

                data = await self.bot.loop.run_in_executor(
                    None, lambda: ytdl_search.extract_info(query, download=False)
                )
                
                if 'entries' in data:
                    entries = [entry for entry in list(data['entries']) if entry]
                    if not entries:
                        continue
                    if "music.youtube.com/search" in query:
                        # Only keep entries that are tracks and have a title
                        entries = [
                            entry for entry in entries 
                            if (entry.get('title') is not None) and ('watch?v=' in (entry.get('url') or entry.get('webpage_url') or ''))
                        ]
                        if not entries:
                            continue
                        entries = [entries[0]]
                    
                    for entry in entries:
                        webpage_url = entry.get('url') or entry.get('webpage_url')
                        title = clean_title(entry.get('title'))
                        state['queue'].append({'webpage_url': webpage_url, 'title': title})
                        added_titles.append(title)
                    added_count += len(entries)
                else:
                    webpage_url = data.get('webpage_url') or data.get('original_url')
                    title = clean_title(data.get('title'))
                    state['queue'].append({'webpage_url': webpage_url, 'title': title})
                    added_titles.append(title)
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
        tags = track.get('tags')
        formatted_date = track.get('upload_date')
        subs_str = track.get('subtitles')
        is_live = track.get('is_live', False)
        thumbnail = track.get('thumbnail')
        
        duration_str = self.format_time(duration) if duration and not is_live else "Live/Unknown"
        elapsed_secs = self.get_elapsed(state)
        elapsed_str = self.format_time(elapsed_secs)
        
        embed = discord.Embed(title="🎵  Now Playing", description=f"**[{title}]({url})**", color=discord.Color.from_rgb(255, 105, 180))
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
            
        embed.add_field(name="Channel", value=uploader, inline=True)
        embed.add_field(name="Progress", value=f"{elapsed_str} / {duration_str}", inline=True)
        
        if view_count:
            embed.add_field(name="Views", value=f"{view_count:,}", inline=True)
            
        if tags:
            embed.add_field(name="Tags", value=tags, inline=True)
        if subs_str:
            embed.add_field(name="Subtitles", value=subs_str, inline=True)
        if formatted_date:
            embed.add_field(name="Uploaded", value=formatted_date, inline=True)
            
        footer_text = "Outa • Youtube Music Bot"
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

    @commands.command(name="subs", aliases=["subtitle", "lyrics"], help="Fetches subtitles for the currently playing track. Usage: !subs [language_code]")
    async def subs(self, ctx: commands.Context, lang_code: str = None):
        state = self.get_state(ctx.guild.id)
        if not state['current_track']:
            return await ctx.send("Nothing is currently playing.")
            
        track = state['current_track']
        subs_data = track.get('subtitles_data', {})
        auto_data = track.get('auto_captions_data', {})
        
        if not subs_data and not auto_data:
            return await ctx.send("No subtitles or closed captions available for this track.")
            
        if not lang_code:
            available = list(subs_data.keys()) + [f"{k} (auto)" for k in auto_data.keys()]
            return await ctx.send(f"Please provide a language code (e.g., `!subs en`).\nAvailable languages: {', '.join(available[:20])}")
            
        lang_code = lang_code.lower()
        sub_list = subs_data.get(lang_code) or auto_data.get(lang_code)
        
        if not sub_list:
            return await ctx.send(f"Subtitle for language `{lang_code}` not found.")
            
        target_sub = next((s for s in sub_list if s.get('ext') == 'json3'), None)
        if not target_sub:
            target_sub = next((s for s in sub_list if s.get('ext') == 'vtt'), None)
            
        if not target_sub:
            return await ctx.send(f"Could not find a parsable subtitle format (json3/vtt) for `{lang_code}`.")
            
        url = target_sub.get('url')
        try:
            headers = state.get('http_headers', {})
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return await ctx.send("Failed to download subtitles.")
                    text_data = await resp.text()
                    
            lines = []
            if target_sub['ext'] == 'json3':
                try:
                    json_data = json.loads(text_data)
                    for event in json_data.get("events", []):
                        if "segs" in event:
                            line = "".join(seg.get("utf8", "") for seg in event["segs"]).strip()
                            if line:
                                for l in line.split('\n'):
                                    l_strip = l.strip()
                                    if l_strip:
                                        lines.append(l_strip)
                except Exception:
                    return await ctx.send("Error parsing JSON subtitle.")
            else:
                raw_lines = text_data.split('\n')
                for line in raw_lines:
                    line = line.strip()
                    if not line or line == "WEBVTT" or "-->" in line or line.startswith("Kind:") or line.startswith("Language:"):
                        continue
                    line = re.sub(r'<[^>]+>', '', line).strip()
                    if line:
                        lines.append(line)
                        
            deduped = deduplicate_lines(lines)
            parsed_text = "\n".join(deduped)
            
            if not parsed_text.strip():
                return await ctx.send("Subtitle file is empty.")
                
            file = discord.File(io.BytesIO(parsed_text.encode('utf-8')), filename=f"{track['title']}_{lang_code}_subs.txt")
            await ctx.send(content=f"Here are the `{lang_code}` subtitles/lyrics for **{track['title']}**:", file=file)
            
        except Exception as e:
            await ctx.send(f"An error occurred while fetching subtitles: {str(e)}")

    @commands.command(name="autoplay", aliases=["ap"], help="Toggles autoplay and sets an optional tag")
    async def autoplay(self, ctx: commands.Context, *, tag: str = None):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
        
        if tag:
            state['autoplay'] = True
            state['autoplay_query'] = tag
            await ctx.send(f"🤖 **Autoplay is now ON**. Tag targeted to: `{tag}`")
        else:
            state['autoplay'] = not state.get('autoplay', False)
            state['autoplay_query'] = None
            if state['autoplay']:
                await ctx.send("🤖 **Autoplay is now ON**. The bot will play recommended songs automatically.")
            else:
                await ctx.send("🤖 **Autoplay is now OFF**.")
                
        vc = ctx.guild.voice_client
        if state['autoplay'] and len(state['queue']) == 0 and vc and not vc.is_playing() and not vc.is_paused():
            await self.play_next(ctx.guild.id, ctx.channel)

    @commands.command(name="filter", help="Applies an audio filter (e.g. bassboost, nightcore, clear)")
    async def apply_filter(self, ctx: commands.Context, filter_name: str = "clear"):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
            
        filter_name = filter_name.lower()
        if filter_name not in AUDIO_FILTERS:
            valid_filters = ", ".join([f"`{f}`" for f in AUDIO_FILTERS.keys()])
            return await ctx.send(f"❌ Invalid filter. Available filters: {valid_filters}")
            
        state['current_filter'] = filter_name
        
        if filter_name == "clear":
            await ctx.send("🧹 **Filters cleared**.")
        else:
            await ctx.send(f"🎛️ **Filter applied:** `{filter_name}`")
            
        vc = ctx.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            current_elapsed = self.get_elapsed(state)
            await self.execute_seek_signal(ctx.guild.id, ctx.channel, current_elapsed)

    @commands.command(name="speed", help="Sets the audio playback speed (0.1 - 2.0) or 'normal'/'clear' to reset")
    async def speed(self, ctx: commands.Context, speed_input: str = "normal"):
        state = self.get_state(ctx.guild.id)
        if not self.is_dj(ctx.author, state):
            return await ctx.send("Only the person who requested the first track (or an Admin) can control the bot.")
            
        speed_input = speed_input.lower()
        if speed_input in ["normal", "clear"]:
            state['speed'] = 1.0
            await ctx.send("⚡ **Speed reset to normal (1.0x)**.")
        else:
            try:
                val = float(speed_input)
                if val < 0.1 or val > 2.0:
                    return await ctx.send("❌ Speed must be between 0.1 and 2.0.")
                state['speed'] = val
                await ctx.send(f"⚡ **Playback speed set to {val}x**.")
            except ValueError:
                return await ctx.send("❌ Invalid speed value. Use a number between 0.1 and 2.0, or 'normal'/'clear'.")
                
        vc = ctx.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            current_elapsed = self.get_elapsed(state)
            await self.execute_seek_signal(ctx.guild.id, ctx.channel, current_elapsed)

    @commands.command(name="credit", help="Displays the creator of the bot")
    async def credit(self, ctx: commands.Context):
        embed = discord.Embed(
            title="✨ Credits",
            description=f"Created with ❤️ by **Vou Aka. Oujisan**\nPowered by the intelligence of **Gemini AI**\n\n🐙 **[GitHub Repository](https://github.com/oujisan/dc-music-bot)**\n\n🏷️ **Version:** {BOT_VERSION}",
            color=discord.Color.gold()
        )
        embed.set_footer(text="Outa • Youtube Music Bot", icon_url=self.bot.user.display_avatar.url if self.bot.user.display_avatar else None)
        await ctx.send(embed=embed)

    @commands.command(name="help", help="Displays a list of available commands")
    async def help_command(self, ctx: commands.Context):
        commands_dict = {
            "🎶 Playback Controls": [
                ("▶️ `!play <query/url>`", "Plays a track or playlist."),
                ("⏸️ `!pause`", "Pauses playback."),
                ("▶️ `!resume`", "Resumes playback."),
                ("⏹️ `!stop`", "Stops playback and clears the queue."),
                ("⏭️ `!skip [index]`", "Skips current track or skips to index."),
                ("⏪ `!replay`", "Replays the previously played track."),
                ("⏩ `!forward <seconds>`", "Skips audio forward by seconds."),
                ("⏪ `!back <seconds>`", "Skips audio backward by seconds."),
                ("⏱️ `!seek <time>`", "Jumps to a specific time (e.g. `01:30`)."),
                ("🔊 `!volume <1-100>`", "Adjusts the playback volume."),
                ("⚡ `!speed <value>`", "Sets the audio speed (0.1 - 2.0) or 'normal'/'clear'.")
            ],
            "📜 Queue Management": [
                ("📜 `!queue`", "Displays the music queue."),
                ("🎵 `!player` (or `!np`)", "Displays the currently playing track."),
                ("🤖 `!autoplay [tag]`", "Toggles autoplay (optional: specific tag)."),
                ("🎛️ `!filter <name>`", "Applies an audio filter (bassboost, nightcore, vaporwave, karaoke, 8d, clear)."),
                ("🔁 `!loop`", "Toggles loop for current track."),
                ("🔁 `!loopqueue` (or `!lq`)", "Toggles loop for the entire queue."),
                ("🗑️ `!drop <indices>`", "Removes specific tracks (e.g., `1,3,5-7`)."),
                ("🗑️ `!clear`", "Empties the queue."),
                ("🔀 `!shuffle`", "Shuffles the queue."),
                ("🔄 `!move <from> <to>`", "Moves a track's position in the queue.")
            ],
            "⚙️ Session & Utilities": [
                ("👑 `!dj`", "Shows the current DJ."),
                ("👑 `!transfer <@user>`", "Transfers the DJ role to another user."),
                ("💬 `!subs [lang_code]`", "Fetches subtitles/lyrics for the currently playing track."),
                ("🚪 `!quit`", "Disconnects the bot from the voice channel."),
                ("🏓 `!ping`", "Checks the bot's latency to the server."),
                ("✨ `!credit`", "Displays the creator of the bot & version.")
            ]
        }
        
        embeds = []
        total_pages = len(commands_dict)
        
        for i, (category, commands) in enumerate(commands_dict.items()):
            embed = discord.Embed(
                title="🎧 Outa Music Bot",
                description=f"\n\n**{category}**",
                color=discord.Color.blurple()
            )
            
            for name, value in commands:
                embed.add_field(name=name, value=value, inline=False)
                
            embed.set_footer(text=f"Page {i+1}/{total_pages} | The bot will automatically disconnect if you leave it alone in the channel.")
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